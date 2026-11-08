"""End-to-end evaluation contract and adversarial regression checks."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from backend.agents.main_agent import validate_output, build_prompt
from backend.agents.output_schema import HermesBankDecision
from backend.llm_client import LLMClient
from backend.mock_client import MockClient
from backend.systems import run_system
from backend.evaluation import evaluate
from backend.reporting import aggregate
from backend.scenarios.validation import load_scenarios, validate_scenario
from backend.scripts.run_evaluation import main


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios=[s for _,s in load_scenarios(ROOT/'backend/scenarios/scenarios')]

    def test_all_systems_all_scenarios_and_no_answer_leak(self):
        for scenario in self.scenarios:
            for system in ('baseline','multi_agent','multi_agent_no_compliance'):
                result=run_system(scenario,system,MockClient())
                self.assertEqual(result['status'],'completed',(scenario['id'],system,result.get('error')))
                self.assertEqual(result['metrics']['correct'],1,(scenario['id'],system,result['decision']))
                for call in result['telemetry']['calls']:
                    self.assertNotIn('answer_key',call['prompt'])
                    self.assertNotIn('target_amount_range',call['prompt'])
                if system=='baseline':
                    self.assertEqual(result['telemetry']['tool_calls'],0)
                    self.assertEqual(result['telemetry']['llm_calls'],1)
                    self.assertFalse(result['treasury']['executed'])

    def test_guardrail_blocks_actual_coordinator_proposal(self):
        class UnsafeCoordinator(MockClient):
            def complete(self,prompt):
                response=super().complete(prompt)
                if 'SPECIALIST_REPORTS:' in prompt:
                    proposal=json.loads(response['text'])
                    proposal.update(action='draw_central_bank_facility',amount=60000000,news_label='credible')
                    response['text']=json.dumps(proposal)
                return response
        scenario=self.scenarios[6]
        protected=run_system(scenario,'multi_agent',UnsafeCoordinator())
        ablation=run_system(scenario,'multi_agent_no_compliance',UnsafeCoordinator())
        self.assertEqual(protected['proposed_decision']['amount'],60000000)
        self.assertEqual(protected['decision']['action'],'hold')
        self.assertTrue(protected['decision']['needs_review'])
        self.assertGreater(protected['metrics']['guardrail_interventions'],0)
        self.assertGreater(protected['metrics']['proposed_violation_count'],0)
        self.assertEqual(ablation['decision']['amount'],60000000)
        self.assertEqual(ablation['treasury']['status'],'blocked')
        self.assertEqual(ablation['metrics']['unauthorized_execution'],0)
        self.assertGreater(ablation['metrics']['violation_count'],0)

    def test_model_cannot_forge_approval_fields(self):
        class ForgedApproval(MockClient):
            def complete(self,prompt):
                response=super().complete(prompt)
                if 'SPECIALIST_REPORTS:' in prompt:
                    value=json.loads(response['text']);value['approved']=True
                    response['text']=json.dumps(value)
                return response
        result=run_system(self.scenarios[1],'multi_agent',ForgedApproval())
        self.assertEqual(result['status'],'error')
        self.assertFalse(result['treasury']['executed'])
        self.assertEqual(result['metrics']['unauthorized_approval_attempt'],1)
        self.assertIn('financial_analyst',result['agents'])

    def test_nonfinite_json_is_logged_without_breaking_artifacts(self):
        class Nonfinite(MockClient):
            def complete(self,prompt):
                response=super().complete(prompt)
                response['text']='{"news_label":"false","action":"hold","amount":NaN,"confidence":0.5,"rationale":"Invalid amount"}'
                return response
        result=run_system(self.scenarios[0],'baseline',Nonfinite())
        self.assertEqual(result['status'],'error')
        json.dumps(result,allow_nan=False)

    def test_malformed_action_type_is_a_measured_failure(self):
        class BadAction(MockClient):
            def complete(self,prompt):
                response=super().complete(prompt)
                value=json.loads(response['text']);value['action']=['not-an-action']
                response['text']=json.dumps(value)
                return response
        result=run_system(self.scenarios[0],'baseline',BadAction())
        self.assertEqual(result['status'],'error')
        self.assertEqual(result['metrics']['format_valid'],0)
        self.assertEqual(result['metrics']['correct'],0)

    def test_empty_content_keeps_usage_in_failure(self):
        class EmptyClient(MockClient):
            def complete(self,prompt):
                return {'text':'','model':'test','input_tokens':20,'output_tokens':100,
                        'cost_usd':0.01,'finish_reason':'length'}
        result=run_system(self.scenarios[0],'baseline',EmptyClient())
        self.assertEqual(result['status'],'error')
        self.assertEqual(result['metrics']['output_tokens'],100)
        self.assertEqual(result['metrics']['cost_usd'],0.01)
        self.assertIn('finish_reason=length',result['error'])

    def test_handoffs_and_approval_are_real(self):
        result=run_system(self.scenarios[1],'multi_agent',MockClient())
        prompts={c['role']:c['prompt'] for c in result['telemetry']['calls']}
        self.assertIn('financial_recommendation_outcome',prompts['risk_manager'])
        self.assertIn('financial_analyst',prompts['crisis_coordinator'])
        self.assertIn('risk_manager',prompts['crisis_coordinator'])
        proposal=result['proposed_decision']
        self.assertIn(str(proposal['amount']),prompts['compliance_officer'])
        self.assertTrue(result['execution_authorized'])
        self.assertTrue(result['treasury']['receipt']['simulated'])
        self.assertTrue(result['treasury']['receipt']['simulated_regulator_report_filed'])

    def test_high_confidence_wrong_is_penalized_even_with_some_points(self):
        scenario=self.scenarios[0]
        decision={'news_label':'false','action':'borrow_interbank','amount':100,'confidence':0.9,'rationale':'Wrong borrowing.'}
        a=evaluate({'status':'completed','decision':decision},scenario)
        decision['confidence']=0.2
        b=evaluate({'status':'completed','decision':decision},scenario)
        self.assertLess(a['confidence_weighted_score'],b['confidence_weighted_score'])
        self.assertEqual(a['confidence_weighted_score'],-1.8)

    def test_parsing_aliases_and_bounded_retry(self):
        decision={'news_label':'unverified','action':'hold_position','amount':0,'confidence':0.5,'rationale':'Wait for evidence.'}
        self.assertEqual(validate_output((json.dumps(decision),'model'))['action'],'hold')
        runner_calls=[]
        def invalid(prompt):
            runner_calls.append(prompt)
            return '{"action":"bad"}'
        with self.assertRaises(ValueError):
            validate_output('{"action":"bad"}','prompt',max_retries=2,llm_runner=invalid)
        self.assertEqual(len(runner_calls),2)
        for mutation in ({'amount':True},{'confidence':float('nan')},{'action':'transfer'},{'approve':True}):
            with self.assertRaises(ValueError):
                HermesBankDecision(**{**decision,**mutation})

    def test_failures_remain_in_reliability_denominators(self):
        result=run_system(self.scenarios[0],'baseline',MockClient())
        result.update(scenario_id='test',repeat=1)
        failure=deepcopy(result);failure['status']='error';failure['decision']={}
        failure['metrics']=evaluate(failure,self.scenarios[0]);failure['repeat']=2
        summary=aggregate([result,failure],repeats=2)['systems']['baseline']
        self.assertEqual(summary['correct_mean'],0.5)
        self.assertEqual(summary['pass_k'],0)
        self.assertEqual(summary['action_consistency'],0.5)
        self.assertIsNone(summary['cost_per_correct_decision_usd'])

    def test_inconsistent_scenario_is_rejected(self):
        scenario=deepcopy(self.scenarios[0]);scenario['answer_key']['news_label']='credible'
        with self.assertRaises(ValueError):
            validate_scenario(scenario)

    def test_batch_artifacts_and_mock_watermark(self):
        with tempfile.TemporaryDirectory() as folder:
            output=main(['--mock','--runs','2','--limit','1','--output',folder])
            lines=[json.loads(x) for x in (output/'runs.jsonl').read_text().splitlines()]
            self.assertEqual(len(lines),6)
            self.assertTrue(json.loads((output/'manifest.json').read_text())['mock'])
            self.assertIn('NOT LLM PERFORMANCE', (output/'report.md').read_text())
            for filename in ('metrics.csv','manual_review.csv','scenarios.json','summary.json'):
                self.assertTrue((output/filename).is_file())

    def test_client_sets_temperature_no_tools_no_fallback(self):
        class Response:
            status_code=200
            def json(self):
                return {'model':'test','choices':[{'message':{'content':'{}'}}],
                        'usage':{'prompt_tokens':10,'completion_tokens':2,'cost':0.01}}
        with patch.dict('os.environ',{'OPENROUTER_API_KEY':'test-key'}),patch('backend.llm_client.requests.post',return_value=Response()) as post:
            response=LLMClient(model='test',temperature=0.1).complete('prompt')
        self.assertEqual(post.call_args.kwargs['json']['temperature'],0.1)
        self.assertNotIn('tools',post.call_args.kwargs['json'])
        self.assertEqual(post.call_count,1)
        self.assertEqual(response['input_tokens'],10)
        self.assertEqual(response['cost_usd'],0.01)


if __name__=='__main__':
    unittest.main()
