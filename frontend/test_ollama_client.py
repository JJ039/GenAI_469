"""Local inference request, telemetry and connection failure contracts."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.llm_client import LLMClient


class OllamaClientTests(unittest.TestCase):
    def test_local_json_request_without_credentials(self):
        response = Mock(status_code=200)
        response.json.return_value = {'message': {'content': '{"ok":true}'},
                                      'prompt_eval_count': 10, 'eval_count': 5, 'done_reason': 'stop'}
        with patch.dict(os.environ, {}, clear=True), patch('backend.llm_client.load_credentials'), \
                patch('backend.llm_client.requests.post', return_value=response) as post:
            result = LLMClient(transport='ollama').complete('Return JSON')
        self.assertEqual(post.call_args.args[0], 'http://127.0.0.1:11434/api/chat')
        self.assertNotIn('headers', post.call_args.kwargs)
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['model'], 'qwen3:1.7b')
        self.assertEqual(payload['format'], 'json')
        self.assertFalse(payload['stream'])
        self.assertEqual(result['input_tokens'], 10)
        self.assertEqual(result['output_tokens'], 5)
        self.assertEqual(result['cost_usd'], 0)
        self.assertEqual(result['transport'], 'ollama')

    def test_unavailable_server_and_missing_model_are_actionable(self):
        for response, failure, message in (
                (None, requests.ConnectionError(), 'Check that Ollama is running'),
                (Mock(status_code=404), None, 'ollama pull')):
            with self.subTest(message=message), patch.dict(os.environ, {}, clear=True), \
                    patch('backend.llm_client.load_credentials'), \
                    patch('backend.llm_client.requests.post', return_value=response, side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, message):
                    LLMClient(transport='ollama').complete('Return JSON')


if __name__ == '__main__':
    unittest.main()
