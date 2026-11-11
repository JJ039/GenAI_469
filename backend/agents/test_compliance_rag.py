"""Five live, standalone Compliance RAG cases with explicit ground truth.

Run this module from the repository root; the exact command is in the agents README.

Uses the configured LLM, local Qwen model and Qdrant collection. It does not run
the coordinator or any other agent. Findings are model outputs, so this script
prints mismatches for review instead of hiding them behind an assertion.
"""
import json

from backend.agents.compliance_officer import run_compliance_officer
from backend.llm_client import LLMClient


GROUND_TRUTH_SOURCE = {
    "title": "MAS Notice 649 Minimum Liquid Assets and Liquidity Coverage Ratio",
    "url": "https://www.mas.gov.sg/-/media/mas-media-library/regulation/notices/ppd/notice-649/mas-notice-649-effective-01-september-2026.pdf",
    "effective_date": "2026-09-01",
    "provisions": "Part I, paragraphs 13 and 15: 16% minimum Liquid Assets and 8% minimum Tier-1 Liquid Assets against the applicable Qualifying Liabilities.",
}


COMMON_SCOPE = (
    "For this test, assess only whether the stated position meets the applicable "
    "Part I MLA percentage requirements in MAS Notice 649 paragraphs 13 and 15. "
    "Do not infer overall legal compliance beyond this narrow scope."
)


def _facts(all_currency, singapore_dollar):
    return {
        "bank_status": "Singapore Reporting Bank, not subject to Part II LCR, and elected Part I MLA with prior written notice to MAS.",
        "test_scope": COMMON_SCOPE,
        "all_currency_position": all_currency,
        "singapore_dollar_position": singapore_dollar,
    }


CASES = [
    {
        "id": "mla_compliant_above_thresholds",
        "expected": "compliant",
        "facts": _facts(
            {"qualifying_liabilities": 1000, "liquid_assets": 200, "tier1_liquid_assets": 100},
            {"qualifying_liabilities": 800, "liquid_assets": 160, "tier1_liquid_assets": 80},
        ),
        "explanation": "20% MLA and 10% Tier-1 in both liability bases exceed the 16% and 8% floors.",
    },
    {
        "id": "mla_compliant_at_exact_thresholds",
        "expected": "compliant",
        "facts": _facts(
            {"qualifying_liabilities": 1000, "liquid_assets": 160, "tier1_liquid_assets": 80},
            {"qualifying_liabilities": 800, "liquid_assets": 128, "tier1_liquid_assets": 64},
        ),
        "explanation": "Exactly 16% MLA and 8% Tier-1 in both liability bases meets the stated minimums.",
    },
    {
        "id": "mla_noncompliant_all_currency_below_16_percent",
        "expected": "non_compliant",
        "facts": _facts(
            {"qualifying_liabilities": 1000, "liquid_assets": 150, "tier1_liquid_assets": 80},
            {"qualifying_liabilities": 800, "liquid_assets": 128, "tier1_liquid_assets": 64},
        ),
        "explanation": "All-currency MLA is 15%, below the 16% minimum; other ratios meet their floors.",
    },
    {
        "id": "mla_noncompliant_sgd_tier1_below_8_percent",
        "expected": "non_compliant",
        "facts": _facts(
            {"qualifying_liabilities": 1000, "liquid_assets": 200, "tier1_liquid_assets": 100},
            {"qualifying_liabilities": 800, "liquid_assets": 160, "tier1_liquid_assets": 56},
        ),
        "explanation": "Singapore-dollar Tier-1 liquid assets are 7%, below the 8% minimum.",
    },
    {
        "id": "mla_undetermined_missing_framework_and_currency_breakdown",
        "expected": "undetermined",
        "facts": {
            "test_scope": COMMON_SCOPE,
            "bank_status": "Singapore bank; whether it is subject to Part II LCR or has elected Part I MLA is not provided.",
            "reported_liquid_assets": 200,
            "reported_liabilities": 1000,
            "missing_facts": [
                "whether Part I MLA applies to this bank",
                "all-currency and Singapore-dollar Qualifying Liabilities",
                "Liquid Assets and Tier-1 Liquid Assets for each required basis",
            ],
        },
        "explanation": "The legal framework and required currency-specific denominators and asset tiers are missing.",
    },
]


def _scenario(case_id):
    # The deterministic check passes in every case; the legal test facts are
    # supplied separately so the RAG finding can be inspected on its own.
    return {
        "id": case_id,
        "financials": {
            "capital": 1000,
            "liquidity": 100,
            "borrowing_limit": 100,
            "daily_withdrawals": 10,
        },
        "regulations": {},
    }


def main():
    client = LLMClient()
    runner = lambda prompt: client.complete(prompt)["text"]
    passed = 0

    print("Compliance-only live RAG evaluation (five cases)")
    print("Ground truth: " + GROUND_TRUTH_SOURCE["title"])
    print("Expected rule: " + GROUND_TRUTH_SOURCE["provisions"])
    print("Each run can use up to 3 model turns and 3 retrieval calls.")

    for number, case in enumerate(CASES, start=1):
        proposal = {
            "action": "hold",
            "amount": 0,
            "description": "Maintain the current liquid asset position described in scenario_facts; evaluate only the stated MAS Notice 649 Part I MLA test scope.",
        }
        result = run_compliance_officer(
            _scenario(case["id"]),
            llm_runner=runner,
            proposals=[proposal],
            scenario_facts=case["facts"],
        )
        report = result["report"]
        finding = report["regulatory_findings"][0]
        budget = finding["budget"]
        retrieval_limit_ok = (
            budget["retrieval_calls"] <= 3
            and len(finding["evidence"]) <= budget["retrieval_calls"] * 5
        )
        matched = finding["finding"] == case["expected"] and retrieval_limit_ok
        passed += int(matched)

        print(f"\n{'=' * 76}\nCASE {number}/5: {case['id']}")
        print("Ground truth: " + case["expected"] + " — " + case["explanation"])
        print("Synthetic simulation check: " + json.dumps(report["synthetic_checks"][0], ensure_ascii=False))
        print("RAG determination: " + finding["finding"])
        print("Rationale: " + finding["rationale"])
        print("Missing facts: " + json.dumps(finding["missing_facts"], ensure_ascii=False))
        print("Budget: " + json.dumps(budget))
        print("Expected match: " + ("PASS" if matched else "REVIEW / MISMATCH"))
        print("Citations:")
        print(json.dumps(finding["citations"], indent=2, ensure_ascii=False))
        print("Retrieved RAG passages:")
        print(json.dumps(finding["evidence"], indent=2, ensure_ascii=False))

    print(f"\nSummary: {passed}/5 matched expected outcomes and retrieval limits.")
    print("Review every mismatch, passage and citation; model findings are not legal advice or authorization.")


if __name__ == "__main__":
    main()
