"""Preparazione editoriale opzionale dei PDF: Vision solo tramite CLI autorizzata.

Uso:
  python -m edicola.pdf_enrichment --dry-run
  python -m edicola.pdf_enrichment --pdf giornale.pdf --limit 3 --authorize-external

Non modifica le estrazioni o gli embedding esistenti.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from edicola.article_vision import (VISION_VERSION, cached_page, page_candidates,
                                    save_page, validate_vision_response)
from edicola.article_structure import infer_article_annotations
from edicola.embeddings import api_key
from edicola.ingestion import extract_pdf

ROOT = Path(__file__).resolve().parents[1]
PROMPT = """Analizza soltanto la struttura editoriale di questa pagina di quotidiano.
Restituisci SOLO JSON con una lista 'articles'. Per ogni articolo usa:
title (testo esatto del titolo visibile), section (se visibile),
importance (apertura, spalla, taglio basso, breve o altro),
continuation_page (numero intero solo se esplicitamente indicato, altrimenti null).
Non riscrivere, inventare o completare il testo degli articoli.
Non dedurre eventi, nomi o date. La struttura verra' verificata sul testo del PDF.
Se non puoi leggere titoli affidabili, usa articles: []."""


def _snapshot(registry: Path, digest: str, content: bytes) -> dict:
    if registry.is_file():
        try:
            with sqlite3.connect(registry.resolve().as_uri() + "?mode=ro", uri=True) as db:
                row = db.execute("SELECT result_json FROM extractions WHERE sha256 = ?", (digest,)).fetchone()
            if row:
                return json.loads(row[0])
        except (sqlite3.Error, ValueError):
            pass
    return extract_pdf(content)  # Locale; non scrive il registro.


def plan_pages(root: Path, *, filenames=(), maximum=4) -> tuple[list[dict], list[str]]:
    incoming = root / "data/incoming"
    registry = root / "data/archive.sqlite3"
    target = set(filenames)
    plans, warnings = [], []
    if not incoming.is_dir():
        return [], ["Cartella dei quotidiani non disponibile."]
    for path in sorted(incoming.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() != ".pdf":
            continue
        if target and path.name not in target:
            continue
        try:
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            result = _snapshot(registry, digest, content)
            text_pages = [item.get("text", "") for item in result.get("pages", [])]
            local_articles = infer_article_annotations(result, digest)
            # Non inviare a Vision pagine con un articolo già verificato
            # geometricamente: basta la prima pagina / layout complessi.
            candidates = [number for number in page_candidates(text_pages, maximum)
                          if number not in local_articles]
            if not candidates:
                warnings.append(f"{path.name}: nessuna pagina testuale utilizzabile.")
                continue
            plans.append({"filename": path.name, "sha256": digest, "pages": candidates,
                          "texts": text_pages, "total_pages": result.get("total_pages", 0),
                          "path": path})
        except (OSError, ValueError, KeyError):
            warnings.append(f"{path.name}: PDF non leggibile.")
    unknown = target - {item["filename"] for item in plans}
    for filename in sorted(unknown):
        warnings.append(f"{filename}: PDF non presente o privo di pagine selezionate.")
    return plans, warnings


def vision_request(client, model: str, path: Path, number: int, *, dpi=200):
    """Carica soltanto la pagina scelta; non invia il PDF completo."""
    import fitz
    from google.genai import types

    with fitz.open(path) as document:
        if not 1 <= number <= len(document):
            raise ValueError("Numero di pagina non valido.")
        png = document[number - 1].get_pixmap(dpi=dpi, alpha=False).tobytes("png")
    if len(png) > 15 * 1024 * 1024:
        raise ValueError("Immagine pagina troppo grande.")
    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_text(text=PROMPT),
                  types.Part.from_bytes(data=png, mime_type="image/png")],
        config=types.GenerateContentConfig(
            temperature=0, response_mime_type="application/json",
            max_output_tokens=4096))
    if not response.text:
        raise ValueError("Risposta Vision vuota.")
    return response.text


def execute(root: Path, *, dry_run: bool, authorize_external: bool,
            limit: int, maximum: int, model: str, filenames=(), client=None):
    if not dry_run and not authorize_external:
        raise ValueError("Richiesta autorizzazione esplicita prima di inviare immagini.")
    if limit <= 0 or maximum <= 0 or maximum > 20:
        raise ValueError("Limiti fuori intervallo.")
    planned, warnings = plan_pages(root, filenames=filenames, maximum=maximum)
    database = root / "data/editorial_pages.sqlite3"
    tasks, reused = [], 0
    for edition in planned:
        for page in edition["pages"]:
            text = edition["texts"][page - 1]
            if not text.strip():
                continue  # Non è possibile verificare un titolo senza testo locale.
            if cached_page(database, edition["sha256"], page, model, text) is not None:
                reused += 1
            else:
                tasks.append((edition, page, text))
    report = {"dry_run": dry_run, "model": model, "vision_version": VISION_VERSION,
              "editions": len(planned), "cached_pages": reused,
              "pending_pages": len(tasks), "selected_for_run": min(len(tasks), limit),
              "warnings": warnings, "completed": 0, "failed": 0}
    if dry_run or not tasks:
        return report
    owned = client is None
    try:
        if owned:
            from google import genai
            key = api_key(root)
            if not key:
                raise ValueError("Chiave Gemini non configurata.")
            client = genai.Client(api_key=key)
        for edition, number, text in tasks[:limit]:
            try:
                raw = vision_request(client, model, edition["path"], number)
                validated = validate_vision_response(raw, text, number, edition["total_pages"])
                save_page(database, edition["sha256"], number, model, text, validated)
                report["completed"] += 1
            except Exception:
                # Una singola pagina non deve impedire di elaborare le successive.
                report["failed"] += 1
    finally:
        if owned and client is not None:
            client.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Nessuna API e nessuna scrittura.")
    parser.add_argument("--authorize-external", action="store_true",
                        help="Autorizza l'invio a Gemini delle sole pagine selezionate.")
    parser.add_argument("--limit", type=int, default=4, help="Massimo pagine nuove da inviare.")
    parser.add_argument("--max-pages-per-pdf", type=int, default=4)
    parser.add_argument("--pdf", action="append", default=[], help="Nome PDF (ripetibile).")
    parser.add_argument("--model", default=os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash"))
    args = parser.parse_args(argv)
    try:
        report = execute(ROOT, dry_run=args.dry_run, authorize_external=args.authorize_external,
                         limit=args.limit, maximum=args.max_pages_per_pdf, model=args.model,
                         filenames=args.pdf)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["failed"] else 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        print("Preparazione interrotta: verificare PDF, limiti, autorizzazione e configurazione Gemini.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
