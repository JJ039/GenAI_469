"""Checks synthetic scenario constraints, not real banking law."""
from math import isfinite
from tools.financial_tools import get_bank_financials

ACTIONS = ("hold", "borrow_interbank", "draw_central_bank_facility")


def retrieve_regulations(scenario):
    regulations = scenario.get("regulations", {})
    if not isinstance(regulations, dict):
        raise ValueError("regulations must be an object")
    out = dict(regulations)
    allowed = out.get('allowed_actions')
    if allowed is not None and (not isinstance(allowed,list) or any(a not in ACTIONS for a in allowed)):
        raise ValueError('allowed_actions must be a list of known actions')
    if 'report_to_regulator' in out and not isinstance(out['report_to_regulator'], bool):
        raise ValueError('report_to_regulator must be boolean')
    if "max_draw_facility" in out:
        limit = out["max_draw_facility"]
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not isfinite(limit) or limit < 0:
            raise ValueError("Invalid max_draw_facility")
    return out


def check_compliance(scenario, proposal):
    rules = retrieve_regulations(scenario)
    violations = []
    try:
        financials = get_bank_financials(scenario)
    except (KeyError, TypeError, ValueError):
        financials = None
        if proposal.get('action') != 'hold':
            violations.append('Required financial data missing or invalid')
    action, amount = proposal.get("action"), proposal.get("amount")
    if action not in ACTIONS:
        violations.append("Unknown action")
    valid_amount = not isinstance(amount, bool) and isinstance(amount, (int, float)) and isfinite(amount) and amount >= 0
    if not valid_amount:
        violations.append("Amount must be a finite nonnegative number")
    elif action == "hold" and amount != 0:
        violations.append("Hold requires zero amount")
    elif action == "borrow_interbank" and financials is not None and amount > financials["borrowing_limit"]:
        violations.append("Interbank borrowing limit exceeded")
    elif action == "draw_central_bank_facility":
        if "max_draw_facility" not in rules:
            violations.append("Facility limit missing; manual review required")
        elif amount > rules["max_draw_facility"]:
            violations.append("Central bank facility limit exceeded")
    allowed = rules.get('allowed_actions')
    if allowed is not None and action not in allowed:
        violations.append('Action not permitted by scenario policy')
    return {"compliant": not violations, "violations": violations,
            "authorization_granted": False,
            "requires_regulator_report": rules.get("report_to_regulator") is True,
            "scope": "Configured simulation funding limits only; not a complete regulatory assessment",
            "unmodelled_fields": [key for key in rules if key not in ("max_draw_facility", "report_to_regulator", "allowed_actions")]}


# Instrument actual tool invocations, including nested deterministic calculations.
from backend.telemetry import tracked_tool
for _name, _value in list(globals().items()):
    if callable(_value) and getattr(_value, '__module__', None) == __name__ and not _name.startswith('_') and not isinstance(_value, type):
        globals()[_name] = tracked_tool(_value)
