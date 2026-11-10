"""Offline trajectory, recovery and approval-boundary checks from Topic 7."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.agents.news_verification import run_news_verification
from backend.agents.treasury_operations import run_treasury_operations
from backend.agents.financial_analyst import run_financial_analyst
from tools.treasury_tools import TreasurySimulation
from tools.news_tools import inspect_source_provenance, inspect_evidence_conflicts, search_news
from tools.financial_tools import compare_outflow_estimates, stress_test_outflows
from tools.treasury_tools import inspect_funding_effect, inspect_reporting_requirements, inspect_execution_requirements
from tools.financial_tools import execute_financial_tool
from copy import deepcopy
from backend.mock_client import MockClient
from backend.systems import run_system
from test_financial_analyst import SCENARIO, tool, final, Scripted


def finish(*ids):
    return {'type': 'final', 'summary': 'Controlled evidence reviewed; authorization is separate.',
            'confidence': 0.5, 'observation_ids': list(ids)}


class AgenticUpgradeTests(unittest.TestCase):
    def test_expanded_paths_obey_role_allowlists_in_full_pipeline(self):
        class DiagnosticClient(MockClient):
            def complete(self, prompt):
                choices = []
                if 'SPECIALIST_AGENT_STATE:' in prompt:
                    state = json.JSONDecoder().raw_decode(prompt.split('SPECIALIST_AGENT_STATE:', 1)[1].lstrip())[0]
                    choices = ([tool('inspect_source_provenance'), tool('inspect_evidence_conflicts')]
                               if state['role'] == 'News Verification Agent' else
                               [tool('inspect_funding_effect'), tool('inspect_reporting_requirements'), tool('inspect_execution_requirements')])
                elif 'FINANCIAL_REACT_STATE:' in prompt:
                    state = json.JSONDecoder().raw_decode(prompt.split('FINANCIAL_REACT_STATE:', 1)[1].lstrip())[0]
                    choices = [tool('compare_outflow_estimates'), tool('stress_test_outflows', multiplier=1.5)]
                if choices:
                    used = {h.get('action', {}).get('tool') for h in state['history']}
                    missing = next((c for c in choices if c['tool'] not in used), None)
                    if missing:
                        return {'text': json.dumps(missing), 'model': self.model}
                return super().complete(prompt)
        path = Path(__file__).resolve().parent.parent / 'backend/scenarios/scenarios/scn_001_false_rumor_healthy.json'
        result = run_system(json.loads(path.read_text()), 'multi_agent', DiagnosticClient())
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['metrics']['tool_allowlist']['valid'])
        for role in ('news_verification', 'financial_analyst', 'treasury_operations'):
            self.assertEqual(result['agents'][role]['output']['analysis_metrics']['valid_tool_calls'], 4)
        self.assertFalse(result['treasury']['executed'])

    def test_provenance_and_conflicts_expose_duplicate_group_without_relabelling(self):
        scenario = deepcopy(SCENARIO)
        scenario['news_sources'] = [
            {'source_id': 'a', 'independence_group': 'same', 'trusted': True, 'verdict': 'supports', 'content': 'Cash withdrawals rise'},
            {'source_id': 'b', 'independence_group': 'same', 'trusted': True, 'verdict': 'refutes', 'content': 'No insolvency'},
            {'source_id': 'c', 'independence_group': 'other', 'trusted': False, 'verdict': 'unknown', 'content': 'withdrawals rumour'}]
        groups = inspect_source_provenance(scenario)['groups']
        self.assertTrue(next(g for g in groups if g['independence_group'] == 'same')['multiple_records_same_group'])
        self.assertEqual(inspect_evidence_conflicts(scenario)['same_group_conflicts'], ['same'])
        self.assertEqual(search_news(scenario, 'WITHDRAWALS')['match_count'], 2)
        self.assertEqual(search_news(scenario, 'unmatched')['match_count'], 0)
        runner = Scripted([tool('retrieve_news'), tool('inspect_source_provenance'),
                           tool('inspect_evidence_conflicts'), tool('verify_claim'), finish('obs_1', 'obs_4')])
        result = run_news_verification(scenario, runner)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['analysis_metrics']['valid_tool_calls'], 4)
        self.assertEqual(result['report']['news_label'], 'unverified')

    def test_news_search_tool_path_and_argument_validation(self):
        runner = Scripted([tool('search_news', query='cash'), tool('retrieve_news'), tool('verify_claim'), finish('obs_2', 'obs_3')])
        self.assertEqual(run_news_verification(SCENARIO, runner)['status'], 'completed')
        for query in ('', ' '*5, 7, 'a'*201):
            with self.assertRaises(ValueError):
                search_news(SCENARIO, query)

    def test_financial_diagnostics_preserve_baseline_and_handle_missing_forecast(self):
        scenario = deepcopy(SCENARIO)
        scenario['financials']['forecast_next_7d'] = 70
        result = compare_outflow_estimates(scenario)
        self.assertEqual(result['forecast_difference'], -70)
        self.assertEqual(result['selected_7d_forecast'], 70)
        self.assertEqual(stress_test_outflows(scenario, 2)['stressed_funding_gap'], 120)
        self.assertEqual(scenario['financials']['forecast_next_7d'], 70)
        scenario['financials']['forecast_next_7d'] = None
        self.assertEqual(compare_outflow_estimates(scenario)['forecast_source'], 'daily_rate_extrapolation')
        for value in (True, 0, 4, float('nan'), float('inf'), '2'):
            with self.assertRaises(ValueError):
                execute_financial_tool('stress_test_outflows', {'multiplier': value}, scenario)

    def test_financial_can_choose_diagnostic_path_within_existing_budget(self):
        claim = {'metric': 'funding_gap', 'value': 120, 'unit': 'amount', 'observation_id': 'obs_3'}
        runner = Scripted([tool('compare_outflow_estimates'), tool('stress_test_outflows', multiplier=1.5),
                           tool(), final(claims=[claim])])
        result = run_financial_analyst(SCENARIO, runner)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['analysis_metrics']['valid_tool_calls'], 3)
        self.assertEqual(result['metrics']['funding_gap'], 120)

    def test_treasury_diagnostic_path_does_not_authorize_or_file_report(self):
        proposal = {'action': 'borrow_interbank', 'amount': 100}
        scenario = deepcopy(SCENARIO)
        scenario['regulations']['report_to_regulator'] = True
        runner = Scripted([tool('inspect_funding_effect'), tool('inspect_reporting_requirements'),
                           tool('inspect_execution_requirements'), tool('prepare_execution_plan'), finish('obs_4')])
        result = run_treasury_operations(scenario, runner, proposal=proposal)
        self.assertEqual(result['analysis_metrics']['valid_tool_calls'], 4)
        self.assertFalse(result['executed'])
        self.assertEqual(inspect_funding_effect(scenario, proposal)['remaining_funding_gap'], 20)
        self.assertFalse(inspect_reporting_requirements(scenario)['regulator_report_sent'])
        self.assertFalse(inspect_execution_requirements(scenario, proposal)['execution_authorized'])
        self.assertFalse(inspect_funding_effect(scenario, {**proposal, 'amount': 101})['available'])
        self.assertFalse(inspect_funding_effect(scenario, None)['available'])

    def test_news_recovers_from_fabricated_citation_and_keeps_private_key_out(self):
        runner = Scripted([tool('retrieve_news'), tool('verify_claim'), finish('invented'), finish('obs_1', 'obs_2')])
        output = run_news_verification(SCENARIO, runner)
        self.assertEqual(output['status'], 'completed')
        self.assertEqual(output['report']['news_label'], 'unverified')
        self.assertIn('Cite only successful', runner.prompts[-1])
        self.assertNotIn('NEVER_EXPOSE', ''.join(runner.prompts))

    def test_news_rejects_execution_tool_and_host_input_replacement(self):
        runner = Scripted([tool('approve'), tool('retrieve_news', trusted=True),
                           tool('retrieve_news'), tool('verify_claim'), finish('obs_3', 'obs_4')])
        output = run_news_verification(SCENARIO, runner)
        self.assertEqual(output['analysis_metrics']['invalid_tool_calls'], 2)
        self.assertEqual(output['status'], 'completed')

    def test_news_cannot_finalize_without_observing_sources(self):
        runner = Scripted([tool('verify_claim'), finish('obs_1')])
        output = run_news_verification(SCENARIO, runner, max_steps=2)
        self.assertIsNone(output['interpretation'])
        self.assertEqual(output['status'], 'needs_review')

    def test_budget_prevents_extra_tool_execution(self):
        runner = Scripted([tool('retrieve_news'), tool('verify_claim'), finish('obs_1')])
        output = run_news_verification(SCENARIO, runner, max_steps=3, max_tool_calls=1)
        self.assertEqual(output['analysis_metrics']['valid_tool_calls'], 1)
        self.assertTrue(output['analysis_metrics']['budget_exhausted'])

    def test_treasury_prepares_candidate_but_does_not_execute(self):
        proposal = {'action': 'borrow_interbank', 'amount': 100}
        runner = Scripted([tool('prepare_execution_plan'), finish('obs_1')])
        output = run_treasury_operations(SCENARIO, runner, proposal=proposal)
        self.assertEqual(output['status'], 'awaiting_authorization')
        self.assertTrue(output['execution_plan']['ready_for_host_review'])
        self.assertFalse(output['executed'])
        self.assertNotIn('NEVER_EXPOSE', ''.join(runner.prompts))

    def test_treasury_blocks_approval_tool_and_noncompliant_candidate(self):
        runner = Scripted([tool('approve'), tool('prepare_execution_plan'), finish('obs_2')])
        output = run_treasury_operations(SCENARIO, runner, proposal={'action': 'borrow_interbank', 'amount': 101})
        self.assertFalse(output['execution_plan']['ready_for_host_review'])
        self.assertFalse(output['executed'])
        self.assertEqual(output['analysis_metrics']['invalid_tool_calls'], 1)

    def test_approved_execution_does_not_depend_on_llm(self):
        book = TreasurySimulation()
        proposal = {'action': 'borrow_interbank', 'amount': 10}
        approval = book.approve(SCENARIO, proposal, approved_by='human_reviewer')
        def unexpected(prompt):
            self.fail('Approved execution must remain deterministic')
        first = run_treasury_operations(SCENARIO, unexpected, book=book, proposal=proposal, approval_id=approval)
        second = run_treasury_operations(SCENARIO, unexpected, book=book, proposal=proposal, approval_id=approval)
        self.assertEqual(first['receipt'], second['receipt'])

    def test_financial_recovers_from_numeric_error_using_feedback(self):
        runner = Scripted([tool(), final(rationale='Funding gap is 999 million.'), final()])
        output = run_financial_analyst(SCENARIO, runner)
        self.assertEqual(output['status'], 'completed')
        self.assertFalse(output['react_trace'][1]['validation']['passed'])
        self.assertIn('last_validation', runner.prompts[-1])
        self.assertEqual(output['analysis_metrics']['react_steps'], 3)


if __name__ == '__main__':
    unittest.main()
