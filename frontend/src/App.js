import React, { useEffect, useState } from 'react';
import './App.css';

const API = 'http://localhost:5000';
const TABS = [
  { id: 'overview', label: 'Comparison', icon: 'grid' },
  { id: 'activity', label: 'Agent activity', icon: 'activity' },
  { id: 'metrics', label: 'Metrics & safety', icon: 'chart' },
  { id: 'scenario', label: 'Scenario inputs', icon: 'file' }
];
const AGENTS = [
  ['news_verification', 'News verification', 'Corroborates the news'],
  ['financial_analyst', 'Financial analyst', 'Examines liquidity'],
  ['risk_manager', 'Risk manager', 'Models the alternatives'],
  ['compliance_officer', 'Compliance officer', 'Checks the proposal'],
  ['treasury_operations', 'Treasury operations', 'Simulates approved actions']
];
const ACTIONS = { hold: 'Hold position', borrow_interbank: 'Interbank borrowing', draw_central_bank_facility: 'Central bank facility' };
const humanize = value => String(value || '').replace(/^scn_\d+_/, '').replace(/_/g, ' ').replace(/\.json$/, '');
const number = value => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('en-SG', { maximumFractionDigits: 2 }).format(value) : '?';
const percent = value => typeof value === 'number' ? `${Math.round(value * 100)}%` : '?';
const duration = value => typeof value === 'number' ? `${value.toFixed(1)}s` : '?';
const compact = value => typeof value !== 'number' ? '?' : Math.abs(value) >= 1000000 ? `${number(value / 1000000)}M` : number(value);
const yesNo = value => value == null ? '?' : value ? 'Yes' : 'No';

function Icon({ name, size = 18, ...props }) {
  const paths = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
    activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
    chart: <><path d="M4 3v17h17" /><path d="M8 15v-4m5 4V7m5 8V4" /></>,
    file: <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M8 13h8m-8 4h5" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    download: <><path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4" /></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z" /><path d="m8 12 3 3 5-6" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    alert: <><path d="m12 3 10 18H2zM12 9v4" /><path d="M12 17h.01" /></>,
    layers: <><path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5" /></>
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name] || paths.file}</svg>;
}

function Badge({ children, tone = 'neutral', dot = false }) {
  return <span className={`badge badge--${tone}`}>{dot && <span className="badge-dot" />}{children}</span>;
}
function RawDetails({ label = 'View raw output', value, text = false }) {
  if (value == null) return null;
  return <details className="raw-details"><summary>{label}</summary><pre>{text ? value : JSON.stringify(value, null, 2)}</pre></details>;
}
function Metric({ label, value, detail }) {
  return <div className="small-metric"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>;
}

