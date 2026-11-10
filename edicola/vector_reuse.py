"""Riuso locale degli embedding quando un passaggio è identico tra versioni.

Nessuna API, nessun modello locale, nessuna cancellazione dei vettori storici.
I soli candidati sono i chunk legati dalla tabella edition_lineage, con testo,
pagina e intervallo identici. Il loro prompt di embedding è identico alla
versione precedente, perciò si copia lo stesso vettore senza rigenerarlo.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from edicola.archive import read_active_chunks
from edicola.embeddings import validate_vector
from edicola.maintenance_store import maintenance_lock
from edicola.vectorstore import open_collection, stored_records


def _has_versions(root: Path) -> bool:
    path = root / "data/archive.sqlite3"
    if not path.is_file():
        return False
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='edition_lineage'"
        ).fetchone()
        return bool(table and db.execute("SELECT 1 FROM edition_lineage LIMIT 1").fetchone())


def reuse_unchanged_vectors(root: Path) -> int:
    """Restituisce i chunk recuperati localmente; quelli cambiati restano pending."""
    root = Path(root).resolve()
    if not _has_versions(root):
        return 0
    # La modalità cloud distribuita non deve scrivere nei propri dati.
    from edicola.settings import setting
    if setting("EDICOLA_CLOUD_DEMO", "0", root=root) == "1":
        return 0
    with maintenance_lock(root):
        chunks, warnings = read_active_chunks(
            root / "data/archive.sqlite3", root / "data/incoming"
        )
        if warnings:
            return 0
        candidates = [
            chunk for chunk in chunks if chunk.metadata.get("embedding_source_sha256")
        ]
        if not candidates:
            return 0
        collection = open_collection(root / "data/chroma", create=False)
        if collection is None or not collection.count():
            return 0
        saved = stored_records(collection)
        old_by_key = {
            (chunk.metadata["pdf_sha256"], chunk.metadata["page"],
             chunk.metadata["start"], chunk.metadata["end"], chunk.text): chunk
            for chunk in chunks
        }
        reused = 0
        for new in candidates:
            current = saved.get(new.id)
            if current and current["text"] == new.text and current["metadata"] == new.chroma_metadata:
                continue
            origin = new.metadata["embedding_source_sha256"]
            old = old_by_key.get((
                origin, new.metadata["page"], new.metadata["start"],
                new.metadata["end"], new.text
            ))
            if old is None:
                continue
            original_record = saved.get(old.id)
            if (original_record is None or original_record["text"] != old.text or
                    original_record["metadata"].get("input_sha256") != old.fingerprint or
                    new.fingerprint != old.fingerprint):
                continue
            response = collection.get(ids=[old.id], include=["embeddings"])
            if response["ids"] != [old.id]:
                continue
            vector = validate_vector(response["embeddings"][0])
            collection.upsert(
                ids=[new.id], documents=[new.text],
                metadatas=[new.chroma_metadata], embeddings=[vector],
            )
            reused += 1
        return reused
