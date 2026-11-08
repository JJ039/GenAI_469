from tools.risk_tools import calculate_risk_score, candidate_actions, simulate_action_outcome
from backend.agents.specialist_common import interpret_report


def run_risk_manager(scenario, llm_runner=None):
    report = {"current_risk": calculate_risk_score(scenario),
              "candidate_outcomes": [simulate_action_outcome(scenario, p) for p in candidate_actions(scenario)]}
    return {"agent": "risk_manager", "status": "completed", "report": report,
            "interpretation": interpret_report("Risk Manager", report, scenario, llm_runner)}