function DecisionCard({ title, subtitle, run, variant, running, queued }) {
  const decision = run?.decision;
  const failed = run?.status === 'error';
  const reportsOnly = run?.decision_status === 'awaiting_integration';
  const status = failed ? 'Failed' : reportsOnly && run?.status === 'completed' ? 'Reports ready' : run?.status === 'completed' ? 'Complete' : running ? 'Running' : queued ? 'Queued' : 'Ready';
  const tone = failed ? 'danger' : run?.status === 'completed' ? 'success' : running ? 'active' : 'neutral';
  return <article className={`decision-card decision-card--${variant}`} aria-label={title}>
    <header className="decision-card-header"><div className="card-identity"><span className="system-icon"><Icon name={variant === 'baseline' ? 'file' : 'layers'} /></span><div><h3>{title}</h3><p>{subtitle}</p></div></div><Badge tone={tone} dot>{status}</Badge></header>
    {decision ? <>
      <div className="decision-score"><div><span className="eyebrow">Decision score</span><div className="score-value">{number(run.score)}<span> / {number(run.max_score)}</span></div></div><span className="score-percent">{percent(run.normalized)}<small>of maximum score</small></span></div>
      <div className="decision-action"><span className="eyebrow">Recommended action</span><h4>{ACTIONS[decision.action] || humanize(decision.action)}</h4><Badge tone={decision.needs_review ? 'warning' : 'neutral'}>{decision.needs_review ? 'Review required' : 'Decision ready'}</Badge></div>
      <div className="decision-facts"><Metric label="Funding amount" value={compact(decision.amount)} detail="Scenario units" /><Metric label="News assessment" value={<span className="text-capitalize">{decision.news_label}</span>} /><Metric label="Confidence" value={percent(decision.confidence)} /></div>
      <div className="confidence-track" aria-label={`Confidence ${percent(decision.confidence)}`}><span style={{ width: `${Math.max(0, Math.min(100, decision.confidence * 100))}%` }} /></div>
      <div className="rationale"><span className="eyebrow">Decision rationale</span><p>{decision.rationale}</p><details><summary>Read full reasoning</summary><p>{decision.rationale}</p></details></div>
    </> : <div className={`decision-empty ${failed ? 'decision-empty--error' : ''}`}>
      <span className={`empty-symbol ${running ? 'is-pulsing' : ''}`}><Icon name={failed ? 'alert' : running ? 'activity' : 'layers'} size={26} /></span>
      <h4>{failed ? 'This system could not finish' : reportsOnly ? 'Specialist reports collected' : running ? 'Analyzing the scenario' : queued ? 'Waiting for the baseline' : 'Ready for a scenario'}</h4>
      <p>{failed ? run.error : reportsOnly ? run.note : running ? 'The result will appear here as soon as this system finishes.' : 'Choose a crisis scenario above to compare the two approaches.'}</p>
    </div>}
    <footer className="decision-card-footer"><Icon name={variant === 'baseline' ? 'file' : 'shield'} size={15} /><span>{variant === 'baseline' ? 'Standalone LLM ? same raw evidence' : 'Specialist reports ? awaiting integration'}</span></footer>
  </article>;
}

function reportFacts(source, output) {
  const report = output?.report || {};
  if (source === 'financial_analyst') return [
    ['Funding gap', compact(output?.metrics?.funding_gap)], ['Forecast outflow', compact(output?.metrics?.forecast_7d_outflow)], ['Cash runway', output?.metrics?.cash_runway_days == null ? 'Not available' : `${number(output.metrics.cash_runway_days)} days`]
  ];
  if (source === 'news_verification') return [['News label', humanize(report.news_label)], ['Supporting sources', number(report.evidence?.independent_supporting_sources)], ['Refuting sources', number(report.evidence?.independent_refuting_sources)]];
  if (source === 'risk_manager') return [['Risk level', humanize(report.current_risk?.risk_level)], ['Risk proxy', number(report.current_risk?.risk_score)], ['Candidates assessed', number(report.candidate_outcomes?.length)]];
  if (source === 'compliance_officer') return [['Proposals checked', number(report.checks?.length)], ['Compliant', report.checks?.length ? yesNo(report.checks.every(check => check.compliant)) : '?'], ['Authorization granted', 'No ? host approval required']];
  if (source === 'treasury_operations') return [['Status', humanize(output?.status)], ['Executed', yesNo(output?.executed)], ['Amount', compact(output?.receipt?.amount)]];
  if (source === 'main_agent') return [['Action', ACTIONS[output?.action] || humanize(output?.action)], ['Amount', compact(output?.amount)], ['Confidence', percent(output?.confidence)]];
  return [];
}

