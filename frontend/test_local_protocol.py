"""Local response constraints preserve evidence and budget requirements."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.local_protocol import response_schema
from backend.agents.compliance_officer import _review_action


class LocalProtocolTests(unittest.TestCase):
    def state(self, observations=(), remaining=4):
        return {'history': [{'observation': o} for o in observations],
                'tools': [{'name': n} for n in ('retrieve_news', 'verify_claim', 'search_news')],
                'context': {'required_tools': ['retrieve_news', 'verify_claim']},
                'tool_calls_remaining': remaining, 'steps_remaining': 3}

    def schema(self, state):
        return response_schema('SPECIALIST_AGENT_STATE:\n' + json.dumps(state))

    def test_missing_verdict_cannot_finalize(self):
        schema = self.schema(self.state([{'id': 'obs_1', 'tool': 'retrieve_news', 'ok': True}]))
        self.assertEqual(schema['properties']['type']['const'], 'tool_call')
        self.assertEqual(schema['properties']['tool']['enum'], ['verify_claim'])

    def test_exhausted_budget_requires_final_citing_required_evidence(self):
        observations = [{'id': 'obs_1', 'tool': 'retrieve_news', 'ok': True},
                        {'id': 'obs_2', 'tool': 'verify_claim', 'ok': True}]
        schema = self.schema(self.state(observations, remaining=0))
        self.assertEqual(schema['properties']['type']['const'], 'final')
        self.assertEqual(schema['properties']['observation_ids']['const'], ['obs_1', 'obs_2'])

    def test_finance_requires_real_report_before_final(self):
        state = self.state()
        state['tools'] = [{'name': 'get_bank_financials'}, {'name': 'build_financial_report'}]
        schema = response_schema('FINANCIAL_REACT_STATE:\n' + json.dumps(state))
        self.assertEqual(schema['properties']['tool']['enum'], ['build_financial_report'])

    def test_unrelated_prompts_keep_json_mode(self):
        self.assertEqual(response_schema('Return JSON'), 'json')

    def test_compliance_must_retrieve_before_a_supported_finding(self):
        state = {'evidence_by_authority': {}, 'retrieval_calls_remaining': 3, 'turns_remaining': 2}
        schema = response_schema('COMPLIANCE_REVIEW_STATE:\n' + json.dumps(state))
        self.assertEqual(schema['properties']['type']['const'], 'retrieve')
        state.update(retrieval_calls_remaining=0, turns_remaining=0)
        schema = response_schema('COMPLIANCE_REVIEW_STATE:\n' + json.dumps(state))
        self.assertEqual(schema['properties']['finding']['enum'], ['undetermined'])

    def test_simulation_ratio_cannot_support_a_regulatory_lcr_breach(self):
        class Retrieval:
            def search(self, query, limit):
                return [{'evidence_id': 'notice:1', 'authority_type': 'binding_rule',
                         'text': 'A regulatory LCR threshold applies to reporting banks.'}]

        responses = iter([
            {'type': 'retrieve', 'query': 'liquidity requirements'},
            {'type': 'final', 'finding': 'non_compliant', 'rationale': 'The LCR is below the threshold.',
             'citations': ['notice:1'], 'missing_facts': []},
            {'type': 'final', 'finding': 'undetermined', 'rationale': 'Regulatory LCR inputs are missing.',
             'citations': ['notice:1'], 'missing_facts': ['Regulatory LCR and reporting-bank classification']},
        ])
        result = _review_action({'action': 'hold', 'amount': 0},
                                {'financials': {'capital': 100, 'liquidity': 20},
                                 '_retriever': (Retrieval(), '')}, lambda prompt: next(responses))
        self.assertEqual(result['finding'], 'undetermined')
        self.assertTrue(result['missing_facts'])
        self.assertIn('LCR evidence is missing', result['protocol_history'][1]['error'])


if __name__ == '__main__':
    unittest.main()
