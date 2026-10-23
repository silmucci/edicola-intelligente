"""Chroma persistente con embedding function esplicitamente disabilitata."""

from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.errors import NotFoundError

from edicola.embeddings import DIMENSIONS, FORMAT_VERSION, MODEL


COLLECTION = "edicola_gemini_embedding_2_768"
COLLECTION_METADATA = {"model": MODEL, "dimensions": DIMENSIONS,
                       "prompt_format": FORMAT_VERSION, "distance": "cosine"}


def open_collection(path: Path, *, create=False):
    if not create and not (path / "chroma.sqlite3").exists():
        return None
    client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
    try:
        collection = client.get_collection(COLLECTION, embedding_function=None)
    except NotFoundError:
        if not create:
            return None
        collection = client.create_collection(
            COLLECTION, embedding_function=None, metadata=COLLECTION_METADATA,
            configuration={"hnsw": {"space": "cosine"}},
        )
    if any((collection.metadata or {}).get(key) != value for key, value in COLLECTION_METADATA.items()):
        raise RuntimeError("Collezione incompatibile: modello, dimensioni o formato diversi. Usare una nuova collezione.")
    if collection.configuration["hnsw"]["space"] != "cosine":
        raise RuntimeError("Collezione incompatibile: distanza diversa da cosine.")
    if collection.count():
        sample = collection.get(limit=1, include=["embeddings"])
        if len(sample["embeddings"][0]) != DIMENSIONS:
            raise RuntimeError("Collezione incompatibile: dimensionalità effettiva diversa da 768.")
    return collection


def stored_records(collection) -> dict:
    if collection is None:
        return {}
    records = {}
    offset = 0
    while True:
        batch = collection.get(limit=500, offset=offset, include=["metadatas", "documents"])
        if not batch["ids"]:
            break
        for identity, metadata, text in zip(batch["ids"], batch["metadatas"], batch["documents"]):
            records[identity] = {"metadata": metadata or {}, "text": text}
        offset += len(batch["ids"])
    return records
