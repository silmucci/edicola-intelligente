"""Diagnostica PDF locale e in sola lettura; funziona anche sullo snapshot GitHub.

Esempio: python -m edicola.pdf_diagnostics --pdf 7ZycEw6ad2611b84bd0_full.pdf
Non chiama Gemini, non modifica l'archivio, i PDF o gli embedding.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from edicola.article_structure import infer_article_annotations
from edicola.ingestion import extract_pdf

ROOT = Path(__file__).resolve().parents[1]


def locate_pdf(root: Path, name: str) -> Path:
    if not name or name != Path(name).name:
        raise ValueError("Usare solo il nome del PDF, senza percorsi.")
    for directory in (root / "data/incoming", root / "deployment/seed/data/incoming"):
        path = directory / name
        if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".pdf":
            return path
    raise ValueError("PDF non trovato né in data/incoming né nello snapshot deployment/seed.")


def inspect_pdf(root: Path, name: str) -> dict:
    path = locate_pdf(root, name)
    result = extract_pdf(path.read_bytes())
    annotated = infer_article_annotations(result, "diagnostica")
    articles = []
    for number, labels in sorted(annotated.items()):
        item = labels[0]
        if item["role"] == "body":
            articles.append({"title": item["title"], "pages": item["article_pages"]})
    extracted = result.get("pages", [])
    methods = sorted({page.get("extraction_method", "unknown") for page in extracted})
    return {
        "pdf": path.name, "total_pages": result.get("total_pages", 0),
        "extraction_status": result.get("status", "error"),
        "extraction_methods": methods,
        "articles_recognized": len(articles),
        "article_pages": len(annotated),
        "continuation_pages": sum(
            entry[0]["role"] == "continuation" for entry in annotated.values()
        ),
        "unclassified_pages": [
            page.get("number") for page in extracted
            if page.get("number") not in annotated
        ],
        "articles": articles,
        "note": "Titoli e continuazioni sono ipotesi geometriche verificabili sul PDF, non una segmentazione garantita.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, help="Nome del quotidiano .pdf")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect_pdf(ROOT, args.pdf), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Diagnostica non completata: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
