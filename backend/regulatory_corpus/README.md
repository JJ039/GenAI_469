# Regulatory corpus RAG

This module chunks the official PDFs in `pdfs/`, prepends the curated source context from `pdfs/manifest.json` before embedding, and writes vectors and citation metadata directly to Qdrant Cloud. Embeddings use `Qwen/Qwen3-Embedding-0.6B`; retrieval can optionally rerank results with the class notebook's cross-encoder. It does not make legal determinations or authorize actions.

## Setup

From the repository root in Windows PowerShell:

```powershell
python -m venv frontend\venv
.\frontend\venv\Scripts\python.exe -m pip install --upgrade pip
.\frontend\venv\Scripts\python.exe -m pip install -r backend/regulatory_corpus/requirements.txt
```

Create `.env` in the repository root (next to `.gitignore`) and add the endpoint and API key from Qdrant Cloud:

```env
QDRANT_URL=https://YOUR-CLUSTER-ENDPOINT
QDRANT_API_KEY=YOUR-QDRANT-API-KEY
QDRANT_COLLECTION=regulatory_corpus_v1
```

Keep `.env` private; it is ignored by Git. The Qdrant collection is created automatically with 1024-dimensional cosine vectors on first connection. Do not put the API key in source code or commit it.

## Ingest the PDFs

Add official PDFs to `pdfs/` and matching entries to `pdfs/manifest.json`. Manifest keys must exactly match filenames. Its `context` field is a short, curated, factual source description prepended to each chunk before embedding; it is not an LLM-generated summary.

```powershell
.\frontend\venv\Scripts\python.exe -m backend.regulatory_corpus.ingest
```

The first run downloads Qwen from Hugging Face and computes the corpus embeddings locally, then uploads them to Qdrant. This embedding step can take a while on a CPU-only laptop. Re-running skips unchanged PDFs; changed PDFs or manifest/chunk settings are re-embedded. If a run stops after some PDFs were uploaded, rerunning resumes by skipping completed PDFs.

Use `--rebuild` only when you intend to delete and recreate the entire configured Qdrant collection:

```powershell
.\frontend\venv\Scripts\python.exe -m backend.regulatory_corpus.ingest --rebuild
```

## Search

Queries use the same Qwen model locally; its weights are cached after first use. Reranking also runs locally and caches its cross-encoder model on first use.

```powershell
.\frontend\venv\Scripts\python.exe -m backend.regulatory_corpus.search "What liquidity requirements apply to this bank?" --top-k 5
.\frontend\venv\Scripts\python.exe -m backend.regulatory_corpus.search "What liquidity requirements apply to this bank?" --recall-k 20 --top-k 5 --rerank
```

Results include the clean source passage and citation metadata (title, source URL, effective date, and PDF page range). Use `--source-type mas_notice` to filter by a metadata type. Keep enforcement actions separately labeled from binding requirements and guidance.

## Sharing with teammates

The Qdrant collection is hosted remotely and shared by anyone with the endpoint and API key; it is not stored in Git or only on the computer that ingested it. Teammates can query the shared collection without ingesting the PDFs, but each machine runs Qwen locally to embed its query. Share the API key privately, never through Git. Qdrant free clusters may suspend after inactivity, so retain the official PDFs and manifest for rebuilding. For scanned/image-only PDFs, OCR is needed first; the current extractor reports files where it finds no text.

## Retrieval details

The default chunk window is 350 words with 60 words of overlap, retaining page ranges. The contextualized passage is embedded while the clean passage and metadata are stored in Qdrant. Dense retrieval may miss exact provision numbers or phrases; add keyword/BM25 retrieval if evaluation shows that gap. Reranking can reorder only the candidates returned by the initial vector search.
