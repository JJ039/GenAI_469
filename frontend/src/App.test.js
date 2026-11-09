import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from './App';

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ scenarios: [{id: 'test.json', name: 'Test crisis'}] }) });
});
afterEach(() => jest.restoreAllMocks());

test('loads scenarios and enables a run only after selection', async () => {
  render(<App />);
  expect(screen.getByRole('heading', {name: /Compare crisis decisions/i})).toBeInTheDocument();
  const button = screen.getByRole('button', {name: /Run comparison/i});
  expect(button).toBeDisabled();
  await screen.findByRole('option', {name: 'Test crisis'});
  fireEvent.change(screen.getByRole('combobox'), {target: {value: 'test.json'}});
  expect(button).toBeEnabled();
});

test('shows a scenario load failure', async () => {
  global.fetch.mockRejectedValue(new Error('offline'));
  render(<App />);
  expect(await screen.findByText(/Could not load scenarios/i)).toBeInTheDocument();
});

test('renders formatted decision cards from run results', async () => {
  const decision = {news_label: 'false', action: 'hold', amount: 0, confidence: 0.5, rationale: 'Verified evidence supports waiting.'};
  global.fetch
    .mockResolvedValueOnce({ok: true, json: async () => ({scenarios: [{id: 'test.json', name: 'Test crisis'}]})})
    .mockResolvedValueOnce({ok: true, json: async () => ({task_id: '1', message: 'Started'})})
    .mockResolvedValue({ok: true, json: async () => ({status: 'completed', stage: 3, trace: [], result: {
      baseline: {status: 'completed', decision, score: 6.5, max_score: 7, normalized: 6.5/7},
      secondary: {status: 'completed', decision, proposed_decision: decision, agents: {}, score: 6.5, max_score: 7, normalized: 6.5/7}
    }})});
  render(<App />);
  await screen.findByRole('option', {name: 'Test crisis'});
  fireEvent.change(screen.getByRole('combobox'), {target: {value: 'test.json'}});
  fireEvent.click(screen.getByRole('button', {name: /Run comparison/i}));
  await waitFor(() => expect(screen.getAllByText('Hold position')).toHaveLength(2));
  expect(screen.getByRole('article', {name: 'Multi-agent system'})).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', {name: /Run comparison/i})).toBeEnabled());
});


test('offers separate readable views without exposing raw JSON on the overview', async () => {
  render(<App />);
  await screen.findByRole('option', {name: 'Test crisis'});
  fireEvent.click(screen.getByRole('button', {name: 'Metrics & safety'}));
  expect(screen.getByRole('heading', {name: 'Run comparison'})).toBeInTheDocument();
  expect(screen.getByRole('table')).toBeInTheDocument();
  expect(screen.getAllByText('Not reported')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', {name: 'Scenario inputs'}));
  expect(screen.getByText('Scenario evidence, in one place')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Agent activity'}));
  expect(screen.getByText('A clear view of every handoff')).toBeInTheDocument();
});

test('keeps configuration usable after a failed start', async () => {
  global.fetch
    .mockResolvedValueOnce({ok: true, json: async () => ({scenarios: [{id:'test.json', name:'Test crisis'}]})})
    .mockResolvedValueOnce({ok: false, json: async () => ({error: 'Provider unavailable'})});
  render(<App />);
  await screen.findByRole('option', {name: 'Test crisis'});
  fireEvent.change(screen.getByRole('combobox'), {target: {value: 'test.json'}});
  fireEvent.click(screen.getByRole('button', {name: /Run comparison/i}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Provider unavailable');
  expect(screen.getByRole('button', {name: /Run comparison/i})).toBeEnabled();
});


test('shows specialist reports as pending integration rather than a final decision', async () => {
  global.fetch
    .mockResolvedValueOnce({ok:true,json:async()=>({scenarios:[{id:'test.json',name:'Test crisis'}]})})
    .mockResolvedValueOnce({ok:true,json:async()=>({task_id:'1'})})
    .mockResolvedValue({ok:true,json:async()=>({status:'completed',stage:3,trace:[],result:{
      baseline:{status:'error',error:'Unavailable'},
      secondary:{status:'completed',decision_status:'awaiting_integration',note:'Combined decision awaits teammate integration.',agents:{}}
    }})});
  render(<App />);
  await screen.findByRole('option',{name:'Test crisis'});
  fireEvent.change(screen.getByRole('combobox'),{target:{value:'test.json'}});
  fireEvent.click(screen.getByRole('button',{name:/Run comparison/i}));
  expect(await screen.findByText('Specialist reports collected')).toBeInTheDocument();
  expect(screen.getByText('Combined decision awaits teammate integration.')).toBeInTheDocument();
  expect(screen.queryByText(/Crisis coordinator/i)).not.toBeInTheDocument();
});


test('makes financial grounding and tool observations inspectable', async () => {
  const output = {status:'needs_review',metrics:{funding_gap:120,forecast_7d_outflow:140,cash_runway_days:1},
    analysis_metrics:{react_steps:2,valid_tool_calls:1,requested_tool_calls:1,grounded_claim_rate:0},
    hallucination_check:{passed:false,flags:[{kind:'value_mismatch',metric:'funding_gap'}]},
    financial_claims:[],react_trace:[{step:1,action:{type:'tool_call',tool:'build_financial_report'}}]};
  global.fetch
    .mockResolvedValueOnce({ok:true,json:async()=>({scenarios:[{id:'test.json',name:'Test crisis'}]})})
    .mockResolvedValueOnce({ok:true,json:async()=>({task_id:'1'})})
    .mockResolvedValue({ok:true,json:async()=>({status:'completed',stage:3,
      trace:[{source:'financial_analyst',stage:'secondary',output}],result:{
        secondary:{status:'completed',decision_status:'awaiting_integration',agents:{financial_analyst:{output}}}
      }})});
  render(<App />);
  await screen.findByRole('option',{name:'Test crisis'});
  fireEvent.change(screen.getByRole('combobox'),{target:{value:'test.json'}});
  fireEvent.click(screen.getByRole('button',{name:/Run comparison/i}));
  await screen.findByText('Specialist reports collected');
  fireEvent.click(screen.getByRole('button',{name:'Agent activity'}));
  expect(screen.getByText('Financial verification')).toBeInTheDocument();
  expect(screen.getByText('Review needed')).toBeInTheDocument();
  expect(screen.getByText('Tool actions and observations')).toBeInTheDocument();
  expect(screen.getByText('value mismatch')).toBeInTheDocument();
});
