"""Exercise Compliance with coordinator-like inputs from the real agent workflow.

Run from the repository root with:
    .\\frontend\\venv\\Scripts\\python.exe -m backend.agents.test_compliance_rag

News Verification and Risk Manager use their real deterministic reports. The
Financial Analyst's real bounded tool loop is driven by a small scripted model
runner so this test spends live model calls only on Compliance. Compliance uses
the configured LLM and the normal Qwen/Qdrant + BM25 retriever. Full output is
saved to results/compliance_rag_report.txt.
"""
import contextlib
import io
import json
import sys
import time
from pathlib import Path

from backend.agents.compliance_officer import run_compliance_officer
from backend.agents.financial_analyst import run_financial_analyst
from backend.agents.news_verification import run_news_verification
from backend.agents.output_schema import parse_json_object
from backend.agents.risk_manager import run_risk_manager
from backend.llm_client import LLMClient
from backend.agents.main_agent import scenario_inputs


MIN_MODEL_CALL_INTERVAL_SECONDS = 5.0
_last_model_call = 0.0


# Expected outcomes are for the post-run evaluator only. They are never passed
# to any agent. Cases deliberately vary the kind of action and fact coverage.
CASES = [
    {
        "id": "coordinator_liquidity_buffered_draw",
        "expected": "compliant",
        "action": "hold",
        "facts": {
            "financials": {"capital": 200, "liquidity": 25, "borrowing_limit": 20,
                           "daily_withdrawals": 10, "forecast_next_7d": 100},
            "regulations": {"max_draw_facility": 80,
                "bank_status": "Singapore reporting bank; elected the applicable minimum liquid assets approach with required notice given.",
                "all_currency_position": {"qualifying_liabilities": 1000, "liquid_assets": 200, "tier1_liquid_assets": 100},
                "singapore_dollar_position": {"qualifying_liabilities": 800, "liquid_assets": 160, "tier1_liquid_assets": 80}},
        },
        "trigger": "A verified wholesale funding disruption is increasing near-term cash outflows.",
        "explanation": "The case supplies applicable bank status and both currency-basis asset positions above the stated minimums; the model must still find and cite relevant corpus passages.",
    },
    {
        "id": "coordinator_interbank_funding_shortfall",
        "expected": "non_compliant",
        "action": "hold",
        "facts": {
            "financials": {"capital": 180, "liquidity": 20, "borrowing_limit": 90,
                           "daily_withdrawals": 12, "forecast_next_7d": 120},
            "regulations": {"max_draw_facility": 50,
                "bank_status": "Singapore reporting bank; elected the applicable minimum liquid assets approach with required notice given.",
                "all_currency_position": {"qualifying_liabilities": 1000, "liquid_assets": 150, "tier1_liquid_assets": 80},
                "singapore_dollar_position": {"qualifying_liabilities": 800, "liquid_assets": 128, "tier1_liquid_assets": 64}},
        },
        "trigger": "Several counterparties have shortened unsecured funding tenors amid market stress.",
        "explanation": "The all-currency liquid-asset position is below the applicable stated floor; whether the model identifies and cites the rule is tested through retrieval.",
    },
    {
        "id": "coordinator_large_facility_request_missing_eligibility",
        "expected": "undetermined",
        "action": "draw_central_bank_facility",
        "facts": {
            "financials": {"capital": 250, "liquidity": 30, "borrowing_limit": 40,
                           "daily_withdrawals": 15, "forecast_next_7d": 150},
            "regulations": {"max_draw_facility": 120},
        },
        "trigger": "Liquidity stress persists after private funding offers were reduced.",
        "explanation": "No case-specific evidence establishes eligibility, collateral, solvency assessment or approval.",
    },
    {
        "id": "coordinator_interbank_request_with_unverified_terms",
        "expected": "undetermined",
        "action": "borrow_interbank",
        "facts": {
            "financials": {"capital": 220, "liquidity": 35, "borrowing_limit": 75,
                           "daily_withdrawals": 14, "forecast_next_7d": 140},
            "regulations": {"max_draw_facility": 60},
        },
        "trigger": "A market-wide liquidity shock has increased expected depositor withdrawals.",
        "explanation": "The proposed funding is within the simulation limit, but that limit is not a regulatory source and transaction details are absent.",
    },
    {
        "id": "coordinator_facility_request_under_uncertain_conditions",
        "expected": "undetermined",
        "action": "draw_central_bank_facility",
        "facts": {
            "financials": {"capital": 160, "liquidity": 18, "borrowing_limit": 25,
                           "daily_withdrawals": 11, "forecast_next_7d": 110},
            "regulations": {"max_draw_facility": 95},
        },
        "trigger": "A sharp deposit outflow is creating an immediate liquidity shortfall.",
        "explanation": "The scenario supports urgency but does not establish whether statutory or framework conditions for emergency assistance are met.",
    },
]