function Activity({ trace, selectedSource, onSelect }) {
  const entries = trace.filter(entry => entry.stage !== 'observe');
  const sources = [...new Set(entries.map(entry => entry.source))];
  const source = selectedSource || sources[sources.length - 1];
  const entry = [...entries].reverse().find(item => item.source === source);
  const output = entry?.output;
  const summary = output?.interpretation?.summary || output?.recommendation?.rationale || output?.rationale || output?.reason;
  return <div className="activity-layout"><div className="panel activity-list"><div className="panel-heading"><h3>Run timeline</h3><Badge>{entries.length} reports</Badge></div>
    {sources.length ? sources.map((name, index) => {
      const last = [...entries].reverse().find(item => item.source === name);
      const failed = last?.output?.status === 'error';
      return <button key={name} className={`activity-row ${source === name ? 'is-selected' : ''}`} onClick={() => onSelect(name)}><span className={`activity-marker ${failed ? 'is-error' : ''}`}>{failed ? <Icon name="alert" size={14} /> : <Icon name="check" size={14} />}</span><span><strong>{AGENTS.find(([key]) => key === name)?.[1] || humanize(name)}</strong><small>{name === 'main_agent' || name === 'baseline' ? 'Baseline' : 'Multi-agent system'} ? Report {index + 1}</small></span><Icon name="arrow" size={15} /></button>;
    }) : <div className="panel-empty"><Icon name="activity" size={28} /><p>Agent reports will appear here during a run.</p></div>}
  </div><div className="panel report-panel">
    {entry ? <><div className="panel-heading"><div><span className="eyebrow">Agent report</span><h3>{AGENTS.find(([key]) => key === source)?.[1] || humanize(source)}</h3></div><Badge tone={output?.status === 'error' ? 'danger' : 'success'}>{output?.status === 'error' ? 'Failed' : 'Received'}</Badge></div>
      {entry.model && <p className="model-label">Model <code>{entry.model}</code></p>}
      {output?.error && <div className="inline-error" role="alert">{output.error}</div>}
      <div className="report-facts">{reportFacts(source, output).map(([label, value]) => <Metric key={label} label={label} value={value || '?'} />)}</div>
      {summary && <div className="report-summary"><h4>Interpretation</h4><p>{summary}</p></div>}
      <RawDetails label="Full report data" value={output} />
      <RawDetails label="Prompt sent to the model" value={entry.prompt} text />
      <RawDetails label="Stage input" value={entry.input} />
    </> : <div className="panel-empty large"><Icon name="file" size={34} /><h3>A clear view of every handoff</h3><p>Select an agent report to inspect its findings, model prompt, and full output.</p></div>}
  </div></div>;
}

function MetricsView({ result }) {
  const baseline = result?.baseline;
  const secondary = result?.secondary;
  const rows = [
    ['Decision score', run => run?.score == null ? '?' : `${number(run.score)} / ${number(run.max_score)}`],
    ['Entire decision correct', run => yesNo(run?.metrics?.correct)],
    ['News label correct', run => yesNo(run?.metrics?.news_label_correct)],
    ['Amount in range', run => yesNo(run?.metrics?.amount_in_range)],
    ['Valid output format', run => yesNo(run?.metrics?.format_valid)],
    ['Confidence-weighted score', run => number(run?.metrics?.confidence_weighted_score)],
    ['Elapsed time', run => duration(run?.telemetry?.elapsed_seconds)],
    ['LLM calls', run => number(run?.telemetry?.llm_calls)],
    ['Tool calls', run => number(run?.telemetry?.tool_calls)],
    ['Input tokens', run => number(run?.telemetry?.input_tokens)],
    ['Output tokens', run => number(run?.telemetry?.output_tokens)],
    ['Reported cost (USD)', run => run?.telemetry?.cost_usd == null ? 'Not reported' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(run.telemetry.cost_usd)],
    ['Unsafe proposal violations', run => number(run?.metrics?.proposed_violation_count)]
  ];
  const interventions = secondary?.interventions || [];
  return <div className="metrics-layout"><section className="panel"><div className="panel-heading"><div><span className="eyebrow">Same scenario ? same rubric</span><h3>Run comparison</h3></div></div><div className="table-scroll"><table className="comparison-table"><thead><tr><th scope="col">Metric</th><th scope="col">Baseline LLM</th><th scope="col">Multi-agent</th></tr></thead><tbody>{rows.map(([label, formatter]) => <tr key={label}><th scope="row">{label}</th><td>{formatter(baseline)}</td><td>{formatter(secondary)}</td></tr>)}</tbody></table></div><p className="table-note">Specialist decision scores await teammate integration. A dash means no result is available; missing usage is not zero.</p></section>
    <section className="panel safety-panel"><div className="panel-heading"><span className="section-icon"><Icon name="shield" /></span><h3>Safety & execution</h3></div><div className="safety-number">{number(secondary?.metrics?.guardrail_interventions)}<span>guardrail interventions</span></div><div className="safety-facts"><div><span>Execution mode</span><Badge>Simulation only</Badge></div><div><span>Treasury status</span><strong>{humanize(secondary?.treasury?.status) || 'Awaiting results'}</strong></div><div><span>Host authorization</span><strong>{yesNo(secondary?.execution_authorized)}</strong></div></div>
      {interventions.length ? <div className="intervention-list">{interventions.map((item, index) => <details key={index}><summary>{humanize(item.rule)}</summary><pre>{JSON.stringify(item, null, 2)}</pre></details>)}</div> : <p className="muted-note">{secondary ? 'No guardrail interventions were recorded in this run.' : 'Checks and any blocked proposals appear after a run.'}</p>}
      <RawDetails label="Simulated treasury receipt" value={secondary?.treasury} />
      <p className="safety-footnote"><Icon name="shield" size={15} />No real funds are moved.</p>
    </section></div>;
}

