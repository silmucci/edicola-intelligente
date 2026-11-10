"""Aggiornamento LOCALE, manuale e con backup delle vecchie estrazioni PDF.

Il comando non tocca ChromaDB, non effettua chiamate API e non cancella cache
editoriali. Dopo un refresh possono servire embedding esplicite per i chunk mutati.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from edicola.chunking import prepare_documents
from edicola.ingestion import extract_pdf, ingest_directory

ROOT = Path(__file__).resolve().parents[1]


def refresh(root: Path, names: list[str], *, apply=False):
    if not names:
        raise ValueError("Selezionare almeno un PDF con --pdf.")
    incoming = root / "data/incoming"
    registry = root / "data/archive.sqlite3"
    if not registry.is_file() or not incoming.is_dir():
        raise ValueError("Archivio locale non disponibile.")
    planned = {}
    with sqlite3.connect(registry.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        for filename in names:
            path = incoming / filename
            if (path.name != filename or not path.is_file() or path.is_symlink() or
                    path.parent.resolve() != incoming.resolve() or path.suffix.lower() != ".pdf"):
                raise ValueError("Nome PDF non valido o documento non disponibile.")
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            source = connection.execute("SELECT sha256 FROM sources WHERE filename=?", (filename,)).fetchone()
            if not source or source[0] != digest:
                raise ValueError("Aprire prima l'Edicola per acquisire la versione attuale del documento.")
            previous = connection.execute("SELECT result_json FROM extractions WHERE sha256=?", (digest,)).fetchone()
            if not previous:
                raise ValueError("Estrazione precedente non disponibile.")
            updated = extract_pdf(content)
            if updated["status"] not in {"ok", "partial", "no_text"}:
                raise ValueError("Il nuovo estrattore non ha prodotto un risultato utilizzabile.")
            if json.loads(previous[0]) != updated:
                planned[digest] = updated
    report = {"dry_run": not apply, "pdf_requested": len(names),
              "extractions_to_update": len(planned), "backup": None,
              "embedding_refresh_required": bool(planned)}
    if not apply or not planned:
        return report
    backup_dir = root / "data/corpus_updates"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / ("archive-before-layout-" + stamp + ".sqlite3")
    # Backup coerente anche in presenza di journal WAL attivo.
    with sqlite3.connect(registry) as source, sqlite3.connect(backup_path) as destination:
        source.backup(destination)
    report["backup"] = str(backup_path)
    with sqlite3.connect(registry) as connection:
        for digest, result in planned.items():
            connection.execute("""UPDATE extractions SET result_json=?, extracted_at=CURRENT_TIMESTAMP
                WHERE sha256=?""", (json.dumps(result, ensure_ascii=False), digest))
            connection.execute("DELETE FROM chunk_sets WHERE sha256=?", (digest,))
            connection.execute("DELETE FROM chunks WHERE pdf_sha256=?", (digest,))
    # Riporta i chunk nel registro soltanto dopo la transazione locale.
    documents = ingest_directory(incoming, registry)
    prepare_documents(documents, registry)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", action="append", default=[], help="PDF già acquisito, ripetibile.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true",
                      help="Con backup, sostituisce solo le estrazioni selezionate nel registro SQLite.")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(refresh(ROOT, args.pdf, apply=args.apply), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error, RuntimeError):
        print("Aggiornamento locale non completato. Verificare PDF, backup e registro SQLite.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
