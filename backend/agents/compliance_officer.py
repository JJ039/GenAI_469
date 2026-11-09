from tools.compliance_tools import retrieve_regulations, check_compliance
from tools.risk_tools import candidate_actions
from backend.agents.specialist_common import interpret_report


def run_compliance_officer(scenario, llm_runner=None, proposals=None):
    report = {"regulations": retrieve_regulations(scenario),
              "checks": [{"proposal": p, **check_compliance(scenario, p)}
                         for p in (candidate_actions(scenario) if proposals is None else proposals)],
              "authorization_granted": False}
    return {"agent": "compliance_officer", "status": "completed", "report": report,
            "interpretation": interpret_report("Compliance Officer", report, scenario, llm_runner)}
