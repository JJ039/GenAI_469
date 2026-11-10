"""Qdrant Cloud connection and Qwen embedding configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent
PDF_DIR = ROOT / "pdfs"
load_dotenv(ROOT.parents[1] / ".env")

COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "regulatory_corpus_v1")
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_DIMENSIONS = 1024
QUERY_INSTRUCTION = (
    "Instruct: Retrieve Singapore banking regulatory passages that directly answer "
    "the compliance question. Prefer applicable requirements and exact sections.\nQuery:"
)


def load_model():
    # Downloads from Hugging Face on first use, then uses the local cache.
    return SentenceTransformer(EMBEDDING_MODEL)


def open_collection(*, rebuild=False):
    """Connect to Qdrant Cloud and ensure a compatible collection exists."""
    url = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")
    if not url or not api_key:
        raise RuntimeError(
            "Set QDRANT_URL and QDRANT_API_KEY in the repository-root .env file."
        )

    client = QdrantClient(url=url, api_key=api_key)
    if rebuild and client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)

    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIMENSIONS,
                distance=models.Distance.COSINE,
            ),
        )
    else:
        config = client.get_collection(COLLECTION_NAME).config.params.vectors
        if not isinstance(config, models.VectorParams):
            raise ValueError("The Qdrant collection must use a single dense vector.")
        if config.size != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Collection has {config.size} dimensions; expected {EMBEDDING_DIMENSIONS}. "
                "Choose a new collection name or rebuild it."
            )
        if config.distance != models.Distance.COSINE:
            raise ValueError("The Qdrant collection must use cosine distance.")
    return client, COLLECTION_NAME


def source_filter(source_file):
    return models.Filter(
        must=[models.FieldCondition(
            key="source_file", match=models.MatchValue(value=source_file)
        )]
    )
