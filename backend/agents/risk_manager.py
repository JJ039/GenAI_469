from tools.risk_tools import calculate_risk_score, candidate_actions, simulate_action_outcome
from backend.agents.specialist_common import interpret_report


def run_risk_manager(scenario, llm_runner=None, financial_report=None):
    report = {"current_risk": calculate_risk_score(scenario),
              "candidate_outcomes": [simulate_action_outcome(scenario, p) for p in candidate_actions(scenario)]}
    if financial_report:
        # Rejected candidate text and unverified claims are for audit only, never evidence.
        report['financial_analyst_report'] = {key: financial_report[key] for key in
            ('agent','status','metrics','recommendation','reason') if key in financial_report}
        recommendation = financial_report.get('recommendation')
        if recommendation:
            report['financial_recommendation_outcome'] = simulate_action_outcome(scenario, {
                'action': recommendation['recommendation'], 'amount': recommendation['amount']})
    return {"agent": "risk_manager", "status": "completed", "report": report,
            "interpretation": interpret_report("Risk Manager", report, scenario, llm_runner)}
