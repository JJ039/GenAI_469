"""Coordinator report generation from complete and incomplete evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.agents.crisis_coordinator import build_team_report
from backend.mock_client import MockClient
from backend.systems import run_system


class CoordinatorReportTests(unittest.TestCase):
    def test_pipeline_emits_report_and_scores_final_decision(self):
        scenario = json.loads((ROOT / 'backend/scenarios/scenarios/scn_001_false_rumor_healthy.json').read_text())
        result = run_system(scenario, 'multi_agent', MockClient())
        self.assertEqual(result['status'], 'completed', result.get('error'))
        self.assertEqual(len(result['report']['sections']), 5)
        self.assertEqual(result['report']['decision'], result['decision'])
        self.assertIn('crisis_coordinator', [entry['source'] for entry in result['trace']])
        self.assertIsInstance(result['score'], (int, float))
        self.assertNotEqual(result['decision_status'], 'awaiting_integration')

    def test_failed_financial_analysis_generates_review_report(self):
        proposal = {'action': 'borrow_interbank', 'amount': 100}
        reports = {
            'news_verification': {'status': 'completed', 'report': {'news_label': 'false'}},
            'financial_analyst': {'status': 'needs_review', 'reason': 'Step budget exhausted'},
            'risk_manager': {'status': 'completed', 'report': {'candidate_outcomes': [
                {'proposal': proposal, 'feasible': True}]}},
            'compliance_officer': {'status': 'completed', 'report': {}},
            'treasury_operations': {'status': 'awaiting_authorization'},
        }
        original = deepcopy(reports)
        report = build_team_report(reports, proposal, [])
        self.assertEqual(report['decision']['action'], 'hold')
        self.assertTrue(report['decision']['needs_review'])
        self.assertIn('Step budget exhausted', report['summary'])
        self.assertEqual(reports, original)


if __name__ == '__main__':
    unittest.main()
