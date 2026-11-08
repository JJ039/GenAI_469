import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from './App';

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ scenarios: [{id: 'test.json', name: 'Test crisis'}] }) });
});
afterEach(() => jest.restoreAllMocks());

test('loads scenarios and enables a run only after selection', async () => {
  render(<App />);
  expect(screen.getByRole('heading', {name: /Bank Agent Dashboard/i})).toBeInTheDocument();
  const button = screen.getByRole('button', {name: /Run LLM Agents/i});
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

test('displays the baseline and coordinated final decision after polling', async () => {
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
  fireEvent.click(screen.getByRole('button', {name: /Run LLM Agents/i}));
  expect(await screen.findByRole('heading', {name: 'Final decision'})).toBeInTheDocument();
  expect(screen.getByRole('heading', {name: 'Multi-agent system'})).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', {name: /Run LLM Agents/i})).toBeEnabled());
});
