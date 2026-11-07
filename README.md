# Bank Crisis Multi-Agent System + Dashboard

A reproducible multi-agent LLM evaluation system for bank-run crisis scenarios, comparing a single-LLM baseline against a multi-agent coordinator with a React + Flask dashboard for visualizing results.

## Project Structure

```
bank-crisis-project/
├── backend/   # Agent evaluation engine
│   ├── agents/                          # main_agent.py, scorer.py, output_schema.py
│   ├── scenarios/scenarios/             # 10 JSON test scenarios
│   ├── scripts/                         # run_baseline.py, test_scenarios.py
│   ├── skills/route-model/              # Model routing skill
│   ├── config.yaml                      # Hermes model aliases
│   └── .env.example                     # API key template
├── frontend/                     # React + Flask visualization dashboard
│   ├── server.py                        # Flask API (port 5000)
│   ├── src/                             # React frontend (port 3000)
│   └── requirements.txt                 # Python dependencies
└── README.md
```

## Quick Start

### Dashboard agent flow

The dashboard runs two independent lines on the same scenario:

- **Baseline:** `main_agent.py` makes one standalone LLM decision. Its output is
  scored locally against the scenario answer key.
- **Secondary:** Financial Analyst, News Verification, Risk Manager and Compliance
  Officer produce their own reports using deterministic tools and LLM interpretation.
  Treasury Operations waits for explicit simulation approval. Specialists are registered in
  `SECONDARY_AGENTS` in `frontend/server.py`; each accepts `(scenario, llm_runner)`.

See [specialist agent documentation](backend/agents/README.md) for interfaces,
evidence fixtures, approval examples and simulation limitations. Crisis Coordinator
is intentionally not implemented.

Neither line receives the other line's outputs. They currently execute in sequence
within the background job, but are independent evaluations. Failures in one line
preserve results from the other. The dashboard displays them side by side with
actual prompts, outputs, and model names. The secondary line has no combined
final decision or comparison score yet. No banking action is executed, and the
answer key is never sent to a model.

From `frontend`, install dependencies and restart the server:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe server.py
```

Hermes must be installed and configured for the model identifiers in
`backend/agents/main_agent.py`. The runner checks its usual Windows install
location and PATH. For a different installation, set the executable before
starting the server:

```powershell
$env:HERMES_EXECUTABLE = "C:\path\to\hermes.exe"
```

Provider keys can be supplied through environment variables or `backend/.env`
(`OPENROUTER_API_KEY` and `GOOGLE_API_KEY`). Do not commit credentials.
The runner tries its second configured model if the first call fails. Each model
attempt has a 180-second timeout, so a stage may take several minutes.

Run the API integration checks without calling external models:

```powershell
cd frontend
.\venv\Scripts\python.exe -B -m unittest discover -p "test_*.py" -v
```

### 1. Install Hermes Agent
```bash
# Windows: download from https://hermes-agent.nousresearch.com
# Verify: hermes --version
```

### 2. Configure API Keys
```bash
cd backend
cp .env.example .env
# Edit .env and add OPENROUTER_API_KEY and GOOGLE_API_KEY
```

### 3. Install Hermes Config
```bash
cp config.yaml ~/.hermes/config.yaml
hermes config set model.aliases.free-gemini gemini/gemini-3.8-flash
hermes config set model.aliases.free-openrouter nvidia/nemotron-3-ultra-550b-a55b:free
```

### 4. Start the Dashboard

**Terminal 1 — Flask API:**
```bash
cd frontend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

**Terminal 2 — React Frontend:**
```bash
cd frontend
npm install
npm start
```

Open http://localhost:3000

### 5. Run Evaluations (CLI)
```bash
cd backend
python scripts/test_scenarios.py
# or
python scripts/run_baseline.py --runs 5 --output results/base
```

## Tech Stack

- **Agent Framework:** Hermes Agent (OpenRouter + Google AI Studio Gemini)
- **Models:** NVIDIA Nemotron 3 Ultra 550B (free via OpenRouter), Gemini 2.0 Flash (free tier)
- **Backend:** Flask (Python 3.11)
- **Frontend:** React 19 (Create React App)
- **Evaluation:** Per-scenario answer keys with scoring (ideal=3, acceptable=2, forbidden=-2)

## Metrics

- Decision quality (per-scenario score)
- Confidence-weighted score
- Safety violations (forbidden actions)
- Injection resistance
- Reliability (mean ± std across 5 runs)
- Efficiency (tokens / calls / time)

## License

MIT
EOF
echo "README CREATED"
