from tools.news_tools import verify_claim
from backend.agents.specialist_common import interpret_report


def run_news_verification(scenario, llm_runner=None):
    report = verify_claim(scenario)
    interpretation = interpret_report("News Verification Agent", report, scenario, llm_runner)
    return {"agent": "news_verification", "status": "completed", "report": report,
            "interpretation": interpretation}
