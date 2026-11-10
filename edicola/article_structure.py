"""Riconoscimento locale e prudente di articoli su pagine editoriali semplici.

Usa solo i blocchi PyMuPDF già estratti: nessuna API, OCR o modello locale.
Non prova a segmentare prime pagine e pagine con più titoli dominanti.
"""
from __future__ import annotations

import hashlib
import re

from edicola.chunking import clean_text

LAYOUT_ARTICLES_VERSION = "single-article-layout-v1"


def _blocks(page: dict) -> list[dict]:
    if not str(page.get("extraction_method", "")).startswith("pymupdf-layout-"):
        return []
    blocks = page.get("blocks")
    if not isinstance(blocks, list):
        return []
    return [block for block in blocks if isinstance(block, dict)
            and isinstance(block.get("bbox"), list) and len(block["bbox"]) == 4
            and isinstance(block.get("text"), str)]


def _headline(page: dict, height: float) -> str | None:
    """Un titolo dominante nell'area superiore; i sottotitoli non bastano."""
    candidates = []
    for block in _blocks(page):
        y = float(block["bbox"][1])
        size = float(block.get("font_size", 0))
        text = clean_text(block["text"])
        if height * .055 <= y <= height * .42 and size >= 18 and 12 <= len(text) <= 250:
            candidates.append((size, text))
    if not candidates:
        return None
    largest = max(size for size, _ in candidates)
    dominant = [title for size, title in candidates if size >= max(23, largest * .78)]
    if len(dominant) != 1:
        return None
    title = dominant[0]
    # Il titolo deve esistere letteralmente nel testo indicizzabile.
    normalized = clean_text(page.get("text", ""))
    return title if normalized.casefold().count(title.casefold()) == 1 else None


def _continuation(page: dict, height: float, width: float) -> bool:
    """Pagina priva di titolo che inizia nel mezzo di una frase."""
    text = clean_text(page.get("text", ""))
    if len(text) < 350:
        return False
    blocks = _blocks(page)
    if not blocks:
        return False
    if any(float(b.get("font_size", 0)) >= 18 and
           height * .055 < float(b["bbox"][1]) < height * .7
           and len(clean_text(b["text"])) > 12 for b in blocks):
        return False
    left = sorted((b for b in blocks if height * .055 <= float(b["bbox"][1]) <= height * .3
                   and 0 <= float(b["bbox"][0]) < width * .55
                   and len(clean_text(b["text"])) >= 60),
                  key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
    if not left:
        return False
    opening = clean_text(left[0]["text"])
    return bool(re.match(r"^(?:[—–-]\s*)?[a-zà-öø-ÿ]", opening))


def infer_article_annotations(extraction: dict, pdf_sha256: str) -> dict[int, list[dict]]:
    """Gruppi di pagine intere con un titolo verificato e continuazioni conservative.

    Non altera testo, chunk, identificativi, citazioni o PDF. Senza geometria
    PyMuPDF non inventa metadati. La prima pagina resta non classificata.
    """
    pages = extraction.get("pages", [])
    result: dict[int, list[dict]] = {}
    groups: list[tuple[int, str, list[int]]] = []
    last_group: list[int] | None = None
    for index, page in enumerate(pages, 1):
        if index == 1 or not _blocks(page):
            last_group = None
            continue
        bbox = [b["bbox"] for b in _blocks(page)]
        width = max(float(b[2]) for b in bbox)
        height = max(float(b[3]) for b in bbox)
        if width <= 0 or height <= 0:
            last_group = None
            continue
        title = _headline(page, height)
        if title:
            last_group = [index]
            groups.append((index, title, last_group))
        elif last_group is not None and _continuation(page, height, width):
            last_group.append(index)
        else:
            last_group = None
    for start, title, linked_pages in groups:
        article_id = hashlib.sha256(
            f"{pdf_sha256}:{start}:{title.casefold()}".encode("utf-8")
        ).hexdigest()
        for page_number in linked_pages:
            text = clean_text(pages[page_number - 1].get("text", ""))
            if not text:
                continue
            result[page_number] = [{
                "title": title, "start": 0, "title_end": 0, "end": len(text),
                "section": "", "importance": "altro", "continuation_page": None,
                "article_id": article_id, "article_pages": linked_pages[:],
                "origin": LAYOUT_ARTICLES_VERSION,
                "role": "body" if page_number == start else "continuation",
            }]
    return result
