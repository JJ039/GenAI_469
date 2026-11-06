# Bank Crisis Multi-Agent System + Dashboard

A reproducible multi-agent LLM evaluation system for bank-run crisis scenarios, comparing a single-LLM baseline against a multi-agent coordinator with a React + Flask dashboard for visualizing results.

## Project Structure

```
bank-crisis-project/
├── hermes-openrouter-gemini-cascade/   # Agent evaluation engine
│   ├── agents/                          # main_agent.py, scorer.py, output_schema.py
│   ├── scenarios/scenarios/             # 10 JSON test scenarios
│   ├── scripts/                         # run_baseline.py, test_scenarios.py
│   ├── skills/route-model/              # Model routing skill
│   ├── config.yaml                      # Hermes model aliases
│   └── .env.example                     # API key template
├── agent-dashboard/                     # React + Flask visualization dashboard
│   ├── server.py                        # Flask API (port 5000)
│   ├── src/                             # React frontend (port 3000)
│   └── requirements.txt                 # Python dependencies
└── README.md
```

## Quick Start

### 1. Install Hermes Agent
```bash
# Windows: download from https://hermes-agent.nousresearch.com
# Verify: hermes --version
```

### 2. Configure API Keys
```bash
cd hermes-openrouter-gemini-cascade
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
cd agent-dashboard
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

**Terminal 2 — React Frontend:**
```bash
cd agent-dashboard
npm install
npm start
```

Open http://localhost:3000

### 5. Run Evaluations (CLI)
```bash
cd hermes-openrouter-gemini-cascade
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