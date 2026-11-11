"""Agentic read-only preparation plus deterministic, host-approved execution."""
from copy import deepcopy
from backend.agents.agent_loop import run_tool_loop, require_observed_tools
from tools.treasury_tools import TOOL_CATALOG, execute_treasury_tool, prepare_execution_plan


def run_treasury_operations(scenario, llm_runner=None, *, book=None, proposal=None, approval_id=None,
                            max_steps=6, max_tool_calls=4):
    if book is None or proposal is None or approval_id is None:
        result = {"agent": "treasury_operations", "status": "awaiting_authorization",
                "simulated": True, "executed": False,
                "reason": "An explicit proposal and host-issued approval are required. No host approval was supplied."}
        if llm_runner is None:
            return result
        inputs, bound_proposal = deepcopy(scenario), deepcopy(proposal)
        loop = run_tool_loop('Treasury Operations Agent', llm_runner, TOOL_CATALOG,
                             lambda name, args: execute_treasury_tool(name, args, inputs, bound_proposal),
                             lambda f, o: require_observed_tools(f, o, ['prepare_execution_plan']),
                             context={'required_tools': ['prepare_execution_plan'],
                                      'limitations': 'Preparation only. A supplied proposal may be a Financial Analyst candidate, not a selected team strategy. Remain awaiting_authorization. Never select a combined strategy, grant approval, or claim execution.'},
                             max_steps=max_steps, max_tool_calls=max_tool_calls)
        final = loop.pop('final')
        # The plan is host-derived, never an executable model proposal.
        result.update(execution_plan=prepare_execution_plan(inputs, bound_proposal), interpretation=final,
                      preparation_status='completed' if final else 'needs_review', **loop)
        return result
    receipt = book.execute(scenario, proposal, approval_id)
    return {"agent": "treasury_operations", "status": "completed", "simulated": True,
            "executed": True, "receipt": receipt}
