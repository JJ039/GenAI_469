# Bank Crisis: baseline versus multi-agent evaluation

A synthetic crisis experiment with a standalone LLM baseline and a specialist-report line ready for teammate integration. Financial actions are simulated in memory; no banking APIs
are connected. Scoring uses versioned answer keys that are never sent to models.

## Start the dashboard (Windows PowerShell)

From the repository root:

```powershell
python -m venv frontend/venv
.\frontend\venv\Scripts\python.exe -m pip install -r frontend/requirements.txt
.\frontend\venv\Scripts\python.exe frontend/server.py
```

In a second terminal:

```powershell
cd frontend
npm install
npm start
```

Open http://localhost:3000. Choose a scenario and click **Run LLM Agents**. The baseline has a final decision and score. The secondary line shows specialist reports and explicitly waits for teammate integration before producing a combined decision or executing anything. Dashboard results are saved under
`results/dashboard/`, including failures.

## Model and credentials

Default inference goes directly to OpenRouter: fixed model, explicit temperature,
no model tools, no hidden retries, and provider token/cost telemetry. Hermes is
not required for this path. Existing OpenRouter credentials saved by Hermes are
loaded from `%LOCALAPPDATA%/hermes/.env` or `~/.hermes/.env`. Alternatively copy
`backend/.env.example` to `backend/.env` and enter your key there. Environment
variables override files. Never commit your key.

```text
OPENROUTER_API_KEY=your_private_key
LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
LLM_TRANSPORT=openrouter
```

Set `LLM_MODEL` to an exact available OpenRouter model id. Both systems use the
same client/model/temperature. Unavailable models, missing credits, rate limits
and invalid JSON count as failures; the system does not silently change models.
Availability and quotas are controlled by your provider.

For manual dashboard testing only, `LLM_TRANSPORT=hermes` uses an isolated,
one-shot Hermes CLI call with toolsets disabled and project rules excluded.
`HERMES_EXECUTABLE` can specify its executable. Hermes temperature comes from its
installed configuration and is recorded as uncontrolled; the research batch runner
requires OpenRouter transport for reproducibility.

## Run the comparison

From the repository root, check the plumbing without external model calls:

```powershell
.\frontend\venv\Scripts\python.exe backend/scripts/run_evaluation.py --mock --runs 5
```

Mock outputs are watermarked **NOT LLM PERFORMANCE RESULTS**. They only check
that the integration and report generation work.

Run baseline evaluation and collect specialist reports (13 scenarios x 5 repeats x 2 lines = 130 runs; the report line is not yet a complete decision system):

```powershell
.\frontend\venv\Scripts\python.exe backend/scripts/run_evaluation.py --runs 5
```

A smaller real check:

```powershell
.\frontend\venv\Scripts\python.exe backend/scripts/run_evaluation.py --runs 1 --limit 2 --systems baseline multi_agent
```

Options include `--model`, `--temperature`, `--max-tokens`, `--reasoning-effort`, `--seed`, `--output`, and `--scenarios`.
`backend/scripts/run_baseline.py --runs 5` remains a baseline-only compatibility
command. Defaults use one model with temperature 0.1, maximum output budget 4096 and requested reasoning effort low. Jobs are shuffled with a
saved seed, and failures remain in reliability denominators.

Every timestamped output directory contains:

- `manifest.json`: model, temperature, rubric version, suite hash, integration status.
- `scenarios.json`: exact inputs and answer keys used for this run.
- `runs.jsonl`: raw model outputs, prompts, proposals, final decisions, approval
  outcomes, tool calls and per-agent diagnostics; flushed after each run.
- `metrics.csv`: decision quality, confidence penalties, safety and efficiency.
- `summary.json`: repeated-run consistency, pass^k, failure categories, paired
  scenario comparisons and bootstrap intervals.
- `report.md`: comparison table and reflective-analysis worksheet.
- `manual_review.csv`: blank human-rating fields for rationales and injection
  adherence. No subjective scores are invented automatically.

## Architecture and limitations

Baseline: raw scenario evidence -> one general-purpose agent with the bounded
union of specialist tools -> one LLM decision -> shared evaluator.

Specialist line: News Verification + Financial Analyst -> Risk Manager ->
Compliance reviews the Financial Analyst recommendation -> Treasury waits for
explicit approval. The combined decision stage is owned by a teammate and is
not implemented in this checkout. No specialist output is promoted to a final
system decision, no secondary score is assigned, and no approval is issued.
Decision-level ablation is deferred until integration.

The 13 version-2 scenarios have controlled evidence fixtures, canonical action
names, explicit missing-data expectations, and injection cases. News retrieval
is simulated, and source trust/verdict metadata are supplied by the scenario
designer, equally visible to the baseline. News Verification also validates
source IDs, independence groups, and trust metadata, and reports instruction-like
content as untrusted and ignored. Risk is a cash-coverage proxy, not a
probability of bank failure. Rules are synthetic funding limits, not a complete
banking regulatory model. See [experiment design](docs/EXPERIMENT.md) and
[agent interfaces](backend/agents/README.md). See [validation and pilot reflection](docs/VALIDATION.md) for observed successes, failures and limitations.

## Verification

```powershell
.\frontend\venv\Scripts\python.exe -B -m unittest discover -s frontend -p "test_*.py" -v
cd frontend
npm test -- --watchAll=false --runInBand
npm run build
```

The full live research study and human reflective analysis are separate from
regression checks. Do not report mock accuracy as evidence for the problem statement.

## Financial Analyst enhancement

The analyst uses bounded model-selected financial tools and validates cited
numeric claims before releasing a recommendation. The baseline has the same
specialist tool access through one shared agent loop, rather than separate role
prompts and handoffs. Both paths use the same model client and temperature. See
[design, metrics and offline benchmark](docs/FINANCIAL_ANALYST.md) and
[experiment design](docs/EXPERIMENT.md) for the comparison budget and limits.
Day-based phrases such as `7-day horizon`, `7-day period`, `7-day window`, and
`over 7 days` are treated as forecast-horizon metadata rather than funding
amounts, preventing valid recommendations from being blocked by their time frame.

## Latest verification

Run the local checks with:

```powershell
.\frontend\venv\Scripts\python.exe -B -m unittest discover -s frontend -p "test_*.py" -v
.\frontend\venv\Scripts\python.exe backend/scripts/check_financial_guardrails.py
```

The regression suite covers the baseline, specialist reports, API behavior,
prompt-injection handling, Treasury approval boundaries, and Financial Analyst
numeric grounding. The planted-error benchmark is synthetic detector evidence,
not a live-model hallucination rate. Treat real model runs separately and review
their saved `runs.jsonl` traces.

## Local inference with Ollama

Ollama runs the language model on this computer. Install and start Ollama, then
pull a local model with `ollama pull qwen3:1.7b` if it is not already installed.
Set the following in `backend/.env` and restart the Python backend:

```dotenv
LLM_TRANSPORT=ollama
LLM_MODEL=qwen3:1.7b
```

The client uses `http://127.0.0.1:11434/api/chat`, JSON output, a 16K context,
and disabled thinking. No inference API key is required. The installed small
model is a starting point for local testing; evaluate correctness before using
its outputs as research results. Compliance retrieval still needs its existing
regulatory corpus, embedding model and Qdrant setup.
For local batch evaluation, pass `--transport ollama --model qwen3:1.7b`.
