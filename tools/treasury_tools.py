"""In-memory simulated approval ledger. No bank APIs or real transactions.

approve() is a trusted application entry point, never an LLM-callable tool.
Approvals are bound to exact scenario inputs, action, and amount. They expire
when this process ends. Reusing an executed approval returns the same receipt.
"""
from copy import deepcopy
import hashlib
import json
import threading
from uuid import uuid4
from tools.compliance_tools import check_compliance


def _scenario_key(scenario):
    inputs = {key: scenario.get(key) for key in ("id", "trigger", "financials", "regulations")}
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, allow_nan=False).encode()).hexdigest()


class TreasurySimulation:
    def __init__(self, authorized_approvers=("human_reviewer", "crisis_coordinator")):
        self._authorized_approvers = frozenset(authorized_approvers)
        self._approvals = {}
        self._receipts = {}
        self._used = {}
        self._lock = threading.RLock()

    def _check_remaining(self, scenario, proposal):
        current = deepcopy(scenario)
        used = self._used.get(_scenario_key(scenario), {})
        current["financials"]["borrowing_limit"] -= used.get("borrow_interbank", 0)
        if "max_draw_facility" in current.get("regulations", {}):
            current["regulations"]["max_draw_facility"] -= used.get("draw_central_bank_facility", 0)
        check = check_compliance(current, proposal)
        if not check["compliant"]:
            raise PermissionError("Simulation blocked: " + "; ".join(check["violations"]))

    def approve(self, scenario, proposal, *, approved_by):
        """Called only by trusted host code after authenticating the approver.

        approved_by is an audit identity, not authentication. The host must not
        accept an identity or this method call from model output or untrusted HTTP.
        """
        if approved_by not in self._authorized_approvers:
            raise PermissionError("Unknown simulation approver")
        with self._lock:
            self._check_remaining(scenario, proposal)
            approval_id = str(uuid4())
            self._approvals[approval_id] = {
                "scenario_key": _scenario_key(scenario), "proposal": deepcopy(proposal),
                "approved_by": approved_by
            }
            return approval_id

    def execute(self, scenario, proposal, approval_id):
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                raise PermissionError("No recognized approval; simulation remains blocked")
            if approval["scenario_key"] != _scenario_key(scenario) or approval["proposal"] != proposal:
                raise PermissionError("Approval does not match this scenario, action, and amount")
            if approval_id in self._receipts:
                return deepcopy(self._receipts[approval_id])
            self._check_remaining(scenario, proposal)
            key = _scenario_key(scenario)
            used = self._used.setdefault(key, {})
            action = proposal["action"]
            used[action] = used.get(action, 0) + proposal["amount"]
            receipt = {"transaction_id": str(uuid4()), "approval_id": approval_id,
                       "action": action, "amount": proposal["amount"],
                       "approved_by": approval["approved_by"], "simulated": True,
                       "status": "simulated_executed",
                       "requires_regulator_report": scenario.get("regulations", {}).get("report_to_regulator") is True,
                       "regulator_report_sent": False}
            self._receipts[approval_id] = receipt
            return deepcopy(receipt)


def draw_central_bank_facility(book, scenario, amount, approval_id):
    return book.execute(scenario, {"action": "draw_central_bank_facility", "amount": amount}, approval_id)


def request_interbank_borrowing(book, scenario, amount, approval_id):
    return book.execute(scenario, {"action": "borrow_interbank", "amount": amount}, approval_id)
