"""Selezione locale delle notizie per 'Per te': nessuna generazione o inferenza AI."""

from collections import defaultdict
from dataclasses import dataclass
import html
import re

from edicola.article_evidence import verified_article
from edicola.editorial_selection import headline_priority
from edicola.personalization import recommend, tokens


@dataclass(frozen=True)
class FeedItem:
    chunk: object
    title: str
    preview: str
    topics: tuple[str, ...]
    verified_title: bool


def _shorten(text: str, limit: int) -> str:
    """Taglia solo tra parole, senza alterare il significato dell'originale."""
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[:cut if cut > 0 else limit].rstrip(" ,;:") + "…"


def _sentences(text: str) -> list[str]:
    """Scarta inizi di chunk tronchi e usa soltanto frasi complete."""
    plain = " ".join(html.unescape(text).split())
    parts = re.split(r'(?<=[.!?])\s+(?=[«“"\(]?[A-ZÀ-ÖØ-Þ])', plain)
    complete = []
    for part in parts:
        sentence = part.strip(" \t\r\n«»“”")
        if (len(sentence) < 45 or not sentence[0].isupper()
                or sentence[-1] not in ".!?"):
            continue
        complete.append(sentence)
    return complete


def _feed_item(chunk, topics: tuple[str, ...]) -> FeedItem | None:
    article = verified_article(chunk.metadata)
    sentences = _sentences(chunk.text)
    if article:
        title = article["title"]
        preview = next((sentence for sentence in sentences
                        if title.casefold() not in sentence.casefold()), "")
        return FeedItem(chunk, title, _shorten(preview, 175) if preview else "",
                        topics, True)
    if not sentences:
        # Evita estratti che cominciano a metà parola e titoli artificiali.
        return None
    return FeedItem(chunk, _shorten(sentences[0], 115),
                    _shorten(sentences[1], 175) if len(sentences) > 1 else "",
                    topics, False)


def _story_key(item: FeedItem) -> tuple:
    meta = item.chunk.metadata
    article = meta.get("article_id")
    if article and meta.get("pdf_sha256"):
        return ("article", meta["filename"], meta["pdf_sha256"], article)
    if item.verified_title:
        return ("title", meta["filename"], item.title.casefold())
    return ("chunk", item.chunk.id)


def select_feed(catalog, profile=None, *, topic: str = "", limit: int = 16) -> list[FeedItem]:
    """Priorità alle preferenze, poi alle edizioni recenti; nessuna quota fittizia.

    Confronta l'identità degli articoli solo dentro lo stesso PDF. Non usa
    il titolo o la somiglianza tematica per fondere aggiornamenti distinti.
    """
    if limit <= 0:
        return []
    chunks = catalog.chunks
    editions = {item["pdf"]: item for item in catalog.coverage.get("files", [])}
    interests = tuple(profile.interests) if profile else ()
    denied = [tokens(name) for name, value in (profile.feedback.items() if profile else ())
              if value == -1]
    wordsets = {chunk.id: tokens(chunk.text) for chunk in chunks}

    def matched(chunk):
        words = wordsets[chunk.id]
        if any(blocked and len(blocked & words) / len(blocked) >= 0.6 for blocked in denied):
            return ()
        return tuple(name for name in interests if tokens(name)
                     and len(tokens(name) & words) / len(tokens(name)) >= 0.6)

    # Il feed non modifica il ranking dei briefing personali già in uso.
    preferred = recommend(catalog, profile, limit=min(len(chunks), 120)) if interests else []
    preferred_scores = {item.chunk.id: item.score for item in preferred}
    prepared = []
    for chunk in chunks:
        topics = matched(chunk)
        if denied and any(blocked and len(blocked & wordsets[chunk.id]) / len(blocked) >= 0.6
                          for blocked in denied):
            continue
        if topic and topic not in topics:
            continue
        item = _feed_item(chunk, topics)
        if item is None:
            continue
        date = editions.get(chunk.metadata["filename"], {}).get("date") or ""
        prepared.append((item, date, preferred_scores.get(chunk.id, 0.0)))

    # I titoli verificati sono favoriti, ma una notizia recente e pertinente
    # precede un articolo vecchio soltanto perché ha un titolo.
    prepared.sort(key=lambda row: (
        bool(row[0].topics), row[1], row[2], row[0].verified_title,
        headline_priority(row[0].chunk),
        -row[0].chunk.metadata.get("position", 0),
    ), reverse=True)

    groups = defaultdict(list)
    for item, _, _ in prepared:
        groups[item.chunk.metadata["filename"]].append(item)

    # Un primo giro tra edizioni evita pagine piene di passaggi dallo stesso PDF.
    selected, seen, texts = [], set(), set()
    while groups and len(selected) < limit:
        for filename in list(groups):
            pool = groups[filename]
            while pool:
                item = pool.pop(0)
                key = _story_key(item)
                body = " ".join(item.chunk.text.casefold().split())
                if key in seen or body in texts:
                    continue
                seen.add(key)
                texts.add(body)
                selected.append(item)
                break
            if not pool:
                del groups[filename]
            if len(selected) >= limit:
                break
    return selected
