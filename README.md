# GenAI 469: Crisis decision agents

This project compares a baseline agent with a specialist multi-agent workflow across synthetic banking-crisis scenarios. The specialist workflow includes news verification, financial analysis, risk management, regulatory compliance, Treasury operations, and a coordinator that consolidates the reports. Financial actions are simulated; the project does not connect to live banking APIs or execute transactions.

## Requirements

- 64-bit Python 3.11 (recommended for the PyTorch and sentence-transformers dependencies)
- Node.js with npm
- [Ollama for Windows](https://ollama.com/download/windows)
- Access to the hosted Qdrant collection for Compliance RAG (Qdrant URL and API key)

Check installed Python versions in PowerShell:

```powershell
py -0p
```

If Python 3.11 is missing, install the 64-bit Python 3.11 release alongside any existing Python versions. Keep Python 3.14 if other projects use it; create this project's environment explicitly with `py -3.11`.

## Install Ollama and the language model

Install and start Ollama, then download the model used by the app:

```powershell
ollama pull qwen3:1.7b
ollama list
```

The first pull downloads the model to the local computer. Ollama must be running before launching the backend. The app uses Ollama at `http://127.0.0.1:11434`
## Configure the backend

Create `backend/.env` by copying `backend/.env.example`. Set the model and Qdrant values:

```dotenv
LLM_TRANSPORT=ollama
LLM_MODEL=qwen3:1.7b
LLM_MAX_TOKENS=4096
LLM_REASONING_EFFORT=low

QDRANT_URL=https://YOUR-CLUSTER-ENDPOINT
QDRANT_API_KEY=YOUR-QDRANT-API-KEY
QDRANT_COLLECTION=regulatory_corpus_v1
```

Keep `backend/.env` and the Qdrant API key private. Do not commit them. Ollama inference is local; the Qdrant credentials are used by regulatory retrieval.

## Install project dependencies

Run these commands from the repository root in PowerShell:

```powershell
py -3.11 -m venv frontend\venv
.\frontend\venv\Scripts\python.exe -m pip install --upgrade pip
.\frontend\venv\Scripts\python.exe -m pip install -r frontend\requirements.txt
```

The frontend requirements file also installs the backend and regulatory-corpus Python dependencies.

## Regulatory corpus and Qdrant

The Compliance Officer uses hybrid retrieval over the regulatory corpus: Qwen embeddings query the hosted Qdrant collection, BM25 retrieves keyword matches locally, and reciprocal-rank fusion combines results. The agent receives up to five combined passages with source and citation metadata. Embeddings use `Qwen/Qwen3-Embedding-0.6B`, which is separate from the Ollama chat model and is downloaded from Hugging Face on first use. It runs locally to embed documents during ingestion and queries during retrieval.

The PDFs and matching manifest entries belong in `backend/regulatory_corpus/pdfs/`. The manifest's curated context is prepended to each chunk before embedding. The collection owner ingests the corpus once; teammates with access to the same populated Qdrant collection do not need to ingest it again, but each computer downloads/runs the embedding model locally for retrieval.

If you are responsible for creating or refreshing the shared collection, from the repository root run:

```powershell
.\frontend\venv\Scripts\python.exe -m backend.regulatory_corpus.ingest
```

The first ingestion downloads the embedding model and computes vectors locally before uploading them to Qdrant. It can take a while, especially on CPU. Re-running skips unchanged PDFs. `--rebuild` deletes and recreates the configured collection; use it only when you intend to replace the whole collection.

See [Regulatory corpus setup](backend/regulatory_corpus/README.md) for PDF manifest, search, and ingestion details.

## Run the application

Open two PowerShell terminals at the repository root.

Terminal 1: start the Python backend:

```powershell
.\frontend\venv\Scripts\python.exe frontend\server.py
```

Terminal 2: install and start the React dashboard:

```powershell
cd frontend
npm install
npm start
```

Open <http://localhost:3000>, choose a scenario, and run the comparison. Dashboard results are saved under `results/dashboard/`.

## Run an evaluation from the command line

From the repository root, run one pass over a small scenario subset:

```powershell
.\frontend\venv\Scripts\python.exe -m backend.scripts.run_evaluation --runs 1 --limit 2 --systems baseline multi_agent --transport ollama --model qwen3:1.7b
```

For a 5-run evaluation over the suite, omit `--limit 2` and set `--runs 5`. Timestamped evaluation outputs are written under `results/evaluation/`. Real model results should be reviewed alongside the saved run traces; mock outputs, if used, are integration checks rather than model-performance results.

## Notes on interpretation

- The baseline is a single agent with a bounded set of tools. The multi-agent workflow has specialized reports and a coordinator consolidation stage.
- Compliance reports regulatory findings from retrieved evidence and keeps configured synthetic scenario limits distinct from regulatory findings. An undetermined regulatory result indicates the available evidence did not support a finding.
- Treasury operations are simulated and require host authorization; no live transaction is made.
- Scenario rules and answer keys are experimental fixtures, not a complete legal or banking compliance system.

For agent interfaces and workflow details, see [backend agent documentation](backend/agents/README.md). For the experiment design and evaluation rubric, see [experiment documentation](docs/EXPERIMENT.md).
