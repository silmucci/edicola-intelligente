"""Unisce lo snapshot GitHub all'archivio locale, con backup e senza API.

Non elimina ne riscrive PDF, estrazioni, chunk o vettori presenti. Il ripristino
dello snapshot usa il manifest e conserva gli embedding Gemini gia verificati.
Eseguire con Streamlit fermo; la procedura e idempotente e riprendibile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from edicola.archive import read_active_chunks
from edicola.cloud import digest, validate_seed
from edicola.embeddings import validate_vector
from edicola.indexing import plan_index
from edicola.maintenance_store import maintenance_lock
from edicola.storage import open_registry
from edicola.vectorstore import open_collection, stored_records

TABLES = ("sources", "extractions", "chunk_sets", "chunks")
KEYS = {"sources": "filename", "extractions": "sha256",
        "chunk_sets": "sha256", "chunks": "id"}


def _local_paths(root):
    root = Path(root).resolve()
    data = root / "data"
    incoming = data / "incoming"
    registry = data / "archive.sqlite3"
    for path in (data, incoming, registry, data / "chroma", data / "editions.json",
                 data / "corpus_updates"):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Percorso locale non consentito.")
    if not incoming.is_dir() or not registry.is_file():
        raise ValueError("Avviare prima l'app locale per preparare il registro dei nuovi PDF.")
    return root, data, incoming, registry


def _read_editions(path):
    if not path.exists():
        return {}
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Catalogo edizioni locale non valido.")
    return result


def _rows(db, table):
    return {row[0]: tuple(row) for row in db.execute(
        f"SELECT {KEYS[table]}, * FROM {table}"
    )}


def _inspect(root):
    from edicola.settings import setting
    root, data, incoming, registry = _local_paths(root)
    if setting("EDICOLA_CLOUD_DEMO", "0", root=root) == "1":
        raise ValueError("Non modificare la modalità snapshot immutabile.")
    seed = root / "deployment/seed"
    manifest = validate_seed(seed)
    expected = manifest["files"]
    seed_files = {
        Path(name).name: (seed / name, sha)
        for name, sha in expected.items() if name.startswith("data/incoming/")
    }
    current_files = {}
    for path in incoming.iterdir():
        if path.suffix.lower() != ".pdf":
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("Un PDF locale non è un file regolare.")
        current_files[path.name] = digest(path)
    for name, (_, sha) in seed_files.items():
        if name in current_files and current_files[name] != sha:
            raise ValueError("Conflitto di nome tra PDF locale e snapshot: " + name)

    with closing(sqlite3.connect(registry.resolve().as_uri() + "?mode=ro", uri=True)) as local, closing(
        sqlite3.connect((seed / "data/archive.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)
    ) as original:
        local_sources = dict(local.execute("SELECT filename,sha256 FROM sources"))
        for name, sha in current_files.items():
            if local_sources.get(name, sha) != sha:
                raise ValueError("Il PDF locale e il suo registro non coincidono.")
        for name, (_, sha) in seed_files.items():
            if name in local_sources and local_sources[name] != sha:
                raise ValueError("Il nome esiste nel registro con un hash differente: " + name)
        for table in TABLES:
            # Il seed ha schema esportato; non sovrascrivere dati locali.
            current = _rows(local, table)
            older = _rows(original, table)
            if table == "sources":
                # last_seen_at è informazione locale, non un conflitto.
                mismatches = [key for key, row in older.items()
                              if key in current and row[2] != current[key][2]]
            elif table == "extractions":
                mismatches = [key for key, row in older.items()
                              if key in current and row[2] != current[key][2]]
            elif table == "chunk_sets":
                mismatches = [key for key, row in older.items()
                              if key in current and row[2:4] != current[key][2:4]]
            else:
                mismatches = [key for key, row in older.items()
                              if key in current and row[2:] != current[key][2:]]
            if mismatches:
                raise ValueError("Dati incompatibili nello schema: " + table)
    seed_chunks, seed_warnings = read_active_chunks(
        seed / "data/archive.sqlite3", seed / "data/incoming"
    )
    if seed_warnings or len(seed_chunks) != manifest["chunks"]:
        raise ValueError("Chunk dello snapshot non coerenti.")
    by_id = {chunk.id: chunk for chunk in seed_chunks}
    records = json.loads((seed / "vectors.json").read_text(encoding="utf-8"))
    if len(records) != manifest["indexed"] or len({r["id"] for r in records}) != len(records):
        raise ValueError("Conteggio embedding nello snapshot incoerente.")
    for record in records:
        chunk = by_id.get(record["id"])
        if (chunk is None or record["text"] != chunk.text
                or record["metadata"].get("input_sha256") != chunk.fingerprint):
            raise ValueError("Embedding senza testo o prompt identico nello snapshot.")
        validate_vector(record["embedding"])
    collection = open_collection(data / "chroma", create=False)
    stored = stored_records(collection)
    for record in records:
        current = stored.get(record["id"])
        if current and (current["text"] != record["text"] or
                        current["metadata"].get("input_sha256") !=
                        record["metadata"].get("input_sha256")):
            raise ValueError("Embedding locale diverso: non sovrascrivere un vettore.")
    local_editions = _read_editions(data / "editions.json")
    seed_editions = _read_editions(seed / "data/editions.json")
    metadata_additions = {name: value for name, value in seed_editions.items()
                          if name not in local_editions}
    # Conta i chunk locali già attivi senza eseguire nuove estrazioni.
    local_chunks, warnings = read_active_chunks(registry, incoming)
    if warnings:
        raise ValueError("Aggiornare prima i PDF locali segnalati da read_active_chunks.")
    union_ids = {c.id for c in seed_chunks} | {c.id for c in local_chunks}
    return {
        "root": root, "data": data, "incoming": incoming, "registry": registry,
        "seed": seed, "manifest": manifest, "seed_files": seed_files,
        "records": records, "existing": stored, "seed_editions": seed_editions,
        "local_editions": local_editions,
        "report": {
            "snapshot_pdfs": manifest["pdfs"],
            "new_local_pdfs": len(set(current_files) - set(seed_files)),
            "pdfs_after_union": len(set(current_files) | set(seed_files)),
            "local_chunks_before": len(local_chunks),
            "total_chunks_after_union": len(union_ids),
            "snapshot_embeddings": len(records),
            "existing_local_embeddings": len(stored),
            "vectors_to_reuse": sum(r["id"] not in stored for r in records),
            "new_files_to_copy": sum(name not in current_files for name in seed_files),
            "edition_metadata_to_add": len(metadata_additions),
            "gemini_api_calls": 0,
        },
    }


def plan_union(root):
    """Verifica in sola lettura, senza creare backup o modificare Chroma."""
    return dict(_inspect(root)["report"])


def _backup_registry(source, destination):
    with closing(sqlite3.connect(source)) as db, closing(sqlite3.connect(destination)) as backup:
        db.backup(backup)


def _publish_pdf(source, target):
    if target.exists() or target.is_symlink():
        if target.is_symlink() or digest(source) != digest(target):
            raise ValueError("Il PDF è cambiato durante l'importazione.")
        return False
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            with source.open("rb") as original:
                shutil.copyfileobj(original, stream, length=1024 * 1024)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)  # O_EXCL: non sovrascrivere un PDF utente.
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return True


def _merge_registry(snapshot, stage):
    source_path = snapshot / "data/archive.sqlite3"
    with closing(sqlite3.connect(stage)) as local, closing(
        sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as source:
        with local:
            for table in TABLES:
                rows = source.execute(f"SELECT * FROM {table}").fetchall()
                if not rows:
                    continue
                marks = ", ".join("?" for _ in rows[0])
                local.executemany(f"INSERT OR IGNORE INTO {table} VALUES ({marks})", rows)


def _atomic_json(path, payload):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, mode="w",
                                         encoding="utf-8", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def apply_union(root):
    """Scrive solo file mancanti e vettori verificati, con backup dell'archivio."""
    root = Path(root).resolve()
    with maintenance_lock(root):
        details = _inspect(root)
        data, incoming = details["data"], details["incoming"]
        registry, seed = details["registry"], details["seed"]
        backup_root = data / "corpus_updates"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_root / ("before-seed-union-" + stamp)
        backup.mkdir(parents=False, exist_ok=False)
        _backup_registry(registry, backup / "archive.sqlite3")
        if (data / "chroma").exists():
            shutil.copytree(data / "chroma", backup / "chroma")
        if (data / "editions.json").exists():
            shutil.copy2(data / "editions.json", backup / "editions.json")

        # Preparazione del DB in una copia privata: il registro live viene
        # sostituito con os.replace solo dopo la fusione completa.
        staged = backup_root / ("stage-union-" + stamp + ".sqlite3")
        try:
            _backup_registry(registry, staged)
            _merge_registry(seed, staged)
            # Il file sorgente non cambia e l'installazione è senza overwrite.
            for name, (path, sha) in details["seed_files"].items():
                if digest(path) != sha:
                    raise ValueError("PDF sorgente cambiato durante l'importazione.")
                _publish_pdf(path, incoming / name)
            os.replace(staged, registry)
        finally:
            staged.unlink(missing_ok=True)

        # Chroma upsert per batch: se un'operazione viene interrotta, il
        # successivo --apply recupera solo gli ID mancanti (idempotente).
        collection = open_collection(data / "chroma", create=True)
        remaining = [r for r in details["records"] if r["id"] not in details["existing"]]
        for offset in range(0, len(remaining), 100):
            batch = remaining[offset:offset + 100]
            collection.upsert(
                ids=[r["id"] for r in batch],
                documents=[r["text"] for r in batch],
                metadatas=[r["metadata"] for r in batch],
                embeddings=[r["embedding"] for r in batch],
            )
        joined_editions = {**details["seed_editions"], **details["local_editions"]}
        if joined_editions != details["local_editions"]:
            _atomic_json(data / "editions.json", joined_editions)
        chunks, warnings = read_active_chunks(registry, incoming)
        if warnings or len(chunks) != details["report"]["total_chunks_after_union"]:
            raise RuntimeError("Il corpus unificato non è coerente; backup conservato.")
        plan = plan_index(chunks, open_collection(data / "chroma"))
        return {**details["report"], "active_chunks": len(chunks),
                "already_indexed": plan.unchanged + len(plan.metadata_updates),
                "pending": len(plan.pending),
                "metadata_updates": len(plan.metadata_updates),
                "backup": str(backup.relative_to(root)), "applied": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Verifica il piano senza scrivere nulla.")
    mode.add_argument("--apply", action="store_true", help="Unisce con backup, senza API Gemini.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        report = apply_union(args.root) if args.apply else plan_union(args.root)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError) as exc:
        print("Unione non completata: " + str(exc))
        print("Nessuna API Gemini chiamata. Conservare i backup e ripetere la verifica.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