def _financial_analyst_runner(action):
    """Drive the actual FA tool loop; derive proposal amount from its tool result."""
    def respond(prompt):
        state = json.loads(prompt.split("FINANCIAL_REACT_STATE:\n", 1)[1])
        successful = [entry["observation"] for entry in state["history"]
                      if entry.get("observation", {}).get("ok")]
        tool_names = {item["tool"] for item in successful}
        if "get_bank_financials" not in tool_names:
            return json.dumps({"type": "tool_call", "tool": "get_bank_financials", "arguments": {}})
        if "build_financial_report" not in tool_names:
            return json.dumps({"type": "tool_call", "tool": "build_financial_report", "arguments": {}})

        report_observation = next(item for item in successful if item["tool"] == "build_financial_report")
        report = report_observation["result"]
        amount = report["suggested_funding_by_action"][action]
        recommendation = {"recommendation": action, "amount": amount,
                          "confidence": 0.65,
                          "rationale": ("Maintain the current position pending review; the host forecast shows a funding gap, and this proposal does not itself provide funding." if action == "hold" else "The seven-day cash forecast exceeds available liquidity; this proposed funding amount follows the host-calculated action bound and remains subject to risk and compliance review.")}
        claim = {"metric": "funding_gap", "value": report["funding_gap"],
                 "unit": "amount", "observation_id": report_observation["id"]}
        return json.dumps({"type": "final", "recommendation": recommendation, "claims": [claim]})
    return respond


def _paced_live_runner(client):
    def respond(prompt):
        global _last_model_call
        remaining = MIN_MODEL_CALL_INTERVAL_SECONDS - (time.monotonic() - _last_model_call)
        if _last_model_call and remaining > 0:
            time.sleep(remaining)
        response = client.complete(prompt)
        _last_model_call = time.monotonic()
        text = response.get("text", "")
        if not text.strip():
            raise RuntimeError("Model returned empty text; check provider output/reasoning token settings.")
        return text
    return respond


