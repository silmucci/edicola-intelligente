"""Aggiorna con Tesseract le pagine vecchie scarsamente estraibili, senza API.

Eseguire a Streamlit fermo. I chunk modificati richiedono successivamente
un'indicizzazione esplicita con Gemini; il comando non modifica Chroma.

  python -m edicola.ocr_backfill --dry-run
  python -m edicola.ocr_backfill --apply --limit 10
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from edicola.chunking import prepare_documents
from edicola.ingestion import ingest_directory
from edicola.maintenance_store import maintenance_lock
from edicola.ocr import OCR_METHOD, needs_ocr, recognize_page, tesseract_available
from edicola.storage import load_result, open_registry

ROOT = Path(__file__).resolve().parents[1]


def _eligible(page: dict) -> bool:
    return (not page.get("error") and page.get("extraction_method") != OCR_METHOD
            and needs_ocr(page.get("text", "")))


def _refresh_status(result: dict) -> None:
    pages = result["pages"]
    errors = sum(bool(page.get("error")) for page in pages)
    has_text = any(page.get("text", "").strip() for page in pages)
    missing = sum(not page.get("text", "").strip() and not page.get("error") for page in pages)
    result["status"] = "partial" if errors and has_text else (
        "error" if errors else "ok" if has_text else "no_text")
    result["message"] = (f"{errors} pagine con errori di estrazione." if errors else
                         f"{missing} pagine senza testo estraibile." if missing else "")


def refresh(root: Path, *, apply: bool = False, limit: int = 10,
            filenames: tuple[str, ...] = ()) -> dict:
    """Scansione progressiva. Le chiamate locali sono autorizzate con --apply."""
    if type(limit) is not int or limit <= 0:
        raise ValueError("Il limite di pagine deve essere positivo.")
    root = Path(root).resolve()
    incoming = root / "data/incoming"
    registry = root / "data/archive.sqlite3"
    if not incoming.is_dir() or not registry.is_file():
        raise RuntimeError("Archivio locale non preparato: aprire prima Streamlit.")
    selected = set(filenames)
    files = sorted((p for p in incoming.iterdir() if p.is_file() and not p.is_symlink()
                    and p.suffix.lower() == ".pdf" and (not selected or p.name in selected)),
                   key=lambda p: p.name.casefold())
    if selected - {p.name for p in files}:
        raise ValueError("Uno o più PDF richiesti non sono nell'archivio locale.")
    if apply and not tesseract_available():
        raise RuntimeError("Tesseract non è installato o non è disponibile nel PATH.")
    report = {"dry_run": not apply, "ocr_available": tesseract_available(),
              "candidate_pages": 0, "attempted_pages": 0, "recovered_pages": 0,
              "updated_documents": 0, "limit": limit, "indexing_required": False}
    seen = set()
    # Stesso lock delle operazioni amministrative sull'archivio.
    with maintenance_lock(root):
        with open_registry(registry) as connection:
            for path in files:
                content = path.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                cached = load_result(connection, digest)
                if not cached:
                    continue
                candidates = [page for page in cached.get("pages", []) if _eligible(page)]
                report["candidate_pages"] += len(candidates)
                if not apply or report["attempted_pages"] >= limit:
                    continue
                changed = False
                for page in candidates:
                    if report["attempted_pages"] >= limit:
                        break
                    report["attempted_pages"] += 1
                    recognized = recognize_page(content, page["number"], page.get("text", ""))
                    if not recognized:
                        continue
                    page["text"] = recognized
                    page["extraction_method"] = OCR_METHOD
                    page.pop("blocks", None)
                    report["recovered_pages"] += 1
                    changed = True
                if changed:
                    _refresh_status(cached)
                    with connection:
                        connection.execute(
                            "UPDATE extractions SET result_json=?, extracted_at=CURRENT_TIMESTAMP WHERE sha256=?",
                            (json.dumps(cached, ensure_ascii=False), digest))
                        connection.execute("DELETE FROM chunk_sets WHERE sha256=?", (digest,))
                        connection.execute("DELETE FROM chunks WHERE pdf_sha256=?", (digest,))
                    report["updated_documents"] += 1
        if report["updated_documents"]:
            # Chunk nuovi solo in SQLite, nessun embedding automatico.
            prepare_documents(ingest_directory(incoming, registry), registry)
            report["indexing_required"] = True
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Esegui l'OCR locale e aggiorna SQLite.")
    mode.add_argument("--dry-run", action="store_true", help="Mostra le pagine candidate senza modifiche.")
    parser.add_argument("--limit", type=int, default=10, help="Massimo pagine OCR per esecuzione (default: 10).")
    parser.add_argument("--pdf", action="append", default=[], help="Limita l'operazione a un PDF; ripetibile.")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(refresh(ROOT, apply=args.apply, limit=args.limit,
                                 filenames=tuple(args.pdf)), ensure_ascii=False, indent=2))
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        parser.exit(1, f"OCR non completato: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
