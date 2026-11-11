"""Shared baseline and multi-agent orchestration for CLI and dashboard."""
from copy import deepcopy
import time
from backend.llm_client import LLMClient
from backend.telemetry import TOOL_AGENT, TOOL_LOG
from backend.agents.main_agent import build_prompt, scenario_inputs
from backend.agents.output_schema import HermesBankDecision, parse_json_object
from backend.agents.news_verification import run_news_verification
from backend.agents.financial_analyst import run_financial_analyst
from backend.agents.risk_manager import run_risk_manager
from backend.agents.compliance_officer import run_compliance_officer
from backend.agents.treasury_operations import run_treasury_operations
from tools.financial_tools import get_bank_financials
from backend.evaluation import evaluate


class RunContext:
    def __init__(self, client, system, callback=None):
        self.client, self.system, self.callback = client, system, callback
        self.trace, self.calls, self.tools = [], [], []
        self.role = 'baseline' if system == 'baseline' else 'news_verification'
        self.last_object = None
        self.agent_results = {}

    def emit(self, source, output, **extra):
        entry = {'source': source, 'stage': 'baseline' if self.system == 'baseline' else 'secondary',
                 'line': self.system, 'output': deepcopy(output), **extra}
        self.trace.append(entry)
        if self.callback:
            self.callback(deepcopy(entry))

    def ask(self, prompt):
        self.last_object = None
        event = {'role': self.role, 'prompt': prompt}
        self.calls.append(event)
        start = time.monotonic()
        if self.callback:
            self.callback({'state': 'running', 'source': self.role, 'stage': 'baseline' if self.system == 'baseline' else 'secondary'})
        try:
            response = self.client.complete(prompt)
            event.update({k: v for k, v in response.items() if k != 'text'})
            event['raw_response'] = response['text']
            if not response['text'].strip():
                raise ValueError('Model returned no final text (finish_reason=' + str(response.get('finish_reason')) + '). Token usage is retained; check the reasoning/output budget.')
            parsed = parse_json_object(response['text'])
            self.last_object = parsed
            event['valid_json'] = True
            return parsed
        except Exception as exc:
            event['error'] = str(exc)
            event['valid_json'] = False
            raise
        finally:
            event['elapsed_seconds'] = time.monotonic() - start

    def agent(self, name, function, scenario, **kwargs):
        self.role = name
        TOOL_AGENT.set(name)
        output = function(scenario, llm_runner=self.ask, **kwargs)
        call = self.calls[-1] if self.calls and self.calls[-1]['role'] == name else {}
        self.agent_results[name] = {'status': 'completed', 'output': deepcopy(output)}
        self.emit(name, output, prompt=call.get('prompt'), model=call.get('model'))
        return output

    def metrics(self, elapsed):
        def total(key):
            values = [c.get(key) for c in self.calls]
            return sum(values) if values and all(v is not None for v in values) else None
        return {'llm_calls': len(self.calls), 'tool_calls': len(self.tools),
                'tool_validity': sum(t['valid'] for t in self.tools) / len(self.tools) if self.tools else None,
                'input_tokens': total('input_tokens'), 'output_tokens': total('output_tokens'),
                'cost_usd': total('cost_usd'), 'elapsed_seconds': elapsed,
                'calls': self.calls, 'tools': self.tools,
                'models_used': sorted({c['model'] for c in self.calls if c.get('model')}),
                'temperature': getattr(self.client, 'temperature', None),
                'transport': getattr(self.client, 'transport', 'injected_test_client'),
                'requested_max_tokens': getattr(self.client, 'max_tokens', None),
                'requested_reasoning_effort': getattr(self.client, 'reasoning_effort', None)}


