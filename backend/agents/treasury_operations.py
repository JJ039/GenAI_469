"""Deterministic execution agent; an LLM never grants its own approval."""


def run_treasury_operations(scenario, llm_runner=None, *, book=None, proposal=None, approval_id=None):
    if book is None or proposal is None or approval_id is None:
        return {"agent": "treasury_operations", "status": "awaiting_authorization",
                "simulated": True, "executed": False,
                "reason": "An explicit proposal and host-issued approval are required. No host approval was supplied."}
    receipt = book.execute(scenario, proposal, approval_id)
    return {"agent": "treasury_operations", "status": "completed", "simulated": True,
            "executed": True, "receipt": receipt}
