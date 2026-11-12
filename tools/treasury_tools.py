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
from tools.compliance_tools import check_compliance, retrieve_regulations
from tools.financial_tools import get_bank_financials, forecast_cash_outflow


def _scenario_key(scenario):
    inputs = {key: scenario.get(key) for key in ("id", "trigger", "financials", "regulations", "news_sources")}
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, allow_nan=False).encode()).hexdigest()


class TreasurySimulation:
    def __init__(self, authorized_approvers=("human_reviewer",)):
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
                       "regulator_report_sent": False,
                       "simulated_regulator_report_filed": scenario.get("regulations", {}).get("report_to_regulator") is True}
            self._receipts[approval_id] = receipt
            return deepcopy(receipt)


def draw_central_bank_facility(book, scenario, amount, approval_id):
    return book.execute(scenario, {"action": "draw_central_bank_facility", "amount": amount}, approval_id)


def request_interbank_borrowing(book, scenario, amount, approval_id):
    return book.execute(scenario, {"action": "borrow_interbank", "amount": amount}, approval_id)


def inspect_funding_effect(scenario, proposal):
    if proposal is None:
        return {'proposal': None, 'available': False, 'reason': 'Host candidate is missing'}
    check = check_compliance(scenario, proposal)
    if not check['compliant']:
        return {'proposal': proposal, 'available': False, 'compliance': check,
                'reason': 'Noncompliant candidates are not simulated'}
    data = get_bank_financials(scenario)
    outflow = forecast_cash_outflow(data)
    added = 0 if proposal['action'] == 'hold' else proposal['amount']
    liquidity = data['liquidity'] + added
    return {'proposal': proposal, 'available': True, 'projected_liquidity': liquidity,
            'forecast_7d_outflow': outflow, 'remaining_funding_gap': max(0, outflow-liquidity),
            'hypothetical': True, 'executed': False,
            'assumption': 'Candidate funding arrives immediately; no fees, inflows or market effects. Ledger remaining capacity is rechecked only at execution.'}

def inspect_reporting_requirements(scenario):
    rules = retrieve_regulations(scenario)
    required = rules.get('report_to_regulator') is True
    return {'requires_regulator_report': required, 'regulator_report_sent': False,
            'draft_fields': ['scenario_id', 'action', 'amount', 'approval_id', 'transaction_id'] if required else [],
            'limitation': 'Simulation flag only. No actual filing, recipient or statutory deadline is defined.'}

def inspect_execution_requirements(scenario, proposal):
    check = check_compliance(scenario, proposal) if proposal is not None else None
    blockers = []
    if proposal is None:
        blockers.append('Host candidate is missing')
    elif not check['compliant']:
        blockers.extend(check['violations'])
    blockers.extend(['Final team strategy has not been established by this tool',
                     'Host must supply and validate exact bound approval through the ledger'])
    return {'proposal': proposal, 'compliance': check, 'blockers': blockers,
            'execution_authorized': False, 'ledger_approval_checked': False,
            'execution_guards': ['Exact scenario/action/amount binding', 'Remaining cumulative funding limits',
                                 'Idempotent receipt on repeated approval'],
            'limitation': 'Read-only checklist; does not inspect private ledger state or grant approval.'}


# Instrument actual tool invocations, including nested deterministic calculations.
from backend.telemetry import tracked_tool
for _name, _value in list(globals().items()):
    if callable(_value) and getattr(_value, '__module__', None) == __name__ and not _name.startswith('_') and not isinstance(_value, type):
        globals()[_name] = tracked_tool(_value)
TreasurySimulation.approve = tracked_tool(TreasurySimulation.approve)
TreasurySimulation.execute = tracked_tool(TreasurySimulation.execute)


def inspect_proposal(proposal):
    return {"proposal": deepcopy(proposal), "execution_authorized": False}


def prepare_execution_plan(scenario, proposal):
    check = check_compliance(scenario, proposal) if proposal is not None else None
    return {'proposal': proposal, 'compliance': check,
            'ready_for_host_review': bool(check and check['compliant']),
            'execution_authorized': False,
            'missing_requirements': (['combined_proposal'] if proposal is None else []) + ['host_issued_bound_approval'],
            'execution_steps': ['Obtain explicit host approval bound to exact scenario, action and amount',
                                'Host invokes ledger execution; ledger rechecks binding and remaining limits',
                                'Return idempotent simulated receipt; surface reporting requirement'],
            'regulator_report_sent': False}
TOOL_CATALOG = [
    {'name': 'inspect_proposal', 'arguments': {}, 'description': 'Read host-supplied proposal. Missing means no strategy has been selected; never invent one.'},
    {'name': 'retrieve_regulations', 'arguments': {}, 'description': 'Read configured simulation limits and reporting requirements.'},
    {'name': 'prepare_execution_plan', 'arguments': {}, 'description': 'Check host proposal compliance and identify missing approval requirements; cannot authorize or execute. Required before final.'},
    {'name': 'inspect_funding_effect', 'arguments': {}, 'description': 'Project liquidity and remaining seven-day gap for the host candidate; reject noncompliant candidates. Hypothetical only.'},
    {'name': 'inspect_reporting_requirements', 'arguments': {}, 'description': 'Read simulation reporting flag and draft receipt fields. Does not send a report or invent deadlines.'},
    {'name': 'inspect_execution_requirements', 'arguments': {}, 'description': 'List proposal/compliance blockers and required ledger checks. Cannot check private approval state, authorize or execute.'},
]
def execute_treasury_tool(name, arguments, scenario, proposal=None):
    if not isinstance(name, str) or name not in {t["name"] for t in TOOL_CATALOG}:
        raise ValueError("Unknown or disallowed treasury tool")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    if arguments:
        raise ValueError('Treasury preparation tools take no arguments; proposal is host-bound')
    if name == 'inspect_proposal':
        return inspect_proposal(proposal)
    if name == 'retrieve_regulations':
        return retrieve_regulations(scenario)
    if name == 'inspect_funding_effect':
        return inspect_funding_effect(scenario, proposal)
    if name == 'inspect_reporting_requirements':
        return inspect_reporting_requirements(scenario)
    if name == 'inspect_execution_requirements':
        return inspect_execution_requirements(scenario, proposal)
    return prepare_execution_plan(scenario, proposal)
