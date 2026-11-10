"""Titoli editoriali verificati associati alle prove, senza invii esterni."""
from __future__ import annotations

import json
import re


def verified_article(metadata: dict) -> dict | None:
    """Mostra solo titoli verificati sull'estrazione, mai proposte non validate."""
    if metadata.get("article_title_verified") is not True:
        return None
    title = metadata.get("article_title")
    if not isinstance(title, str) or not 8 <= len(title.strip()) <= 220:
        return None
    title = " ".join(title.split())
    if any(ord(c) < 32 for c in title) or not title:
        return None
    pages = []
    try:
        raw = json.loads(metadata.get("article_pages_json", "[]"))
        if (isinstance(raw, list) and 1 <= len(raw) <= 80
                and all(type(value) is int and value >= 1 for value in raw)):
            pages = sorted(set(raw))
    except (TypeError, ValueError):
        pass
    return {"title": title, "pages": pages}


def source_articles(sources, metadata_by_id: dict) -> dict:
    result = {}
    for source in sources:
        item = metadata_by_id.get(source.chunk_id)
        verified = verified_article(item) if isinstance(item, dict) else None
        if verified is not None:
            result[source.id] = verified
    return result


def article_reference(article: dict) -> str:
    """Etichetta corta, indipendente da percorsi e ID tecnici."""
    title = article["title"]
    pages = article.get("pages") or []
    if not pages:
        return title
    if len(pages) == 1:
        return title + f" · pag. {pages[0]}"
    if len(pages) <= 5:
        return title + " · pagg. " + ", ".join(map(str, pages))
    return title + f" · {len(pages)} pagine"


def clean_source_articles(data, ids) -> dict:
    """Convalida i metadati serializzati prima di mostrarli dalla cronologia."""
    if not isinstance(data, dict) or not set(data).issubset(ids) or len(data) > 512:
        raise ValueError("Metadati articolo non validi.")
    validated = {}
    for key, entry in data.items():
        if not isinstance(entry, dict) or set(entry) != {"title", "pages"}:
            raise ValueError("Metadati articolo non validi.")
        title, pages = entry["title"], entry["pages"]
        if (not isinstance(title, str) or not 8 <= len(title.strip()) <= 220 or
                any(ord(c) < 32 for c in title) or not isinstance(pages, list) or
                len(pages) > 80 or any(type(n) is not int or n < 1 for n in pages) or
                pages != sorted(set(pages))):
            raise ValueError("Metadati articolo non validi.")
        validated[key] = {"title": title, "pages": pages}
    return validated


def duplicate_article_hit(candidate: dict, accepted: list[dict]) -> bool:
    """Accorpa esclusivamente chunk davvero ripetuti nello stesso articolo."""
    article_id = candidate.get("article_id")
    if not article_id:
        return False
    normalized = re.sub(r"\s+", " ", candidate.get("text", "")).strip().casefold()
    return any(
        previous.get("article_id") == article_id and
        re.sub(r"\s+", " ", previous.get("text", "")).strip().casefold() == normalized
        for previous in accepted
    )
