"""Hybrid Qwen/Qdrant and local-PDF BM25 retrieval for regulatory passages."""
import math
import re
from collections import Counter
from functools import lru_cache

from backend.regulatory_corpus.ingest import chunk_pages, extract_pages, load_manifest
from backend.regulatory_corpus.store import QUERY_INSTRUCTION, PDF_DIR, load_model, open_collection

RRF_K = 60
TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def authority_type(source_type):
    value = str(source_type or "").casefold()
    if any(term in value for term in ("enforcement", "penalty", "fine", "disciplinary")):
        return "enforcement_example"
    if any(term in value for term in ("legislation", "act", "notice", "regulation", "binding_rule")):
        return "binding_rule"
    if any(term in value for term in ("guidance", "framework", "monograph", "guideline")):
        return "guidance"
    return "unclassified_source"


def _tokens(text):
    return TOKEN_RE.findall(text.casefold())


class HybridRegulatorySearch:
    """Load the local lexical index and Qwen model once for one compliance run."""

    def __init__(self):
        self.client, self.collection_name = open_collection()
        self.model = load_model()
        manifest = load_manifest()
        self.documents = []
        for path in sorted(PDF_DIR.glob("*.pdf")):
            entry = manifest.get(path.name, {})
            for index, chunk in enumerate(chunk_pages(extract_pages(path))):
                self.documents.append({
                    "text": chunk["text"],
                    "metadata": {
                        "title": str(entry.get("title", path.stem)),
                        "source_type": str(entry.get("source_type", "public_regulation")),
                        "url": str(entry.get("url", "")),
                        "effective_date": str(entry.get("effective_date", "")),
                        "source_file": path.name,
                        "chunk_index": index,
                        "page_start": chunk["page_start"],
                        "page_end": chunk["page_end"],
                    },
                })
        self.tokenized = [_tokens(doc["text"]) for doc in self.documents]
        self.lengths = [len(doc) for doc in self.tokenized]
        self.average_length = sum(self.lengths) / max(len(self.lengths), 1)
        self.document_frequency = Counter(
            token for doc in self.tokenized for token in set(doc)
        )

    def _bm25(self, query, limit):
        query_terms = _tokens(query)
        count = len(self.documents)
        scored = []
        for index, terms in enumerate(self.tokenized):
            frequencies = Counter(terms)
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = self.document_frequency[term]
                inverse_frequency = math.log(1 + (count - df + 0.5) / (df + 0.5))
                norm = frequency + 1.5 * (1 - 0.75 + 0.75 * self.lengths[index] / max(self.average_length, 1))
                score += inverse_frequency * frequency * 2.5 / norm
            if score > 0:
                scored.append((score, index))
        scored.sort(reverse=True)
        return [
            {**self.documents[index], "score": score, "retrieval_method": "bm25"}
            for score, index in scored[:limit]
        ]

    def search(self, query, *, limit=5):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Retrieval query must be nonempty text")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
            raise ValueError("Hybrid retrieval limit must be between 1 and 5")
        vector = self.model.encode(
            [query], prompt=QUERY_INSTRUCTION, normalize_embeddings=True
        ).tolist()[0]
        dense = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=20,
            with_payload=True,
        ).points
        dense_rows = []
        for point in dense:
            payload = point.payload or {}
            metadata = {key: value for key, value in payload.items() if key != "text"}
            dense_rows.append({
                "text": payload.get("text", ""), "metadata": metadata,
                "score": point.score, "retrieval_method": "qwen_qdrant",
            })
        lexical_rows = self._bm25(query, 20)

        fused = {}
        for rows in (dense_rows, lexical_rows):
            for rank, row in enumerate(rows, start=1):
                meta = row["metadata"]
                key = (meta.get("source_file"), meta.get("chunk_index"))
                if key not in fused:
                    fused[key] = {**row, "rrf_score": 0.0, "retrieval_methods": []}
                fused[key]["rrf_score"] += 1 / (RRF_K + rank)
                if row["retrieval_method"] not in fused[key]["retrieval_methods"]:
                    fused[key]["retrieval_methods"].append(row["retrieval_method"])

        rows = sorted(fused.values(), key=lambda row: row["rrf_score"], reverse=True)[:limit]
        results = []
        for rank, row in enumerate(rows, start=1):
            metadata = row["metadata"]
            results.append({
                "evidence_id": f"{metadata.get('source_file')}:{metadata.get('chunk_index')}",
                "text": row["text"],
                "source": metadata.get("title", metadata.get("source_file", "Unknown source")),
                "source_file": metadata.get("source_file"),
                "source_type": metadata.get("source_type", "public_regulation"),
                "authority_type": authority_type(metadata.get("source_type")),
                "section": metadata.get("section"),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "url": metadata.get("url", ""),
                "effective_date": metadata.get("effective_date", ""),
                "retrieval_methods": row["retrieval_methods"],
                "rrf_score": row["rrf_score"],
                "rank": rank,
            })
        return results


@lru_cache(maxsize=1)
def get_hybrid_search():
    """Reuse the local model and lexical index across multiple action reviews."""
    return HybridRegulatorySearch()