function ScenarioView({ result }) {
  const scenario = result?.scenario_input;
  if (!scenario) return <div className="panel panel-empty large"><Icon name="file" size={34} /><h3>Scenario evidence, in one place</h3><p>Run a scenario to inspect the exact news content, financials, and rules used by both systems.</p></div>;
  return <div className="scenario-layout"><section className="panel"><div className="panel-heading"><h3>News content</h3><Badge tone="warning">Untrusted text</Badge></div><blockquote className="news-quote">{scenario.trigger}</blockquote><div className="panel-heading evidence-heading"><h3>Controlled evidence</h3><Badge>{scenario.news_sources?.length || 0} sources</Badge></div>{scenario.news_sources?.length ? scenario.news_sources.map((source, index) => <div className="evidence-card" key={`${source.source_id}-${index}`}><div><strong>{humanize(source.source_id)}</strong><Badge>{humanize(source.verdict)}</Badge></div><p>{source.content}</p><small>Group: {source.independence_group} ? {source.trusted ? 'Trusted fixture' : 'Untrusted fixture'}</small></div>) : <p className="muted-note">No independent source records were supplied. The news remains unverified.</p>}</section><div className="scenario-side"><section className="panel"><div className="panel-heading"><h3>Bank financials</h3></div><dl className="input-list">{Object.entries(scenario.financials || {}).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value == null ? 'Not supplied' : number(value)}</dd></div>)}</dl><p className="table-note">Monetary values use the scenario?s units.</p></section><section className="panel"><div className="panel-heading"><h3>Simulation rules</h3></div><dl className="input-list">{Object.entries(scenario.regulations || {}).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{Array.isArray(value) ? value.map(humanize).join(', ') : typeof value === 'boolean' ? yesNo(value) : number(value)}</dd></div>)}</dl></section></div></div>;
}

