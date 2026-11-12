"""Shared baseline and multi-agent orchestration for CLI and dashboard."""
from copy import deepcopy
import time
from backend.llm_client import LLMClient
from backend.telemetry import TOOL_AGENT, TOOL_LOG
from backend.agents.main_agent import scenario_inputs
from backend.agents.baseline_agent import run_baseline_agent
from backend.agents.output_schema import HermesBankDecision, parse_json_object
from backend.agents.news_verification import run_news_verification
from backend.agents.financial_analyst import run_financial_analyst
from backend.agents.risk_manager import run_risk_manager
from backend.agents.compliance_officer import run_compliance_officer
from backend.agents.treasury_operations import run_treasury_operations
from tools.financial_tools import get_bank_financials
from backend.evaluation import evaluate
from backend.agents.crisis_coordinator import build_team_report


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
    result['agents'] = ctx.agent_results
    start = time.monotonic()
    log_token = TOOL_LOG.set(ctx.tools)
    agent_token = TOOL_AGENT.set(ctx.role)
    try:
        if system == 'baseline':
            ctx.role = 'baseline'
            TOOL_AGENT.set('baseline')
            baseline_output = run_baseline_agent(inputs, llm_runner=ctx.ask)
            raw = baseline_output['decision']
            result['baseline_agent'] = baseline_output
            result['analysis_metrics'] = deepcopy(baseline_output['analysis_metrics'])
            result['proposed_decision'] = deepcopy(raw)
            result['decision'] = HermesBankDecision(**raw).model_dump()
            ctx.emit('main_agent', result['decision'], prompt=ctx.calls[-1]['prompt'], model=ctx.calls[-1].get('model'))
        else:
            reports = {}
            reports['news_verification'] = ctx.agent('news_verification', run_news_verification, inputs)
            # Missing financial data is an explicit report, not fabricated metrics.
            TOOL_AGENT.set('orchestrator')
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
            # Risk Manager hand-off: Compliance reviews the risk-compared candidate
            # outcomes (lowest risk first). The Risk Manager has already taken the
            # Financial Analyst recommendation as an input; fall back to that
            # recommendation only if the risk hand-off produced no proposals.
            risk = reports.get('risk_manager', {})
            proposals = [deepcopy(p) for p in risk.get('compliance_handoff', {}).get('proposals', [])]
            if not proposals:
                recommendation = reports.get('financial_analyst', {}).get('recommendation')
                if recommendation:
                    proposals = [{'action': recommendation['recommendation'], 'amount': recommendation['amount']}]
            reports['compliance_officer'] = ctx.agent(
                'compliance_officer', run_compliance_officer, inputs, proposals=proposals)
            compliance = reports['compliance_officer']['report']
            findings = compliance.get('regulatory_findings', [])
            checks = compliance.get('synthetic_checks', [])
            proposal = proposals[0] if proposals else None
            blockers = []
            compliance_basis = 'unavailable'
            if proposal is None:
                blockers.append('No validated financial recommendation is available.')
            else:
                matching_checks = [check for check in checks if check.get('proposal') == proposal]
                matching_findings = [finding for finding in findings if finding.get('proposal') == proposal]
                scenario_limits_passed = bool(matching_checks) and all(
                    check.get('compliant') is True for check in matching_checks
                )
                if not scenario_limits_passed:
                    blockers.append('Proposal did not pass the simulation compliance checks.')
                # A supported regulatory prohibition remains a hard blocker. When
                # corpus retrieval or interpretation is indeterminate, fall back
                # to the explicit synthetic scenario limits, without labeling that
                # result as regulatory clearance.
                prohibited = [item for item in matching_findings
                              if item.get('finding') == 'non_compliant']
                supported_clearance = (len(matching_findings) == 1
                                       and matching_findings[0].get('finding') == 'compliant'
                                       and not matching_findings[0].get('missing_facts'))
                if prohibited:
                    for finding in prohibited:
                        blockers.append('Regulatory review non_compliant: '
                                        + finding.get('rationale', 'A cited regulatory prohibition was found.'))
                    compliance_basis = 'regulatory_prohibition'
                elif supported_clearance:
                    compliance_basis = 'regulatory_corpus'
                elif scenario_limits_passed:
                    compliance_basis = 'scenario_limits_only'
                else:
                    compliance_basis = 'scenario_limits_failed'
            for reason in blockers:
                result['interventions'].append({
                    'stage': 'compliance', 'rule': 'Compliance review required',
                    'action': 'hold', 'amount': 0, 'rationale': reason})
            # Treasury can report preparation blockers for every scenario.
            # Only a cleared candidate is forwarded, and authorization remains host-issued.
            reports['treasury_operations'] = ctx.agent(
                'treasury_operations', run_treasury_operations, inputs,
                proposal=proposal if not blockers else None)
            result['compliance_blockers'] = blockers
            result['treasury'] = reports['treasury_operations']
            result['agents'] = {name: {'status': 'completed', 'output': output} for name, output in reports.items()}
            team_report = build_team_report(reports, proposal, blockers,
                                            compliance_basis=compliance_basis)
            result['report'] = team_report
            result['compliance_basis'] = compliance_basis
            result['decision'] = team_report['decision']
            result['decision_status'] = 'needs_review' if team_report['decision']['needs_review'] else 'decided'
            result['note'] = team_report['summary']
            ctx.emit('crisis_coordinator', {'agent': 'crisis_coordinator',
                     'status': result['decision_status'], 'report': team_report,
                     'interpretation': {'summary': team_report['summary']}})
        result['status'] = 'completed'
    except Exception as exc:
        result.update(status='error', error=str(exc))
        if ctx.role == 'baseline' and ctx.last_object is not None:
            result.setdefault('proposed_decision', deepcopy(ctx.last_object))
        ctx.emit(ctx.role, {'status': 'error', 'error': str(exc)})
    finally:
        TOOL_AGENT.reset(agent_token)
        TOOL_LOG.reset(log_token)
    if system != 'baseline' and 'decision_status' not in result:
        result['decision_status'] = 'failed'
    result['trace'] = ctx.trace
    result['telemetry'] = ctx.metrics(time.monotonic() - start)
    result['metrics'] = evaluate(result, scenario)
    result.update({key: result['metrics'][key] for key in ('score','max_score','normalized')})
    return result
