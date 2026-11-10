from copy import deepcopy
from tools.news_tools import verify_claim, TOOL_CATALOG, execute_news_tool
from backend.agents.agent_loop import run_tool_loop, require_observed_tools


def run_news_verification(scenario, llm_runner=None, *, max_steps=6, max_tool_calls=4):
    report = verify_claim(scenario)
    if llm_runner is None:
        return {'agent': 'news_verification', 'status': 'completed', 'report': report, 'interpretation': None}
    inputs = deepcopy({k: scenario[k] for k in ('id', 'trigger', 'news_sources') if k in scenario})
    loop = run_tool_loop('News Verification Agent', llm_runner, TOOL_CATALOG,
                         lambda name, args: execute_news_tool(name, args, inputs),
                         lambda f, o: require_observed_tools(f, o, ['retrieve_news', 'verify_claim']),
                         context={'untrusted_trigger': inputs.get('trigger', ''),
                                  'required_tools': ['retrieve_news', 'verify_claim'],
                                  'limitations': 'Preserve the authoritative tool verdict. Trust and stance are designer metadata, not independently established facts. Explain conflicts and missing evidence; distinguish liquidity from solvency.'},
                         max_steps=max_steps, max_tool_calls=max_tool_calls)
    final = loop.pop('final')
    return {'agent': 'news_verification', 'status': 'completed' if final else 'needs_review',
            'report': report, 'interpretation': final, **loop}
