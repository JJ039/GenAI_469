"""Coordinator routing and compliance handoff regressions."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.mock_client import MockClient
from backend.systems import run_system


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads((ROOT / 'backend/scenarios/scenarios/scn_001_false_rumor_healthy.json').read_text())

    def test_baseline_calls_only_baseline_model(self):
        result = run_system(self.scenario, 'baseline', MockClient())
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([call['role'] for call in result['telemetry']['calls']], ['baseline'])
        self.assertEqual(result['agents'], {})
        self.assertIn('decision', result)

    def test_false_news_still_runs_all_specialists_once(self):
        result = run_system(self.scenario, 'multi_agent', MockClient())
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([entry['source'] for entry in result['trace']], [
            'news_verification', 'financial_analyst', 'risk_manager',
            'compliance_officer', 'treasury_operations'])
        self.assertFalse(result['treasury']['executed'])
        self.assertTrue(result['telemetry']['tools'])

    def test_compliance_gate_controls_treasury_candidate(self):
        for finding in ('compliant', 'non_compliant', 'undetermined'):
            for synthetic_passed in (True, False):
                with self.subTest(finding=finding, synthetic_passed=synthetic_passed):
                    def review(scenario, llm_runner=None, proposals=None):
                        proposal = proposals[0]
                        return {'report': {
                            'synthetic_checks': [{'proposal': proposal, 'compliant': synthetic_passed}],
                            'regulatory_findings': [{'proposal': proposal, 'finding': finding}]}}

                    with patch('backend.systems.run_compliance_officer', side_effect=review):
                        result = run_system(self.scenario, 'multi_agent', MockClient())
                    self.assertEqual(result['status'], 'completed')
                    candidate = result['treasury']['execution_plan']['proposal']
                    cleared = finding == 'compliant' and synthetic_passed
                    self.assertEqual(candidate is not None, cleared)
                    self.assertEqual(bool(result['compliance_blockers']), not cleared)
                    self.assertFalse(result['treasury']['executed'])


if __name__ == '__main__':
    unittest.main()
