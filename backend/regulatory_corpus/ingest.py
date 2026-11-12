"""Extract, chunk, embed and persist PDFs into Qdrant Cloud."""
import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path

from pypdf import PdfReader
from qdrant_client import models

from backend.regulatory_corpus.store import (
    PDF_DIR, EMBEDDING_MODEL, load_model, open_collection, source_filter,
)

WINDOW_WORDS = 350
OVERLAP_WORDS = 60
CONTEXT_VERSION = "document-context-v1"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_pages(path):
    reader = PdfReader(str(path))
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            pages.append((page_number, text))
    return pages


def chunk_pages(pages, window=WINDOW_WORDS, overlap=OVERLAP_WORDS):
    """Word windows retain the page span for each chunk, like the class notebook."""
    if window < 50 or overlap < 0 or overlap >= window:
        raise ValueError("Use window >= 50 and 0 <= overlap < window")
    words = []
    for page_number, text in pages:
        words.extend((page_number, word) for word in text.split())
    chunks, step = [], window - overlap
    for start in range(0, len(words), step):
        window_words = words[start:start + window]
        if not window_words:
            break
        chunks.append({
            "text": " ".join(word for _, word in window_words),
            "page_start": window_words[0][0],
            "page_end": window_words[-1][0],
        })
        if start + window >= len(words):
            break
    return chunks


def load_manifest():
    path = PDF_DIR / "manifest.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest.json must contain a filename-to-metadata object")
    return data


def make_contextual_text(chunk_text, metadata, page_start, page_end):
    """Prefix a short, source-grounded blurb before embedding the passage."""
    blurb = metadata.get("context", "")
    if not isinstance(blurb, str) or not blurb.strip():
        source_type = str(metadata.get("source_type", "public_regulation")).replace("_", " ")
        blurb = (
            f"This is a passage from {metadata.get('title', 'an official Singapore source')}, "
            f"classified as {source_type}."
        )
    location = f"Pages {page_start}-{page_end}" if page_start != page_end else f"Page {page_start}"
    return (
        f"Document context: {blurb.strip()}\n"
        f"Source: {metadata.get('title', 'Untitled source')} | {location}\n\n"
        f"Passage:\n{chunk_text}"
    )


def ingest(*, rebuild=False):
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(path for path in PDF_DIR.glob("*.pdf") if path.is_file())
    if not pdf_paths:
        raise SystemExit(f"No PDFs found. Add official source PDFs to: {PDF_DIR}")

    client, collection_name = open_collection(rebuild=rebuild)
    manifest = load_manifest()
    model = None
    added, skipped = 0, 0

    for path in pdf_paths:
        source_hash = sha256_file(path)
        pages = extract_pages(path)
        if not pages:
            print(f"No extractable text (possibly scanned PDF), skipping: {path.name}")
            continue
        chunks = chunk_pages(pages)
        if not chunks:
            print(f"No text chunks created, skipping: {path.name}")
            continue

        entry = manifest.get(path.name, {})
        if not isinstance(entry, dict):
            raise ValueError(f"Manifest entry for {path.name} must be an object")
        title = entry.get("title", path.stem)
        context = entry.get("context", "")
        source_type = str(entry.get("source_type", "public_regulation"))
        index_config = {
            "embedding_model": EMBEDDING_MODEL,
            "context_version": CONTEXT_VERSION,
            "title": str(title),
            "source_type": source_type,
            "url": str(entry.get("url", "")),
            "effective_date": str(entry.get("effective_date", "")),
            "context": context,
            "window_words": WINDOW_WORDS,
            "overlap_words": OVERLAP_WORDS,
        }
        index_config_hash = hashlib.sha256(
            json.dumps(index_config, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        # Context or chunking changes require new vectors, even when the source PDF is unchanged.
        existing_points, offset = [], None
        while True:
            points, offset = client.scroll(
                collection_name=collection_name,
                scroll_filter=source_filter(path.name),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            existing_points.extend(points)
            if offset is None:
                break
        if existing_points and all(
            point.payload.get("source_sha256") == source_hash
            and point.payload.get("index_config_sha256") == index_config_hash
            for point in existing_points
        ):
            print(f"Unchanged, skipping: {path.name}")
            skipped += 1
            continue
        if existing_points:
            client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(filter=source_filter(path.name)),
                wait=True,
            )

        if model is None:
            model = load_model()

        metadata_base = {
            "title": str(title),
            "source_type": source_type,
            "url": str(entry.get("url", "")),
            "effective_date": str(entry.get("effective_date", "")),
            "context_blurb": str(context),
            "source_file": path.name,
            "source_sha256": source_hash,
            "index_config_sha256": index_config_hash,
            "embedding_model": EMBEDDING_MODEL,
        }
        chunk_ids, documents, embedding_texts, metadatas = [], [], [], []
        for index, chunk in enumerate(chunks):
            chunk_hash = hashlib.sha256(
                f"{path.name}:{source_hash}:{index}".encode("utf-8")
            ).hexdigest()
            chunk_ids.append(str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_hash)))
            documents.append(chunk["text"])
            embedding_texts.append(make_contextual_text(
                chunk["text"], {**entry, "title": title},
                chunk["page_start"], chunk["page_end"],
            ))
            metadatas.append({
                **metadata_base,
                "chunk_index": index,
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
            })

        vectors = model.encode(
            embedding_texts,
            batch_size=8,
            normalize_embeddings=True,
            show_progress_bar=True,
        ).tolist()
        # Store clean source passages as payload; vectors use contextualized text.
        client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=chunk_id,
                    vector=vector,
                    payload={**metadata, "text": document},
                )
                for chunk_id, vector, metadata, document in zip(
                    chunk_ids, vectors, metadatas, documents
                )
            ],
            wait=True,
        )
        added += len(chunks)
        print(f"Indexed {path.name}: {len(chunks)} chunks")

    print(f"Done. Added {added} chunks; skipped {skipped} unchanged PDFs.")
    print(f"Qdrant collection: {collection_name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Delete and recreate the Qdrant collection before indexing PDFs.",
    )
    args = parser.parse_args()
    ingest(rebuild=args.rebuild)


if __name__ == "__main__":
    main()
