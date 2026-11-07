"""Transparent risk proxies and cash-only simulations, not calibrated probabilities."""
from tools.financial_tools import build_financial_report, get_bank_financials
from tools.compliance_tools import check_compliance
from math import isfinite


def candidate_actions(scenario):
    amount = build_financial_report(scenario)["suggested_funding_amount"]
    return [{"action": "hold", "amount": 0},
            {"action": "borrow_interbank", "amount": amount},
            {"action": "draw_central_bank_facility", "amount": amount}]


def calculate_risk_score(scenario, additional_liquidity=0):
    if isinstance(additional_liquidity, bool) or not isinstance(additional_liquidity, (int, float)) or not isfinite(additional_liquidity) or additional_liquidity < 0:
        raise ValueError("Additional liquidity must be a finite nonnegative number")
    report = build_financial_report(scenario)
    liquidity = get_bank_financials(scenario)["liquidity"] + additional_liquidity
    outflow = report["forecast_7d_outflow"]
    gap = max(0.0, outflow - liquidity)
    score = 0.0 if outflow == 0 else min(100.0, 100 * gap / outflow)
    return {"risk_score": round(score, 2), "remaining_funding_gap": gap,
            "risk_level": "high" if score >= 50 else "medium" if score > 0 else "low",
            "meaning": "Percentage of forecast seven-day outflow left unfunded; not a default probability"}


def simulate_action_outcome(scenario, proposal):
    compliance = check_compliance(scenario, proposal)
    if not compliance["compliant"]:
        return {"proposal": proposal, "feasible": False, "compliance": compliance}
    amount = proposal["amount"] if proposal["action"] != "hold" else 0
    return {"proposal": proposal, "feasible": True, "compliance": compliance,
            "projected_liquidity": get_bank_financials(scenario)["liquidity"] + amount,
            "risk": calculate_risk_score(scenario, amount),
            "assumptions": ["Funding succeeds immediately", "No interest, contagion or asset sales modelled"]}
