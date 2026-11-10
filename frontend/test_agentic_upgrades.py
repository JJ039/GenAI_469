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
from test_financial_analyst import SCENARIO, tool, final, Scripted


def finish(*ids):
    return {'type': 'final', 'summary': 'Controlled evidence reviewed; authorization is separate.',
            'confidence': 0.5, 'observation_ids': list(ids)}


class AgenticUpgradeTests(unittest.TestCase):
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
