"""Selezione locale delle notizie per 'Per te': nessuna generazione o inferenza AI."""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
import html
import re

from edicola.archive import IndexChunk
from edicola.article_evidence import verified_article
from edicola.editorial_selection import headline_priority
from edicola.personalization import recommend, tokens


@dataclass(frozen=True)
class FeedItem:
    chunk: IndexChunk
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


def article_preview(chunk: IndexChunk) -> FeedItem | None:
    """Titolo verificato o frase completa, riutilizzabile nella rassegna."""
    return _feed_item(chunk, ())


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
    interest_words = {name: tokens(name) for name in interests}
    denied = [interest_words[name] for name, value in (profile.feedback.items() if profile else ())
              if value == -1 and name in interest_words]
    wordsets = {chunk.id: tokens(chunk.text) for chunk in chunks}

    def matched(words):
        return tuple(name for name, expected in interest_words.items()
                     if expected and len(expected & words) / len(expected) >= 0.6)

    def publication_date(chunk):
        value = editions.get(chunk.metadata["filename"], {}).get("date") or ""
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return ""

    # Il feed non modifica il ranking dei briefing personali già in uso.
    preferred = recommend(catalog, profile, limit=min(len(chunks), 120)) if interests else []
    preferred_scores = {item.chunk.id: item.score for item in preferred}
    prepared = []
    for chunk in chunks:
        words = wordsets[chunk.id]
        if any(blocked and len(blocked & words) / len(blocked) >= 0.6
               for blocked in denied):
            continue
        topics = matched(words)
        if topic and topic not in topics:
            continue
        item = _feed_item(chunk, topics)
        if item is None:
            continue
        prepared.append((item, publication_date(chunk), preferred_scores.get(chunk.id, 0.0)))

    # I titoli verificati sono favoriti, ma una notizia recente e pertinente
    # precede un articolo vecchio soltanto perché ha un titolo.
    prepared.sort(key=lambda row: (
        bool(row[0].topics), row[1], row[2], row[0].verified_title,
        headline_priority(row[0].chunk),
        -row[0].chunk.metadata.get("position", 0),
    ), reverse=True)

    groups = defaultdict(deque)
    for item, _, _ in prepared:
        groups[item.chunk.metadata["filename"]].append(item)

    # Un primo giro tra edizioni evita pagine piene di passaggi dallo stesso PDF.
    selected, seen, texts = [], set(), set()
    while groups and len(selected) < limit:
        for filename in list(groups):
            pool = groups[filename]
            while pool:
                item = pool.popleft()
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
