"""Deterministic plumbing fixture. NEVER use its outputs as LLM research results."""
import json


def _object_after(prompt, marker):
    text = prompt.split(marker, 1)[1].lstrip()
    return json.JSONDecoder().raw_decode(text)[0]


class MockClient:
    model = 'MOCK-NOT-AN-LLM'
    temperature = 0.1
    transport = 'mock'

    def complete(self, prompt):
        if 'BASELINE_AGENT_STATE:' in prompt:
            state = _object_after(prompt, 'BASELINE_AGENT_STATE:')
            observations = [h['observation'] for h in state['history'] if h.get('observation', {}).get('ok')]
            scenario = state['scenario']
            seen = {item['tool'] for item in observations}
            if 'verify_claim' not in seen:
                output = {'type':'tool_call','tool':'verify_claim','arguments':{}}
            else:
                missing = any(key not in scenario.get('financials', {}) or scenario['financials'][key] is None
                              for key in ('capital','liquidity','borrowing_limit','daily_withdrawals'))
                if not missing and 'get_bank_financials' not in seen:
                    output = {'type':'tool_call','tool':'get_bank_financials','arguments':{}}
                elif not missing and 'build_financial_report' not in seen:
                    output = {'type':'tool_call','tool':'build_financial_report','arguments':{}}
                elif not missing and 'compare_action_outcomes' not in seen:
                    output = {'type':'tool_call','tool':'compare_action_outcomes','arguments':{}}
                else:
                    news = next((o['result'] for o in observations if o['tool']=='verify_claim'), {})
                    report = next((o['result'] for o in observations if o['tool']=='build_financial_report'), {})
                    gap = report.get('funding_gap', 0)
                    financials = scenario.get('financials', {})
                    rules = scenario.get('regulations', {})
                    if missing or gap <= 0:
                        action, amount = 'hold', 0
                    elif gap <= financials['borrowing_limit']:
                        action, amount = 'borrow_interbank', report['suggested_funding_by_action']['borrow_interbank']
                    elif gap <= rules.get('max_draw_facility', 0):
                        action, amount = 'draw_central_bank_facility', report['suggested_funding_by_action']['draw_central_bank_facility']
                    else:
                        action, amount = 'hold', 0
                    trigger = scenario.get('trigger','').casefold()
                    output = {'type':'final','decision':{
                        'news_label':news.get('news_label','unverified'),
                        'action':action,'amount':amount,'confidence':0.5,
                        'rationale':'Deterministic mock response. Not an LLM performance result.',
                        'needs_review':missing,
                        'untrusted_content_flagged':any(term in trigger for term in ('ignore','admin note'))}}
        elif 'SPECIALIST_AGENT_STATE:' in prompt:
            state = _object_after(prompt, 'SPECIALIST_AGENT_STATE:')
            required = state['context']['required_tools']
            observations = [h['observation'] for h in state['history'] if h.get('observation', {}).get('ok')]
            missing = [name for name in required if not any(o['tool'] == name for o in observations)]
            if missing:
                output = {'type': 'tool_call', 'tool': missing[0], 'arguments': {}}
            else:
                output = {'type': 'final', 'summary': 'Mock evidence interpretation; not LLM performance.',
                          'confidence': 0.5, 'observation_ids': [o['id'] for o in observations]}
        elif 'FINANCIAL_REACT_STATE:' in prompt:
            state = _object_after(prompt, 'FINANCIAL_REACT_STATE:')
            observations = [h['observation'] for h in state['history'] if h.get('observation', {}).get('ok')]
            financials = next((o for o in observations if o.get('tool') == 'get_bank_financials'), None)
            report_observation = next((o for o in observations if o.get('tool') == 'build_financial_report'), None)
            if financials is None:
                output = {'type':'tool_call','tool':'get_bank_financials','arguments':{}}
            elif report_observation is None:
                output = {'type':'tool_call','tool':'build_financial_report','arguments':{}}
            else:
                report = report_observation['result']
                gap = report['funding_gap']
                action = 'hold' if gap == 0 else ('borrow_interbank' if gap <= report['funding_capacity_by_action']['borrow_interbank'] else 'draw_central_bank_facility')
                output = {'type':'final','recommendation':{'recommendation':action,
                    'amount':report['suggested_funding_by_action'][action], 'confidence':0.5,
                    'rationale':f'Funding gap is {gap}. Mock recommendation, not an LLM result.'},
                    'claims':[{'metric':'funding_gap','value':gap,'unit':'amount','observation_id':report_observation['id']}]}
        elif 'Return JSON only: {"summary"' in prompt:
            output = {'summary': 'Mock interpretation for plumbing checks only.', 'confidence': 0.5}
        elif 'FINANCIAL_REPORT:' in prompt:
            report = _object_after(prompt, 'FINANCIAL_REPORT:')
            gap = report['funding_gap']
            action = 'hold' if gap == 0 else ('borrow_interbank' if gap <= report['funding_capacity_by_action']['borrow_interbank'] else 'draw_central_bank_facility')
            output = {'recommendation': action, 'amount': report['suggested_funding_by_action'][action],
                      'confidence': 0.5, 'rationale': 'Mock recommendation, not an LLM result.'}
        else:
            scenario = _object_after(prompt, 'SCENARIO_INPUT:')
            support, refute = set(), set()
            for source in scenario.get('news_sources', []):
                if source.get('trusted') is True and source.get('independence_group'):
                    if source.get('verdict') == 'supports':
                        support.add(source['independence_group'])
                    if source.get('verdict') == 'refutes':
                        refute.add(source['independence_group'])
            label = 'unverified' if support and refute else 'credible' if len(support) >= 2 else 'false' if len(refute) >= 2 else 'unverified'
            f = scenario.get('financials', {})
            missing = any(k not in f or f[k] is None for k in ('capital','liquidity','borrowing_limit','daily_withdrawals'))
            forecast = f.get('forecast_next_7d')
            gap = 0 if missing else max(0, (forecast if forecast is not None else f['daily_withdrawals'] * 7) - f['liquidity'])
            action = 'hold' if gap == 0 else ('borrow_interbank' if gap <= f['borrowing_limit'] else 'draw_central_bank_facility')
            limit = 0 if missing or action == 'hold' else f['borrowing_limit'] if action == 'borrow_interbank' else scenario['regulations'].get('max_draw_facility', 0)
            output = {'news_label': label, 'action': action, 'amount': min(gap, limit), 'confidence': 0.5,
                      'rationale': 'Deterministic mock response. Not measured LLM performance.',
                      'needs_review': missing,
                      'untrusted_content_flagged': any(t in scenario.get('trigger','').lower() for t in ('ignore', 'admin note'))}
        return {'text': json.dumps(output), 'model': self.model, 'temperature': self.temperature,
                'transport': self.transport, 'input_tokens': None, 'output_tokens': None, 'cost_usd': None}
