"""Transparent risk proxies and cash-only simulations, not calibrated probabilities."""
from tools.financial_tools import build_financial_report, get_bank_financials
from tools.compliance_tools import check_compliance
from copy import deepcopy
from math import isfinite


def candidate_actions(scenario):
    suggested = build_financial_report(scenario)['suggested_funding_by_action']
    return [{'action': action, 'amount': amount} for action, amount in suggested.items()]


def calculate_risk_score(scenario, additional_liquidity=0):
    if isinstance(additional_liquidity, bool) or not isinstance(additional_liquidity, (int, float)) or not isfinite(additional_liquidity) or additional_liquidity < 0:
        raise ValueError("Additional liquidity must be a finite nonnegative number")
    report = build_financial_report(scenario)
    liquidity = get_bank_financials(scenario)["liquidity"] + additional_liquidity
    outflow = report["forecast_7d_outflow"]
    gap = max(0.0, outflow - liquidity)
    score = 0.0 if outflow == 0 else min(100.0, 100 * gap / outflow)
    coverage = None if outflow == 0 else round(min(1.0, liquidity / outflow), 4)
    return {"risk_score": round(score, 2), "remaining_funding_gap": gap,
            "cash_coverage_proxy": coverage,
            "risk_level": "high" if score >= 50 else "medium" if score > 0 else "low",
            "meaning": "Percentage of forecast seven-day outflow left unfunded; not a default probability",
            "cash_coverage_meaning": "Liquidity divided by forecast seven-day outflow (capped at 1.0); a cash-coverage proxy, not a regulatory ratio"}


def simulate_action_outcome(scenario, proposal):
    compliance = check_compliance(scenario, proposal)
    if not compliance["compliant"]:
        return {"proposal": proposal, "feasible": False, "compliance": compliance}
    amount = proposal["amount"] if proposal["action"] != "hold" else 0
    return {"proposal": proposal, "feasible": True, "compliance": compliance,
            "projected_liquidity": get_bank_financials(scenario)["liquidity"] + amount,
            "risk": calculate_risk_score(scenario, amount),
            "assumptions": ["Funding succeeds immediately", "No interest, contagion or asset sales modelled"]}


def compare_action_outcomes(scenario, financial_recommendation=None):
    """Assess risk and compare the possible action outcomes in one host-bound call.

    Simulates every candidate action, ranks them by projected risk score (lowest
    first), and, when the coordinator forwards the Financial Analyst's
    recommendation, marks and simulates it so the financial analysis is an
    explicit input to the comparison. Model-supplied figures are never accepted;
    proposals come only from the host candidate set plus the forwarded
    recommendation.
    """
    current = calculate_risk_score(scenario)
    proposals = candidate_actions(scenario)
    recommended = None
    if financial_recommendation is not None:
        if not isinstance(financial_recommendation, dict) or set(financial_recommendation) != {"action", "amount"}:
            raise ValueError("financial_recommendation must contain exactly action and amount")
        action = financial_recommendation["action"]
        amount = financial_recommendation["amount"]
        if action not in ("hold", "borrow_interbank", "draw_central_bank_facility"):
            raise ValueError("Unknown recommended action")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not isfinite(amount) or amount < 0:
            raise ValueError("Recommended amount must be a finite nonnegative number")
        recommended = {"action": action, "amount": amount}
        if not any(p["action"] == action and p["amount"] == amount for p in proposals):
            proposals = proposals + [recommended]
    outcomes = []
    for proposal in proposals:
        outcome = simulate_action_outcome(scenario, proposal)
        outcome["is_financial_recommendation"] = (
            recommended is not None
            and proposal["action"] == recommended["action"]
            and proposal["amount"] == recommended["amount"])
        outcomes.append(outcome)
    # Rank feasible outcomes by resulting risk (lowest risk first); infeasible last.
    def sort_key(outcome):
        feasible = outcome.get("feasible")
        score = outcome.get("risk", {}).get("risk_score")
        return (0 if feasible else 1, score if isinstance(score, (int, float)) else float("inf"))
    ranked = sorted(outcomes, key=sort_key)
    best = next((o for o in ranked if o.get("feasible")), None)
    return {
        "current_risk": current,
        "financial_recommendation": recommended,
        "ranked_outcomes": ranked,
        "lowest_risk_feasible_action": best["proposal"] if best else None,
        "limitation": "Cash-only simulations; risk scores are unfunded-outflow proxies, not default probabilities.",
    }


# Instrument actual tool invocations, including nested deterministic calculations.
from backend.telemetry import tracked_tool
for _name, _value in list(globals().items()):
    if callable(_value) and getattr(_value, '__module__', None) == __name__ and not _name.startswith('_') and not isinstance(_value, type):
        globals()[_name] = tracked_tool(_value)


TOOL_CATALOG = [
    {'name': 'calculate_risk_score', 'arguments': {},
     'description': 'Assess the current risk proxy: percentage of forecast seven-day outflow left unfunded, remaining funding gap and risk_level (low/medium/high). Not a default probability.'},
    {'name': 'candidate_actions', 'arguments': {},
     'description': 'List the action/amount proposals (hold, borrow_interbank, draw_central_bank_facility) with host-suggested funding amounts available to compare.'},
    {'name': 'compare_action_outcomes', 'arguments': {},
     'description': 'Assess risk and compare every possible action outcome in one call: feasibility, compliance, projected liquidity and resulting risk, ranked lowest-risk first. Uses the coordinator-forwarded financial analysis recommendation as an input. Required before final.'},
    {'name': 'simulate_action_outcome', 'arguments': {'action': 'required: hold|borrow_interbank|draw_central_bank_facility', 'amount': 'required finite nonnegative number; 0 for hold'},
     'description': 'Optionally simulate one specific action/amount proposal in isolation: feasibility, compliance, projected liquidity and resulting risk score.'},
]


def execute_risk_tool(name, arguments, scenario, financial_recommendation=None):
    """No arbitrary dispatch, execution, input replacement, or model-supplied financials."""
    if not isinstance(name, str) or name not in {tool['name'] for tool in TOOL_CATALOG}:
        raise ValueError('Unknown or disallowed risk tool')
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object')
    scenario = deepcopy(scenario)
    if name == 'calculate_risk_score':
        if arguments:
            raise ValueError('calculate_risk_score takes no arguments; financials are host-bound')
        return calculate_risk_score(scenario)
    if name == 'candidate_actions':
        if arguments:
            raise ValueError('candidate_actions takes no arguments; proposals are host-bound')
        return {'candidate_actions': candidate_actions(scenario)}
    if name == 'compare_action_outcomes':
        if arguments:
            raise ValueError('compare_action_outcomes takes no arguments; the financial analysis input is host-bound')
        return compare_action_outcomes(scenario, financial_recommendation)
    if name == 'simulate_action_outcome':
        if set(arguments) != {'action', 'amount'}:
            raise ValueError('simulate_action_outcome requires exactly action and amount')
        action, amount = arguments['action'], arguments['amount']
        if action not in ('hold', 'borrow_interbank', 'draw_central_bank_facility'):
            raise ValueError('Unknown action')
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not isfinite(amount) or amount < 0:
            raise ValueError('amount must be a finite nonnegative number')
        return simulate_action_outcome(scenario, {'action': action, 'amount': amount})
    raise ValueError('Unsupported risk tool')
