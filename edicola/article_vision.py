"""Metadati editoriali verificabili, isolati dall'estrazione e dagli embedding."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from edicola.chunking import clean_text

VISION_VERSION = "editorial-vision-v1"
PAGE_REFERENCE = re.compile(r"(?i)\\b(?:pag(?:ina|ine|\\.)?|p\\.)\\s*(\\d{1,3})\\b")
SECTION_WORDS = ("politica", "economia", "esteri", "sport", "cultura",
                 "tecnologia", "cronaca", "finanza", "salute", "scienza")
PRIORITY = {"apertura", "spalla", "taglio basso", "breve", "altro"}


def page_candidates(pages: list[str], maximum: int = 4) -> list[int]:
    """Prima pagina, richiami testuali reali, aperture di sezione. Numeri 1-based."""
    if maximum <= 0 or not pages:
        return []
    candidates = [1]
    for match in PAGE_REFERENCE.finditer(pages[0]):
        number = int(match.group(1))
        if 1 <= number <= len(pages) and number not in candidates:
            candidates.append(number)
    for number, text in enumerate(pages, 1):
        first_lines = [line.strip().casefold() for line in text.splitlines()[:12]]
        if number not in candidates and any(line in SECTION_WORDS for line in first_lines):
            candidates.append(number)
    return candidates[:maximum]


def _unique_heading(text: str, title: str):
    normalized = clean_text(title)
    if len(normalized) < 8 or len(normalized) > 220:
        return None
    pattern = re.compile(r"(?<!\\w)" + re.escape(normalized.casefold()) + r"(?!\\w)")
    positions = list(pattern.finditer(text.casefold()))
    return positions[0].span() if len(positions) == 1 else None


def validate_vision_response(raw, page_text: str, page: int, total_pages: int) -> dict:
    """La Vision propone metadati: titoli e richiami vengono confrontati col PDF."""
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict) or not isinstance(value.get("articles"), list):
        raise ValueError("Struttura della risposta Vision non valida.")
    if len(value["articles"]) > 40:
        raise ValueError("Troppi articoli nella risposta Vision.")
    text = clean_text(page_text)
    matches = []
    seen = set()
    for item in value["articles"]:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str):
            continue
        title = clean_text(item["title"])
        found = _unique_heading(text, title)
        if not found or found[0] in seen:
            continue
        seen.add(found[0])
        section = clean_text(item.get("section", "")) if isinstance(item.get("section"), str) else ""
        if section and section.casefold() not in text.casefold():
            section = ""
        importance = item.get("importance", "")
        if importance not in PRIORITY:
            importance = "altro"
        next_page = item.get("continuation_page")
        # Un riferimento di pagina proposto dal modello non prova una continuazione.
        if (type(next_page) is not int or not 1 <= next_page <= total_pages or
                next_page == page or
                not any(int(m.group(1)) == next_page for m in PAGE_REFERENCE.finditer(text))):
            next_page = None
        matches.append({"title": title, "start": found[0], "title_end": found[1],
                        "section": section, "importance": importance,
                        "continuation_page": next_page})
    matches.sort(key=lambda item: item["start"])
    for i, item in enumerate(matches):
        # Il limite è il successivo titolo verificato, mai una lunghezza arbitraria.
        item["end"] = matches[i + 1]["start"] if i + 1 < len(matches) else len(text)
    return {"page": page, "articles": matches, "version": VISION_VERSION}


def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS vision_pages (
        pdf_sha256 TEXT NOT NULL, page INTEGER NOT NULL,
        extraction_sha256 TEXT NOT NULL, model TEXT NOT NULL, version TEXT NOT NULL,
        result_json TEXT NOT NULL, saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(pdf_sha256, page, model, version)
    )""")
    db.commit()
    return db


def extraction_fingerprint(text: str) -> str:
    return hashlib.sha256(clean_text(text).encode("utf-8")).hexdigest()


def cached_page(path: Path, pdf_sha256: str, page: int, model: str, text: str):
    if not path.is_file():
        return None
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        try:
            row = db.execute("""SELECT result_json, extraction_sha256 FROM vision_pages
                WHERE pdf_sha256=? AND page=? AND model=? AND version=?""",
                (pdf_sha256, page, model, VISION_VERSION)).fetchone()
        except sqlite3.Error:
            return None
    if row and row[1] == extraction_fingerprint(text):
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return None
    return None


def save_page(path: Path, pdf_sha256: str, page: int, model: str,
              text: str, validated: dict):
    with _connect(path) as db:
        db.execute("""INSERT OR REPLACE INTO vision_pages
            (pdf_sha256, page, extraction_sha256, model, version, result_json)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (pdf_sha256, page, extraction_fingerprint(text), model, VISION_VERSION,
             json.dumps(validated, ensure_ascii=False)))


def read_annotations(path: Path, pdf_sha256: str, page_texts: dict[int, str]) -> dict[int, list[dict]]:
    """Sola lettura: niente chiamate API, niente metadati se testo/versione cambiano."""
    if not path.is_file():
        return {}
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            rows = db.execute("""SELECT page, extraction_sha256, result_json FROM vision_pages
                WHERE pdf_sha256=? AND version=? ORDER BY saved_at DESC, rowid DESC""",
                (pdf_sha256, VISION_VERSION)).fetchall()
    except sqlite3.Error:
        return {}
    result = {}
    for page, fingerprint, payload in rows:
        if page in result or page not in page_texts:
            continue
        if fingerprint != extraction_fingerprint(page_texts[page]):
            continue
        try:
            parsed = json.loads(payload)
            if parsed.get("version") != VISION_VERSION:
                continue
            result[page] = parsed.get("articles", [])
        except (ValueError, TypeError, AttributeError):
            continue
    # Connettere pagine diverse solo se entrambe hanno lo stesso titolo verificato.
    for page, articles in result.items():
        for item in articles:
            target = item.get("continuation_page")
            if target not in result:
                continue
            matching = [other for other in result[target]
                        if clean_text(other["title"]).casefold() == clean_text(item["title"]).casefold()]
            if len(matching) == 1:
                item["linked_page"] = target
                matching[0]["linked_page"] = page
    return result


def chunk_annotation(pdf_sha256: str, page: int, start: int, end: int,
                     annotations: dict[int, list[dict]]) -> dict:
    for item in annotations.get(page, []):
        if not (item["start"] <= start and end <= item["end"]):
            continue  # Non attribuire a un articolo chunk che attraversano confini.
        linked = item.get("linked_page")
        pages = sorted({page, linked} - {None})
        identity = clean_text(item["title"]).casefold() if linked else f"{page}:{item['start']}:{item['title']}"
        article_id = hashlib.sha256(f"{pdf_sha256}:{identity}".encode()).hexdigest()
        result = {"article_id": article_id, "article_title": item["title"],
                  "article_title_verified": True,
                  "article_importance": item["importance"],
                  "article_pages_json": json.dumps(pages)}
        if item.get("section"):
            result["article_section"] = item["section"]
        return result
    return {}
