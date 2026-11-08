"""API integration checks; model calls are mocked so tests need no credentials."""
import json
import unittest
from unittest.mock import patch

import server


class AgentApiTests(unittest.TestCase):
    def setUp(self):
        server.task_status = "pending"
        self.client = server.app.test_client()
        registry = patch.object(server, 'SECONDARY_AGENTS', {'financial_analyst': server.run_financial_analyst})
        registry.start()
        self.addCleanup(registry.stop)

    def run_synchronously(self):
        class InlineThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                self.target()
        return patch.object(server.threading, "Thread", InlineThread)

    def start_run(self):
        response = self.client.post('/api/run', json={"scenario": "scn_001_false_rumor_healthy.json"})
        self.assertEqual(response.status_code, 200)
        return self.client.get('/api/task/' + response.json['task_id']).json

    def test_real_agent_pipeline_and_answer_key_isolation(self):
        decision = {"news_label": "unverified", "action": "hold", "amount": 0,
                    "confidence": 0.5, "rationale": "Adequate liquidity"}
        recommendation = {"recommendation": "hold", "amount": 0, "confidence": 0.5, "rationale": "Adequate liquidity"}
        responses = [(json.dumps(value), 'test-model') for value in (decision, recommendation)]
        with self.run_synchronously(), patch.object(server, 'run_agent', side_effect=responses) as runner:
            result = self.start_run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(runner.call_count, 2)
        for call in runner.call_args_list:
            self.assertNotIn('answer_key', call.args[0])
        self.assertIn('FINANCIAL_REPORT', runner.call_args_list[1].args[0])
        self.assertEqual(runner.call_args_list[0].args[0], server.build_prompt(result['result']['scenario_input']))
        self.assertNotIn('FINANCIAL_REPORT', runner.call_args_list[0].args[0])
        self.assertNotIn('PRELIMINARY_ASSESSMENT', runner.call_args_list[1].args[0])
        self.assertEqual(result['result']['baseline']['decision'], decision)
        self.assertEqual(result['result']['secondary']['agents']['financial_analyst']['status'], 'completed')
        self.assertEqual(result['trace'][1]['source'], 'financial_analyst')
        self.assertEqual(result['trace'][1]['model'], 'test-model')
        self.assertEqual(len(result['trace']), 3)

    def test_failures_are_reported_without_simulation(self):
        for response in ('not JSON', '{"action":"invalid"}'):
            with self.run_synchronously(), patch.object(server, 'run_agent', return_value=(response, 'test')):
                result = self.start_run()
            self.assertEqual(result['status'], 'error')
            self.assertFalse(any(t.get('model') for t in result['trace']))
        with self.run_synchronously(), patch.object(server, 'run_agent', side_effect=FileNotFoundError('Hermes missing')):
            result = self.start_run()
        self.assertIn('Hermes missing', result['error'])

    def test_secondary_failure_preserves_baseline(self):
        decision = {"news_label": "unverified", "action": "hold", "amount": 0,
                    "confidence": 0.5, "rationale": "Baseline preserved"}
        with self.run_synchronously(), patch.object(server, 'run_agent', side_effect=[
            (json.dumps(decision), 'test-model'), RuntimeError('Specialist failed')
        ]):
            result = self.start_run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['result']['baseline']['decision'], decision)
        self.assertEqual(result['result']['secondary']['status'], 'error')

    def test_baseline_failure_does_not_stop_secondary(self):
        recommendation = {"recommendation": "hold", "amount": 0, "confidence": 0.5, "rationale": "Independent"}
        with self.run_synchronously(), patch.object(server, 'run_agent', side_effect=[
            RuntimeError('Baseline failed'), (json.dumps(recommendation), 'test-model')
        ]):
            result = self.start_run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['result']['baseline']['status'], 'error')
        self.assertEqual(result['result']['secondary']['status'], 'completed')

    def test_scenario_validation(self):
        scenarios = self.client.get('/api/scenarios').json['scenarios']
        self.assertEqual(len(scenarios), 10)
        for value in ('scenario.json', '../README.md', ['invalid']):
            self.assertEqual(self.client.post('/api/run', json={'scenario': value}).status_code, 400)
        self.assertEqual(self.client.get('/api/task/unknown').status_code, 404)

    def test_concurrent_run_is_rejected(self):
        server.task_status = 'running'
        self.assertEqual(self.client.post('/api/run', json={'scenario': 'scn_001_false_rumor_healthy.json'}).status_code, 409)

    def test_all_specialists_and_treasury_waiting(self):
        decision = {"news_label": "unverified", "action": "hold", "amount": 0,
                    "confidence": 0.5, "rationale": "Adequate liquidity"}
        recommendation = {"recommendation": "hold", "amount": 0, "confidence": 0.5, "rationale": "Adequate liquidity"}
        interpretation = {"summary": "Evidence reviewed", "confidence": 0.5}
        registry = {'financial_analyst': server.run_financial_analyst,
                    'news_verification': server.run_news_verification,
                    'risk_manager': server.run_risk_manager,
                    'compliance_officer': server.run_compliance_officer,
                    'treasury_operations': server.run_treasury_operations}
        responses = [(json.dumps(v), 'test-model') for v in
                     (decision, recommendation, interpretation, interpretation, interpretation)]
        with patch.object(server, 'SECONDARY_AGENTS', registry), self.run_synchronously(), patch.object(server, 'run_agent', side_effect=responses) as runner:
            result = self.start_run()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(runner.call_count, 5)
        agents = result['result']['secondary']['agents']
        self.assertEqual(len(agents), 5)
        self.assertTrue(all(a['status'] == 'completed' for a in agents.values()))
        self.assertEqual(agents['treasury_operations']['output']['status'], 'awaiting_authorization')
        self.assertIsNone(agents['treasury_operations']['model'])
        self.assertEqual(agents['news_verification']['output']['report']['news_label'], 'unverified')
        for call in runner.call_args_list:
            self.assertNotIn('answer_key', call.args[0])


if __name__ == '__main__':
    unittest.main()