def run_system(scenario, system='baseline', client=None, callback=None):
    if system not in ('baseline', 'multi_agent'):
        raise ValueError('Unknown system')
    ctx = RunContext(client or LLMClient(), system, callback)
    inputs = deepcopy(scenario_inputs(scenario))
    result = {'system': system, 'status': 'running', 'agents': {}, 'interventions': [],
              'execution_authorized': False, 'treasury': {'executed': False}}
    result['trace'] = ctx.trace
    start = time.monotonic()

    def log(source, output):
        ctx.trace.append({'source': source, 'stage': 'multi_agent', 'output': deepcopy(output)})
        if callback:
            callback({'state': 'running', 'source': source, 'stage': 'multi_agent'})

    def get_news_label(report):
        return report.get('report', {}).get('news_label', 'unverified')

    # --- Phase 1: Receive scenario, run News Verification ---
    news_verif = ctx.agent('news_verification', run_news_verification, inputs)
    log('news_verification', news_verif)
    news_label = get_news_label(news_verif)

    # --- Phase 2: Financial Analyst (skip if news_label == 'false') ---
    financial_report = None
    if news_label != 'false':
        financial_report = ctx.agent('financial_analyst', run_financial_analyst, inputs)
        log('financial_analyst', financial_report)
        liquidity_healthy = financial_report.get('metrics', {}).get('liquidity_healthy', True)
    else:
        # news_label == 'false': no need to check liquidity go straight to Compliance
        liquidity_healthy = False

    # --- Phase 3: Risk Manager (skip if liquidity not healthy) ---
    risk_report = None
    if liquidity_healthy:
        risk_report = ctx.agent('risk_manager', run_risk_manager, inputs,
                                financial_report=financial_report)
        log('risk_manager', risk_report)
        risk_level = risk_report.get('report', {}).get('current_risk', {}).get('risk_level', 'low')
    else:
        risk_level = 'low'

    # --- Phase 4: Compliance Officer (skip if risk != high) ---
    compliance_report = None
    if risk_level == 'high':
        proposals = []
        if financial_report:
            rec = financial_report.get('recommendation', {})
            if rec:
                proposals.append({'action': rec.get('recommendation'), 'amount': rec.get('amount', 0)})
        compliance_report = ctx.agent('compliance_officer', run_compliance_officer, inputs,
                                      proposals=proposals)
        log('compliance_officer', compliance_report)
        findings = compliance_report.get('report', {}).get('regulatory_findings', [])
        compliant = findings[0].get('finding', 'undetermined') if findings else 'undetermined'
    else:
        compliant = 'true'

    # --- Phase 5: Treasury Operations (skip if compliance == 'false') ---
    treasury_op = None
    if compliant != 'false':
        proposals = []
        if financial_report:
            rec = financial_report.get('recommendation', {})
            if rec:
                proposals.append({'action': rec.get('recommendation'), 'amount': rec.get('amount', 0)})
        treasury_op = ctx.agent('treasury_operations', run_treasury_operations, inputs,
                                proposal=proposals[0] if proposals else None,
                                approval_id='simulated_host_approval')
        log('treasury_operations', treasury_op)
    else:
        treasury_op = {'agent': 'treasury_operations', 'status': 'VETOED',
                       'executed': False,
                       'reason': 'Compliance officer returned non-compliant finding. Decision held. '
                                 'Human intervention raised.'}
        result['interventions'].append({'stage': 'compliance', 'rule': 'Compliance veto',
                                        'action': 'hold', 'amount': 0, 'rationale': 'Non-compliant proposal'})
        log('treasury_operations', treasury_op)

    # --- Phase 6: Assemble final decision and score ---
    result['treasury'] = treasury_op
    result['agents'] = {name: {'status': 'completed', 'output': output}
                        for name, output in {
                            'news_verification': news_verif,
                            'financial_analyst': financial_report,
                            'risk_manager': risk_report,
                            'compliance_officer': compliance_report,
                            'treasury_operations': treasury_op,
                        }.items() if output is not None}

    # Score using the shared evaluator
    result['trace'] = ctx.trace
    result['telemetry'] = ctx.metrics(time.monotonic() - start)
    result['metrics'] = evaluate(result, scenario)
    result.update({key: result['metrics'][key] for key in ('score', 'max_score', 'normalized')})
    result['status'] = 'completed'
    return result
