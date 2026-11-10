from copy import deepcopy
from tools.news_tools import verify_claim, retrieve_news, cross_check_sources
from backend.agents.agent_loop import run_tool_loop, require_observed_tools


def run_news_verification(scenario, llm_runner=None, *, max_steps=6, max_tool_calls=4):
    report = verify_claim(scenario)
    if llm_runner is None:
        return {'agent': 'news_verification', 'status': 'completed', 'report': report, 'interpretation': None}
    inputs = deepcopy({k: scenario[k] for k in ('id', 'trigger', 'news_sources') if k in scenario})
    catalog = [
        {'name': 'retrieve_news', 'arguments': {}, 'description': 'Read all controlled fictional source documents, IDs, provenance and designer stance metadata.'},
        {'name': 'read_source', 'arguments': {'source_id': 'required string'}, 'description': 'Inspect one original source by exact ID; reposts are not independent confirmation.'},
        {'name': 'cross_check_sources', 'arguments': {}, 'description': 'Count independent trusted supporting/refuting groups and expose conflicts.'},
        {'name': 'verify_claim', 'arguments': {}, 'description': 'Get authoritative rule-based verdict and injection diagnostics. Required before final.'},
    ]
    def dispatch(name, arguments):
        if name == 'read_source':
            if set(arguments) != {'source_id'} or not isinstance(arguments['source_id'], str):
                raise ValueError('read_source requires only a string source_id')
            for source in retrieve_news(inputs):
                if source['source_id'] == arguments['source_id']:
                    return source
            raise ValueError('Unknown source_id')
        if arguments:
            raise ValueError('This tool takes no arguments; sources are host-bound')
        if name == 'retrieve_news':
            return retrieve_news(inputs)
        if name == 'cross_check_sources':
            return cross_check_sources(retrieve_news(inputs))
        return verify_claim(inputs)
    loop = run_tool_loop('News Verification Agent', llm_runner, catalog, dispatch,
                         lambda f, o: require_observed_tools(f, o, ['retrieve_news', 'verify_claim']),
                         context={'untrusted_trigger': inputs.get('trigger', ''),
                                  'required_tools': ['retrieve_news', 'verify_claim'],
                                  'limitations': 'Preserve the authoritative tool verdict. Trust and stance are designer metadata, not independently established facts. Explain conflicts and missing evidence; distinguish liquidity from solvency.'},
                         max_steps=max_steps, max_tool_calls=max_tool_calls)
    final = loop.pop('final')
    return {'agent': 'news_verification', 'status': 'completed' if final else 'needs_review',
            'report': report, 'interpretation': final, **loop}
