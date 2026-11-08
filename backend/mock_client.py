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
        if 'Return JSON only: {"summary"' in prompt:
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
