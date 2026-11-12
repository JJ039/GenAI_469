"""Retrieve regulatory PDF chunks and optionally rerank as in the class notebook."""
import argparse
import json

from backend.regulatory_corpus.store import (
    QUERY_INSTRUCTION, load_model, open_collection,
)
from qdrant_client import models


def search(query, *, top_k=5, recall_k=20, rerank=False, source_type=None):
    if not query.strip():
        raise ValueError("Query must not be empty")
    if top_k < 1 or recall_k < 1:
        raise ValueError("top_k and recall_k must be positive")
    client, collection_name = open_collection()
    count = client.count(collection_name=collection_name, exact=True).count
    if count == 0:
        raise ValueError("The collection is empty. Run ingest.py first.")
    model = load_model()
    query_vector = model.encode(
        [query], prompt=QUERY_INSTRUCTION, normalize_embeddings=True
    ).tolist()
    query_filter = models.Filter(
        must=[models.FieldCondition(
            key="source_type", match=models.MatchValue(value=source_type)
        )]
    ) if source_type else None
    result = client.query_points(
        collection_name=collection_name,
        query=query_vector[0],
        limit=min(recall_k if rerank else top_k, count),
        query_filter=query_filter,
        with_payload=True,
    )
    rows = []
    for point in result.points:
        payload = point.payload or {}
        document = payload.get("text", "")
        metadata = {key: value for key, value in payload.items() if key != "text"}
        context = metadata.get("context_blurb", "")
        rows.append({
            "text": document,
            "metadata": metadata,
            "score": point.score,
            "_rerank_text": f"{context}\n\n{document}" if context else document,
        })

    if rerank and rows:
        from sentence_transformers import CrossEncoder
        reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        scores = reranker.predict([[query, row["_rerank_text"]] for row in rows])
        for row, score in zip(rows, scores):
            row["rerank_score"] = float(score)
        rows.sort(key=lambda row: row["rerank_score"], reverse=True)

    for row in rows:
        row.pop("_rerank_text", None)
    return rows[:top_k]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Question to retrieve regulatory passages for")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--recall-k", type=int, default=20)
    parser.add_argument("--rerank", action="store_true", help="Rerank the wider candidate set")
    parser.add_argument("--source-type", help="Optional exact metadata filter, e.g. mas_notice")
    args = parser.parse_args()
    results = search(
        args.query, top_k=args.top_k, recall_k=args.recall_k,
        rerank=args.rerank, source_type=args.source_type,
    )
    for rank, row in enumerate(results, start=1):
        print(json.dumps({"rank": rank, **row}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