def _run_case(number, case, client):
    scenario = {
        "id": case["id"],
        "trigger": case["trigger"],
        "financials": case["facts"]["financials"],
        "regulations": case["facts"]["regulations"],
        # No external-news package in these fixtures, so the real verifier
        # reports unverified and the system continues to Financial Analyst.
        "news_sources": [],
    }
    print(f"\n{'=' * 88}\nCASE {number}/5: {case['id']}")
    print("Coordinator scenario supplied to the workflow:")
    print(json.dumps(scenario_inputs(scenario), indent=2, ensure_ascii=False))

    news = run_news_verification(scenario)
    print("\n1. News Verification output:")
    print(json.dumps(news, indent=2, ensure_ascii=False))
    news_label = news.get("report", {}).get("news_label", "unverified")
    if news_label == "false":
        print("Workflow gate: News Verification returned false; the real workflow skips Financial Analyst/Risk Manager and routes directly to Compliance.")
        # That branch supplies no upstream proposal. Exercise the documented
        # normal-agent action as a hold, which is what an empty proposal list
        # would otherwise leave Compliance unable to review.
        proposal = {"action": "hold", "amount": 0}
        fa = risk = None
    else:
        fa = run_financial_analyst(scenario, llm_runner=_financial_analyst_runner(case["action"]))
        print("\n2. Financial Analyst output (real tools/validation; scripted test driver):")
        print(json.dumps(fa, indent=2, ensure_ascii=False))
        if not fa.get("recommendation"):
            print("Workflow gate: Financial Analyst did not emit a validated recommendation; Compliance has no coordinator proposal for this case.")
            return {"evaluated": False, "reason": fa.get("reason", "No accepted recommendation")}
        liquidity_healthy = fa.get("metrics", {}).get("liquidity_healthy", True)
        if not liquidity_healthy:
            print("Workflow gate: liquidity_healthy is false; the real workflow skips Risk Manager and Compliance.")
            return {"evaluated": False, "reason": "Risk Manager/Compliance skipped by workflow gate"}
        risk = run_risk_manager(scenario, financial_report=fa)
        print("\n3. Risk Manager output:")
        print(json.dumps(risk, indent=2, ensure_ascii=False))
        risk_level = risk.get("report", {}).get("current_risk", {}).get("risk_level", "low")
        if risk_level != "high":
            print(f"Workflow gate: risk level is {risk_level}; the real workflow skips Compliance.")
            return {"evaluated": False, "reason": f"Risk level {risk_level} skips Compliance"}
        rec = fa["recommendation"]
        proposal = {"action": rec["recommendation"], "amount": rec["amount"]}

    # Mirror systems.py's Compliance call. It passes scenario inputs and only
    # the FA recommendation's action/amount as the proposed coordinator action.
    facts = scenario_inputs(scenario)
    compliance_input = {"scenario_facts": facts, "proposals": [proposal]}
    print("\n4. Exact input passed to Compliance (matches systems.py):")
    print(json.dumps(compliance_input, indent=2, ensure_ascii=False))
    result = run_compliance_officer(
        facts,
        llm_runner=_paced_live_runner(client),
        proposals=[proposal],
    )
    report = result["report"]
    finding = report["regulatory_findings"][0]
    budget = finding["budget"]
    complete = bool(finding.get("protocol_history")) and bool(budget["retrieval_calls"])
    within_budget = (budget["model_turns"] <= 3 and budget["retrieval_calls"] <= 3
                     and len(finding["evidence"]) <= budget["retrieval_calls"] * 5)
    matched = complete and within_budget and finding["finding"] == case["expected"]

    print("\n5. Compliance output:")
    print("Synthetic simulation check (separate from regulatory RAG finding):")
    print(json.dumps(report["synthetic_checks"], indent=2, ensure_ascii=False))
    print("Regulatory RAG finding:")
    print(json.dumps(finding, indent=2, ensure_ascii=False))
    print("\nPost-run evaluator only (not supplied to agents):")
    print(f"Expected: {case['expected']} — {case['explanation']}")
    print(f"Model finding: {finding['finding']}")
    print(f"Protocol/retrieval complete: {complete}; within configured budgets: {within_budget}")
    print("Outcome match: " + ("PASS" if matched else "REVIEW / MISMATCH"))
    return {"evaluated": True, "matched": matched, "finding": finding["finding"],
            "expected": case["expected"], "retrieval_calls": budget["retrieval_calls"]}


class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, value):
        for stream in self.streams:
            stream.write(value)
            stream.flush()
        return len(value)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def main():
    report_path = Path(__file__).resolve().parents[2] / "results" / "compliance_rag_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as report_file:
        with contextlib.redirect_stdout(_Tee(sys.stdout, report_file)):
            print("Compliance RAG workflow simulation (five coordinator-like cases)")
            print("Live model calls are made for Compliance only. Financial Analyst uses its real bounded tools and validation with a scripted test driver.")
            print("News Verification and Risk Manager use their real deterministic paths; no upstream live-model calls are consumed.")
            print("Each Compliance action is bounded to 3 model turns, 3 retrievals and 5 passages per retrieval.")
            print(f"Full report: {report_path}")
            client = LLMClient()
            results = []
            for number, case in enumerate(CASES, start=1):
                try:
                    results.append(_run_case(number, case, client))
                except Exception as exc:
                    print(f"\nCASE ERROR: {type(exc).__name__}: {exc}")
                    results.append({"evaluated": False, "reason": f"{type(exc).__name__}: {exc}"})
            evaluated = [item for item in results if item.get("evaluated")]
            passed = sum(bool(item.get("matched")) for item in evaluated)
            print(f"\nSummary: {passed}/{len(evaluated)} evaluated cases matched; {len(results) - len(evaluated)} skipped/failed.")
            print("Expected outcomes are evaluator metadata only. Review the displayed RAG evidence and citations; this harness does not authorize actions.")


if __name__ == "__main__":
    main()
