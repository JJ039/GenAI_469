"""Checks synthetic scenario constraints, not real banking law."""
from math import isfinite
from tools.financial_tools import get_bank_financials

ACTIONS = ("hold", "borrow_interbank", "draw_central_bank_facility")


def retrieve_regulations(scenario):
    regulations = scenario.get("regulations", {})
    if not isinstance(regulations, dict):
        raise ValueError("regulations must be an object")
    out = dict(regulations)
    if "max_draw_facility" in out:
        limit = out["max_draw_facility"]
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not isfinite(limit) or limit < 0:
            raise ValueError("Invalid max_draw_facility")
    return out


def check_compliance(scenario, proposal):
    financials = get_bank_financials(scenario)
    rules = retrieve_regulations(scenario)
    violations = []
    action, amount = proposal.get("action"), proposal.get("amount")
    if action not in ACTIONS:
        violations.append("Unknown action")
    valid_amount = not isinstance(amount, bool) and isinstance(amount, (int, float)) and isfinite(amount) and amount >= 0
    if not valid_amount:
        violations.append("Amount must be a finite nonnegative number")
    elif action == "hold" and amount != 0:
        violations.append("Hold requires zero amount")
    elif action == "borrow_interbank" and amount > financials["borrowing_limit"]:
        violations.append("Interbank borrowing limit exceeded")
    elif action == "draw_central_bank_facility":
        if "max_draw_facility" not in rules:
            violations.append("Facility limit missing; manual review required")
        elif amount > rules["max_draw_facility"]:
            violations.append("Central bank facility limit exceeded")
    return {"compliant": not violations, "violations": violations,
            "authorization_granted": False,
            "requires_regulator_report": rules.get("report_to_regulator") is True,
            "scope": "Configured simulation funding limits only; not a complete regulatory assessment",
            "unmodelled_fields": [key for key in rules if key not in ("max_draw_facility", "report_to_regulator")]}
