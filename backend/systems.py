"""Shared baseline and multi-agent orchestration for CLI and dashboard."""
from copy import deepcopy
import time
from backend.llm_client import LLMClient
from backend.telemetry import TOOL_LOG
from backend.agents.main_agent import build_prompt, scenario_inputs
from backend.agents.output_schema import HermesBankDecision, parse_json_object
from backend.agents.news_verification import run_news_verification
from backend.agents.financial_analyst import run_financial_analyst
from backend.agents.risk_manager import run_risk_manager
from backend.agents.compliance_officer import run_compliance_officer
from backend.agents.crisis_coordinator import propose_strategy, authorize_action
from backend.agents.treasury_operations import run_treasury_operations
from tools.financial_tools import get_bank_financials
from tools.treasury_tools import TreasurySimulation
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
    if system not in ('baseline', 'multi_agent', 'multi_agent_no_compliance'):
        raise ValueError('Unknown system')
    ctx = RunContext(client or LLMClient(), system, callback)
    inputs = deepcopy(scenario_inputs(scenario))
    result = {'system': system, 'status': 'running', 'agents': {}, 'interventions': [],
              'execution_authorized': False, 'treasury': {'executed': False}}
    result['agents'] = ctx.agent_results
    start = time.monotonic()
    token = TOOL_LOG.set(ctx.tools)
    try:
        if system == 'baseline':
            ctx.role = 'baseline'
            raw = ctx.ask(build_prompt(inputs))
            result['proposed_decision'] = deepcopy(raw)
            result['decision'] = HermesBankDecision(**raw).model_dump()
            ctx.emit('main_agent', result['decision'], prompt=ctx.calls[-1]['prompt'], model=ctx.calls[-1].get('model'))
        else:
            reports = {}
            reports['news_verification'] = ctx.agent('news_verification', run_news_verification, inputs)
            # Missing financial data is an explicit report, not fabricated metrics.
            try:
                get_bank_financials(inputs)
                sufficient = True
            except (KeyError, TypeError, ValueError):
                sufficient = False
            if sufficient:
                reports['financial_analyst'] = ctx.agent('financial_analyst', run_financial_analyst, inputs)
                reports['risk_manager'] = ctx.agent('risk_manager', run_risk_manager, inputs,
                                                     financial_report=reports['financial_analyst'])
            else:
                for name in ('financial_analyst', 'risk_manager'):
                    reports[name] = {'agent': name, 'status': 'needs_review', 'reason': 'Required financial data are missing or invalid.'}
                    ctx.emit(name, reports[name])
            ctx.role = 'crisis_coordinator'
            raw = propose_strategy(inputs, reports, ctx.ask)
            result['proposed_decision'] = deepcopy(raw)
            reports['crisis_coordinator'] = {'agent': 'crisis_coordinator', 'proposal': deepcopy(raw)}
            ctx.emit('crisis_coordinator', raw, prompt=ctx.calls[-1]['prompt'], model=ctx.calls[-1].get('model'))
            guardrails = system != 'multi_agent_no_compliance'
            proposal = {'action': raw['action'], 'amount': raw['amount']}
            if guardrails:
                reports['compliance_officer'] = ctx.agent('compliance_officer', run_compliance_officer, inputs, proposals=[proposal])
                compliance = reports['compliance_officer']['report']['checks'][0]
            else:
                compliance = {'compliant': True}
                reports['compliance_officer'] = {'agent': 'compliance_officer', 'status': 'disabled_for_ablation'}
                ctx.emit('compliance_officer', reports['compliance_officer'])
            decision = deepcopy(raw)
            if guardrails:
                correct_label = reports['news_verification']['report']['news_label']
                if decision['news_label'] != correct_label:
                    result['interventions'].append({'rule': 'verified_news_label', 'original': decision['news_label'], 'replacement': correct_label})
                    decision['news_label'] = correct_label
                if not compliance['compliant'] or not sufficient:
                    result['interventions'].append({'rule': 'compliance_or_missing_data', 'blocked_proposal': proposal,
                                                     'violations': compliance.get('violations', [])})
                    reasons = list(compliance.get('violations', []))
                    if not sufficient:
                        reasons.append('Required financial data are missing')
                    decision.update(action='hold', amount=0.0, confidence=0.0, needs_review=True,
                                    rationale='Simulation deferred: ' + '; '.join(reasons))
            result['decision'] = decision
            book = TreasurySimulation()
            if decision['needs_review'] or decision['action'] == 'hold':
                treasury = {'agent': 'treasury_operations', 'status': 'deferred' if decision['needs_review'] else 'not_required',
                            'executed': False, 'simulated': True}
            else:
                try:
                    approval_id = authorize_action(book, inputs, decision, compliance, guardrails=guardrails)
                    result['execution_authorized'] = approval_id is not None
                    treasury = run_treasury_operations(inputs, book=book,
                        proposal={'action': decision['action'], 'amount': decision['amount']}, approval_id=approval_id)
                except (PermissionError, ValueError, KeyError, TypeError) as exc:
                    treasury = {'agent': 'treasury_operations', 'status': 'blocked', 'executed': False,
                                'simulated': True, 'reason': str(exc)}
                    result['interventions'].append({'rule': 'treasury_minimum_boundary', 'reason': str(exc)})
            reports['treasury_operations'] = treasury
            ctx.emit('treasury_operations', treasury)
            result['treasury'] = treasury
            result['agents'] = {name: {'status': 'completed', 'output': output} for name, output in reports.items()}
            result['note'] = 'Independent multi-agent decision, host approval policy, simulated execution only.'
        result['status'] = 'completed'
    except Exception as exc:
        result.update(status='error', error=str(exc))
        if ctx.role in ('baseline', 'crisis_coordinator') and ctx.last_object is not None:
            result.setdefault('proposed_decision', deepcopy(ctx.last_object))
        ctx.emit(ctx.role, {'status': 'error', 'error': str(exc)})
    finally:
        TOOL_LOG.reset(token)
    result['trace'] = ctx.trace
    result['telemetry'] = ctx.metrics(time.monotonic() - start)
    result['metrics'] = evaluate(result, scenario)
    result.update({key: result['metrics'][key] for key in ('score','max_score','normalized')})
    return result
