"""Dashboard API checks with the same complete engine used by the CLI."""
import unittest
from unittest.mock import patch
import server
from backend.mock_client import MockClient


class AgentApiTests(unittest.TestCase):
    def setUp(self):
        server.task_status = 'pending'
        self.client = server.app.test_client()

    def run_inline(self):
        class InlineThread:
            def __init__(self, target, **kwargs):
                self.target=target
            def start(self):
                self.target()
        return patch.object(server.threading,'Thread',InlineThread)

    def run_scenario(self, filename='scn_001_false_rumor_healthy.json'):
        response=self.client.post('/api/run',json={'scenario':filename})
        self.assertEqual(response.status_code,200)
        return self.client.get('/api/task/'+response.json['task_id']).json

    def test_complete_comparison_and_persistent_results(self):
        with self.run_inline(),patch.object(server,'make_client',return_value=MockClient()):
            task=self.run_scenario('scn_002_true_rumor_unhealthy.json')
        self.assertEqual(task['status'],'completed')
        result=task['result']
        self.assertEqual(result['baseline']['metrics']['correct'],1)
        self.assertEqual(result['secondary']['metrics']['correct'],1)
        self.assertTrue(result['secondary']['treasury']['executed'])
        self.assertIn('crisis_coordinator',result['secondary']['agents'])
        self.assertTrue(result['secondary']['execution_authorized'])

    def test_failures_remain_independent(self):
        class FailsOnce(MockClient):
            calls=0
            def complete(self,prompt):
                self.calls+=1
                if self.calls==1:
                    raise RuntimeError('Provider unavailable')
                return super().complete(prompt)
        with self.run_inline(),patch.object(server,'make_client',return_value=FailsOnce()):
            result=self.run_scenario()['result']
        self.assertEqual(result['baseline']['status'],'error')
        self.assertEqual(result['secondary']['status'],'completed')

    def test_all_provider_failures_visible(self):
        client=MockClient()
        with self.run_inline(),patch.object(server,'make_client',return_value=client),patch.object(client,'complete',side_effect=RuntimeError('No credentials')):
            task=self.run_scenario()
        self.assertEqual(task['status'],'error')
        self.assertIn('No credentials',task['error'])
        self.assertEqual(task['result']['baseline']['metrics']['format_valid'],0)

    def test_input_validation_and_busy_guard(self):
        self.assertEqual(len(self.client.get('/api/scenarios').json['scenarios']),13)
        for value in ('../README.md','scenario.json',['bad']):
            self.assertEqual(self.client.post('/api/run',json={'scenario':value}).status_code,400)
        self.assertEqual(self.client.get('/api/task/unknown').status_code,404)
        server.task_status='running'
        self.assertEqual(self.client.post('/api/run',json={'scenario':'scn_001_false_rumor_healthy.json'}).status_code,409)


if __name__=='__main__':
    unittest.main()