export default function App() {
  const [scenarios, setScenarios] = useState([]);
  const [selected, setSelected] = useState('');
  const [connection, setConnection] = useState('loading');
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [trace, setTrace] = useState([]);
  const [currentStage, setCurrentStage] = useState(0);
  const [taskId, setTaskId] = useState(null);
  const [starting, setStarting] = useState(false);
  const [stageMessage, setStageMessage] = useState('');
  const [stageElapsed, setStageElapsed] = useState(0);
  const [tab, setTab] = useState('overview');
  const [selectedSource, setSelectedSource] = useState(null);
  const [runLabel, setRunLabel] = useState('');
  const busy = starting || Boolean(taskId);

  useEffect(() => {
    let active = true;
    fetch(`${API}/api/scenarios`).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      return data;
    }).then(data => { if (active) { setScenarios(data.scenarios || []); setConnection('connected'); } })
      .catch(() => { if (active) { setConnection('error'); setError('Could not load scenarios. Check that the agent server is running.'); } });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!taskId) return undefined;
    let active = true;
    let timer;
    const poll = async () => {
      try {
        const response = await fetch(`${API}/api/task/${taskId}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'The run could not be retrieved.');
        if (!active) return;
        setCurrentStage(data.stage || 0);
        setTrace(data.trace || []);
        setStageMessage(data.message || 'Waiting for a model response.');
        setStageElapsed(data.elapsed_seconds || 0);
        if (data.result && Object.keys(data.result).length) setResult(data.result);
        if (data.status === 'completed' || data.status === 'error') {
          setTaskId(null);
          if (data.status === 'error') setError(data.error || 'Both systems could not finish.');
        } else timer = setTimeout(poll, 750);
      } catch (failure) {
        if (active) { setError(failure.message); setTaskId(null); }
      }
    };
    timer = setTimeout(poll, 500);
    return () => { active = false; clearTimeout(timer); };
  }, [taskId]);

  const runScenario = async () => {
    if (!selected || busy) return;
    setStarting(true); setError(null); setResult(null); setTrace([]); setCurrentStage(1);
    setStageMessage('Starting the baseline comparison.'); setStageElapsed(0);
    setRunLabel(humanize(scenarios.find(item => item.id === selected)?.name || selected));
    setTab('overview'); setSelectedSource(null);
    try {
      const response = await fetch(`${API}/api/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario: selected }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not start the comparison.');
      setTaskId(data.task_id); setStageMessage(data.message || 'Comparison started.');
    } catch (failure) { setError(failure.message); }
    finally { setStarting(false); }
  };
  const exportRun = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `crisis-comparison-${(result.scenario || 'run').replace(/\.json$/, '')}.json`; link.click(); URL.revokeObjectURL(url);
  };
  const baseline = result?.baseline;
  const secondary = result?.secondary;
  const stageNames = ['Baseline LLM', 'Specialist team', 'Shared evaluation'];
  const completedStages = [Boolean(baseline && baseline.status !== 'running'), Boolean(secondary && secondary.status !== 'running'), Boolean(secondary && !busy)];
  const openAgent = source => { setSelectedSource(source); setTab('activity'); };

  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#main-content" aria-label="CrisisLab home"><span className="brand-mark"><Icon name="layers" size={23} /></span><span>Crisis<span className="brand-light">Lab</span><small>DECISION INTELLIGENCE</small></span></a><div className="sidebar-group"><p className="nav-label">WORKSPACE</p><nav aria-label="Dashboard views">{TABS.map(item => <button key={item.id} className={`nav-item ${tab === item.id ? 'is-active' : ''}`} aria-current={tab === item.id ? 'page' : undefined} onClick={() => setTab(item.id)}><Icon name={item.icon} /><span>{item.label}</span>{tab === item.id && <span className="nav-active-dot" />}</button>)}</nav></div><div className="sidebar-footer"><span className="protocol-icon"><Icon name="shield" size={21} /></span><strong>A controlled experiment</strong><p>One scenario. Two independent decision systems.</p><span className="protocol-version">Protocol v2 <span>?</span> {scenarios.length || '?'} scenarios</span></div></aside>
    <div className="workspace"><header className="workspace-bar"><div className="breadcrumb">Workspace <span>/</span> Crisis evaluation</div><div className="workspace-status"><span className={`connection-dot connection-dot--${connection}`} />{connection === 'connected' ? 'API connected' : connection === 'error' ? 'Server unavailable' : 'Connecting'}<span className="bar-divider" /><Icon name="shield" size={14} />Simulation only</div></header>
      <main id="main-content" className="main-content"><header className="page-header"><div><span className="eyebrow">BASELINE VS. MULTI-AGENT</span><h1>Compare crisis decisions</h1><p>A shared scenario. A clear view of how each system responds.</p></div><button className="button button--secondary export-button" onClick={exportRun} disabled={!result || busy}><Icon name="download" size={16} />Export run</button></header>
        <section className="run-control" aria-label="Run configuration"><div className="scenario-select"><label htmlFor="scenario-select">Crisis scenario <span>{scenarios.length} available</span></label><select id="scenario-select" value={selected} onChange={event => setSelected(event.target.value)} disabled={busy || connection !== 'connected'}><option value="">Choose a scenario to evaluate</option>{scenarios.map(item => <option key={item.id} value={item.id}>{humanize(item.name)}</option>)}</select></div><div className="run-control-note"><Icon name="layers" size={20} /><span>Same evidence.<br /><strong>Same evaluation rubric.</strong></span></div><button className="button button--primary" onClick={runScenario} disabled={!selected || busy}>{busy ? <span className="spinner" /> : <Icon name="arrow" size={18} />}{busy ? 'Comparison running' : 'Run comparison'}</button></section>
        {error && <div className="error-banner" role="alert"><Icon name="alert" size={20} /><div><strong>We couldn?t complete that request</strong><p>{error}</p></div></div>}
        {(busy || result) && <section className="run-progress" aria-label="Run progress"><ol>{stageNames.map((label, index) => <li key={label} className={completedStages[index] ? 'is-complete' : busy && currentStage === index + 1 ? 'is-current' : ''}><span>{completedStages[index] ? <Icon name="check" size={13} /> : String(index + 1).padStart(2, '0')}</span>{label}</li>)}</ol><div className="run-live-message" aria-live="polite">{busy ? <><span className="live-dot" />{stageMessage}<span className="elapsed">{stageElapsed}s</span></> : <><Icon name="check" size={14} />{error ? 'Run finished with errors' : secondary?.decision_status === 'awaiting_integration' ? 'Baseline and specialist reports collected' : 'Comparison complete'}</>}</div></section>}
        <div className="view-heading"><div><h2>{TABS.find(item => item.id === tab)?.label}</h2>{runLabel ? <p>Results for <strong>{runLabel}</strong></p> : <p>{tab === 'overview' ? 'Two independent approaches to the same crisis.' : 'Inspect the evidence behind every decision.'}</p>}</div><Badge>{tab === 'overview' ? 'Independent systems' : tab === 'activity' ? 'Recorded handoffs' : tab === 'metrics' ? 'Shared rubric' : 'Controlled evidence'}</Badge></div>
        {tab === 'overview' && <><div className="decision-grid"><DecisionCard title="Baseline LLM" subtitle="A single decision-making model" variant="baseline" run={baseline} running={busy && currentStage === 1} /><DecisionCard title="Multi-agent system" subtitle="Independent specialist reports" variant="multi" run={secondary} running={busy && currentStage === 2} queued={busy && currentStage === 1} /></div>
          <div className="overview-stats"><div className="overview-stat"><span className="stat-icon"><Icon name="clock" /></span><div><span>Run latency</span><strong>{duration(baseline?.telemetry?.elapsed_seconds)} <small>vs</small> {duration(secondary?.telemetry?.elapsed_seconds)}</strong><small>Baseline / multi-agent</small></div></div><div className="overview-stat"><span className="stat-icon"><Icon name="activity" /></span><div><span>Model calls</span><strong>{number(baseline?.telemetry?.llm_calls)} <small>vs</small> {number(secondary?.telemetry?.llm_calls)}</strong><small>Baseline / multi-agent</small></div></div><div className="overview-stat"><span className="stat-icon"><Icon name="shield" /></span><div><span>Guardrail interventions</span><strong>{number(secondary?.metrics?.guardrail_interventions)}</strong><small>Multi-agent system</small></div></div></div>
          <section className="panel pipeline-panel"><div className="panel-heading"><div><span className="eyebrow">THE SPECIALIST LINE</span><h3>Evidence and specialist recommendations</h3></div><button className="text-button" onClick={() => setTab('activity')}>View activity <Icon name="arrow" size={15} /></button></div><div className="agent-pipeline">{AGENTS.map(([key, title, description], index) => { const entry = [...trace].reverse().find(item => item.source === key); const failed = entry?.output?.status === 'error'; return <button key={key} className={`pipeline-agent ${entry ? failed ? 'has-error' : 'has-report' : ''}`} onClick={() => openAgent(key)} aria-label={`Inspect ${title}`}><span className="pipeline-number">{entry && !failed ? <Icon name="check" size={15} /> : String(index + 1).padStart(2, '0')}</span><strong>{title}</strong><small>{description}</small><span className="pipeline-state">{entry ? failed ? 'Failed' : 'Report available' : busy ? 'Waiting' : 'Not started'}</span></button>; })}</div></section></>}
        {tab === 'activity' && <Activity trace={trace} selectedSource={selectedSource} onSelect={setSelectedSource} />}
        {tab === 'metrics' && <MetricsView result={result} />}
        {tab === 'scenario' && <ScenarioView result={result} />}
        <footer className="page-footer"><span><Icon name="shield" size={14} />All financial actions are simulated.</span><span>Evidence ? decisions ? accountability</span></footer>
      </main>
    </div>
  </div>;
}
