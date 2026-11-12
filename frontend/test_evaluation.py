"""End-to-end evaluation contract and adversarial regression checks."""
from copy import deepcopy
import json
import csv
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
from backend.evaluation import evaluate, evaluate_tool_allowlist, evaluate_workflow
from backend.reporting import aggregate
from backend.scenarios.validation import load_scenarios, validate_scenario
from backend.scripts.run_evaluation import main


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios=[s for _,s in load_scenarios(ROOT/'backend/scenarios/scenarios')]

    def test_all_systems_all_scenarios_and_no_answer_leak(self):
        for scenario in self.scenarios:
            for system in ('baseline','multi_agent'):
                result=run_system(scenario,system,MockClient())
                self.assertEqual(result['status'],'completed',(scenario['id'],system,result.get('error')))
                if system == 'baseline':
                    self.assertEqual(result['metrics']['correct'],1)
                else:
                    self.assertIsNone(result['metrics']['correct'])
                    self.assertIsNone(result['score'])
                    self.assertNotIn('decision', result)
                    self.assertFalse(result['treasury']['executed'])
                for call in result['telemetry']['calls']:
                    self.assertNotIn('answer_key',call['prompt'])
                    self.assertNotIn('target_amount_range',call['prompt'])
                if system=='baseline':
                    self.assertGreater(result['telemetry']['tool_calls'],0)
                    self.assertGreater(result['telemetry']['llm_calls'],1)
                    self.assertTrue(result['metrics']['tool_allowlist']['valid'])
                    self.assertFalse(result['treasury']['executed'])

    def test_nonfinite_json_is_logged_without_breaking_artifacts(self):
        class Nonfinite(MockClient):
            def complete(self,prompt):
                response=super().complete(prompt)
                output=json.loads(response['text'])
                if output.get('type') == 'final':
                    output['decision']['amount']=float('nan')
                    response['text']=json.dumps(output)
                return response
        result=run_system(self.scenarios[0],'baseline',Nonfinite())
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['baseline_agent']['status'],'needs_review')
        self.assertGreater(result['analysis_metrics']['invalid_final_responses'],0)
        json.dumps(result,allow_nan=False)

    def test_malformed_action_type_is_a_measured_failure(self):
        class BadAction(MockClient):
            def complete(self,prompt):
                response=super().complete(prompt)
                value=json.loads(response['text'])
                if value.get('type') == 'final':
                    value['decision']['action']=['not-an-action']
                    response['text']=json.dumps(value)
                return response
        result=run_system(self.scenarios[0],'baseline',BadAction())
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['baseline_agent']['status'],'needs_review')
        self.assertGreater(result['analysis_metrics']['invalid_final_responses'],0)

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

    def test_specialist_handoffs_without_combined_decision_or_approval(self):
        result=run_system(self.scenarios[1],'multi_agent',MockClient())
        prompts={c['role']:c['prompt'] for c in result['telemetry']['calls']}
        self.assertEqual(set(result['agents']), {'news_verification','financial_analyst','risk_manager','compliance_officer','treasury_operations'})
        self.assertIn('financial_recommendation_outcome',prompts['risk_manager'])
        recommendation=result['agents']['financial_analyst']['output']['recommendation']
        checks=result['agents']['compliance_officer']['output']['report']['checks']
        self.assertEqual(checks[0]['proposal'], {'action':recommendation['recommendation'],'amount':recommendation['amount']})
        self.assertEqual(result['decision_status'],'awaiting_integration')
        self.assertEqual(result['treasury']['status'],'awaiting_authorization')
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(any(t['tool'].endswith('.approve') for t in result['telemetry']['tools']))
        self.assertEqual(result['telemetry']['llm_calls'],10)
        telemetry = result['metrics']['agent_telemetry']
        self.assertGreaterEqual(telemetry['news_verification']['tool_calls'],3)
        self.assertEqual(telemetry['news_verification']['valid_tool_calls'],
                         telemetry['news_verification']['tool_calls'])
        self.assertGreaterEqual(telemetry['financial_analyst']['tool_calls'],3)
        self.assertEqual(telemetry['financial_analyst']['invalid_tool_calls'],0)
        self.assertIn('treasury_operations', telemetry)
        self.assertFalse(result['treasury']['execution_plan']['execution_authorized'])
        self.assertTrue(result['metrics']['tool_allowlist']['valid'])
        self.assertEqual(result['metrics']['tool_allowlist']['violation_count'], 0)
        workflow = result['metrics']['workflow']
        self.assertTrue(workflow['valid'])
        self.assertEqual(workflow['actual_stages'], [
            'news_verification', 'financial_analyst', 'risk_manager',
            'compliance_officer', 'treasury_operations'])
        self.assertTrue(workflow['handoffs']['risk_received_financial_recommendation'])
        self.assertTrue(workflow['handoffs']['compliance_received_financial_recommendation'])
        self.assertTrue(workflow['handoffs']['treasury_waited_for_authorization'])

    def test_workflow_reports_missing_and_out_of_order_stages(self):
        result=run_system(self.scenarios[0], 'multi_agent', MockClient())
        result['trace'] = list(reversed(result['trace']))
        workflow=evaluate_workflow(result)
        self.assertFalse(workflow['valid'])
        self.assertEqual(workflow['violation_count'], 1)
        self.assertEqual(workflow['violations'][0]['kind'], 'stage_order')

    def test_workflow_is_not_applicable_to_baseline(self):
        result=run_system(self.scenarios[0], 'baseline', MockClient())
        workflow=result['metrics']['workflow']
        self.assertFalse(workflow['applicable'])
        self.assertIsNone(workflow['valid'])

    def test_tool_allowlist_reports_disallowed_agent_tool(self):
        result=run_system(self.scenarios[0], 'multi_agent', MockClient())
        result['telemetry']['tools'].append({
            'agent': 'news_verification',
            'tool': 'tools.compliance_tools.check_compliance',
            'valid': True,
        })
        allowlist=evaluate_tool_allowlist(result)
        self.assertFalse(allowlist['valid'])
        self.assertEqual(allowlist['violation_count'], 1)
        self.assertEqual(allowlist['violations'][0]['agent'], 'news_verification')
        self.assertEqual(allowlist['violations'][0]['tool'], 'tools.compliance_tools.check_compliance')

    def test_pending_reports_do_not_become_failed_decisions_or_paired_scores(self):
        records=[]
        for system in ('baseline','multi_agent'):
            result=run_system(self.scenarios[0],system,MockClient())
            result.update(scenario_id=self.scenarios[0]['id'],repeat=1)
            records.append(result)
        summary=aggregate(records,1)
        row=summary['systems']['multi_agent']
        self.assertIsNone(row['correct_mean'])
        self.assertIsNone(row['pass_k'])
        self.assertIsNone(row['action_consistency'])
        self.assertEqual(row['failure_counts'],{})
        self.assertTrue(row['evaluation_pending'])
        self.assertEqual(summary['paired_comparisons'],{})

    def test_high_confidence_wrong_is_penalized_even_with_some_points(self):
        scenario=self.scenarios[0]
        decision={'news_label':'false','action':'borrow_interbank','amount':100,'confidence':0.9,'rationale':'Wrong borrowing.'}
        a=evaluate({'status':'completed','decision':decision},scenario)
        decision['confidence']=0.2
        b=evaluate({'status':'completed','decision':decision},scenario)
        self.assertLess(a['confidence_weighted_score'],b['confidence_weighted_score'])
        self.assertEqual(a['confidence_weighted_score'],-1.8)
        self.assertEqual(a['confidence']['bucket'], 4)
        self.assertAlmostEqual(a['confidence_brier_error'], 0.81)

    def test_report_signature_and_efficiency_metrics_are_recorded(self):
        result=run_system(self.scenarios[1], 'multi_agent', MockClient())
        self.assertIsInstance(result['metrics']['report_signature'], str)
        financial=result['metrics']['agent_telemetry']['financial_analyst']
        self.assertGreater(financial['steps'], 0)
        self.assertGreater(financial['step_efficiency'], 0)
        self.assertEqual(financial['tool_call_accuracy'], 1.0)

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
            self.assertEqual(len(lines),4)
            self.assertTrue(json.loads((output/'manifest.json').read_text())['mock'])
            with (output/'metrics.csv').open(newline='', encoding='utf-8') as stream:
                rows=list(csv.DictReader(stream))
            self.assertIn('financial_react_steps',rows[0])
            self.assertTrue(all(r['financial_react_steps']=='3' for r in rows if r['system']=='multi_agent'))
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
