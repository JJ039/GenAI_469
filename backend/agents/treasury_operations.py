"""Agentic read-only preparation plus deterministic, host-approved execution."""
from copy import deepcopy
from backend.agents.agent_loop import run_tool_loop, require_observed_tools
from tools.compliance_tools import check_compliance, retrieve_regulations


def run_treasury_operations(scenario, llm_runner=None, *, book=None, proposal=None, approval_id=None,
                            max_steps=6, max_tool_calls=4):
    if book is None or proposal is None or approval_id is None:
        result = {"agent": "treasury_operations", "status": "awaiting_authorization",
                "simulated": True, "executed": False,
                "reason": "An explicit proposal and host-issued approval are required. No host approval was supplied."}
        if llm_runner is None:
            return result
        inputs, bound_proposal = deepcopy(scenario), deepcopy(proposal)
        def readiness():
            check = check_compliance(inputs, bound_proposal) if bound_proposal is not None else None
            return {'proposal': bound_proposal, 'compliance': check,
                    'ready_for_host_review': bool(check and check['compliant']),
                    'execution_authorized': False,
                    'missing_requirements': (['combined_proposal'] if bound_proposal is None else []) + ['host_issued_bound_approval'],
                    'execution_steps': ['Obtain explicit host approval bound to exact scenario, action and amount',
                                        'Host invokes ledger execution; ledger rechecks binding and remaining limits',
                                        'Return idempotent simulated receipt; surface reporting requirement'],
                    'regulator_report_sent': False}
        catalog = [
            {'name': 'inspect_proposal', 'arguments': {}, 'description': 'Read host-supplied proposal. Missing means no strategy has been selected; never invent one.'},
            {'name': 'retrieve_regulations', 'arguments': {}, 'description': 'Read configured simulation limits and reporting requirements.'},
            {'name': 'prepare_execution_plan', 'arguments': {}, 'description': 'Check host proposal compliance and identify missing approval requirements; cannot authorize or execute. Required before final.'},
        ]
        def dispatch(name, arguments):
            if arguments:
                raise ValueError('Treasury preparation tools take no arguments; proposal is host-bound')
            if name == 'inspect_proposal':
                return {'proposal': bound_proposal, 'execution_authorized': False}
            if name == 'retrieve_regulations':
                return retrieve_regulations(inputs)
            return readiness()
        loop = run_tool_loop('Treasury Operations Agent', llm_runner, catalog, dispatch,
                             lambda f, o: require_observed_tools(f, o, ['prepare_execution_plan']),
                             context={'required_tools': ['prepare_execution_plan'],
                                      'limitations': 'Preparation only. A supplied proposal may be a Financial Analyst candidate, not a selected team strategy. Remain awaiting_authorization. Never select a combined strategy, grant approval, or claim execution.'},
                             max_steps=max_steps, max_tool_calls=max_tool_calls)
        final = loop.pop('final')
        # The plan is host-derived, never an executable model proposal.
        result.update(execution_plan=readiness(), interpretation=final,
                      preparation_status='completed' if final else 'needs_review', **loop)
        return result
    receipt = book.execute(scenario, proposal, approval_id)
    return {"agent": "treasury_operations", "status": "completed", "simulated": True,
            "executed": True, "receipt": receipt}
