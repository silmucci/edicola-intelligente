"""Recupero specifico delle vicende per le sole Mappe concettuali.

Un nome o titolo specifico indicato nella domanda prevale su termini
generici come "approvazione", "misure" o "conseguenze". Recupera anche
passaggi della stessa identità di articolo quando sono verificati.
Non cambia ricerca vettoriale, indice o recupero di altri prodotti.
"""
from __future__ import annotations

from collections import Counter
import json
import re

from edicola.knowledge_relevance import RELATION_CUES, terms


_GENERIC = {
    "governo", "senato", "parlamento", "istituzioni", "economia", "politica",
    "agricoltura", "lavoro", "occupazione", "imprese", "ministero", "misure",
    "provvedimenti", "conseguenze", "approvazione", "protagonisti", "previsti",
    "previste", "notizie", "principali", "rapporti", "relazioni", "tema", "legge",
    "politici", "attori", "organizzazioni", "eventi", "italia", "italiano",
}


def request_focus(topic: str) -> str | None:
    """Riconosce un soggetto nominato, non una parola tematica generica."""
    before, colon, _ = topic.partition(":")
    if colon:
        candidate = " ".join(before.strip(" \"'«»“”").split())
        if (4 <= len(candidate) <= 65 and len(candidate.split()) <= 4
                and "," not in candidate and " e " not in candidate.casefold()
                and candidate.casefold() not in _GENERIC):
            return candidate
    named = re.search(r"(?<!\w)([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+\w*[A-ZÀ-ÖØ-Þ]\w+)(?!\w)", topic)
    if named and named.group(1).casefold() not in _GENERIC:
        return named.group(1)
    quoted = re.search(r"[«“\"]([^»”\"]{4,65})[»”\"]", topic)
    if quoted and quoted.group(1).casefold().strip() not in _GENERIC:
        return quoted.group(1).strip()
    return None


def _verified_title(chunk) -> str:
    meta = chunk.metadata
    title = meta.get("article_title")
    return title if meta.get("article_title_verified") is True and isinstance(title, str) else ""


def _article_key(chunk):
    """Non associare mai articoli appartenenti a PDF differenti."""
    metadata = chunk.metadata
    name = metadata.get("filename")
    article = metadata.get("article_id")
    if name and isinstance(article, str) and len(article) >= 8:
        return ("id", name, article)
    title = _verified_title(chunk)
    if name and title:
        return ("title", name, " ".join(title.casefold().split()))
    return None


def focused_map_seeds(topic, chunks, hits, *, fallback, limit=28):
    """Se il focus è documentato nell'archivio, esclude notizie generiche.

    Evidenze dirette: nome nel chunk O nel titolo verificato. Evidenze
    complementari: soltanto lo stesso articolo verificato, incluse
    continuazioni su pagine diverse. Mai un PDF intero come scorciatoia.
    """
    focus = request_focus(topic)
    if not focus:
        return list(fallback)
    expression = re.compile(r"(?<!\w)" + re.escape(focus) + r"(?!\w)", re.I)
    direct = [c for c in chunks if expression.search(c.text)
              or expression.search(_verified_title(c))]
    if not direct:
        return list(fallback)
    article_keys = {_article_key(c) for c in direct if _article_key(c) is not None}
    # Gli altri articoli delle stesse pagine non diventano automaticamente
    # pertinenti: si richiede identità editoriale specifica.
    selected = {c.id: c for c in direct}
    for chunk in chunks:
        if _article_key(chunk) in article_keys and _article_key(chunk) is not None:
            selected[chunk.id] = chunk
    positions = {h["id"]: i for i, h in enumerate(hits)}
    matched = terms(topic)
    relevance = []
    for chunk in selected.values():
        direct_text = bool(expression.search(chunk.text))
        direct_title = bool(expression.search(_verified_title(chunk)))
        hits_rank = positions.get(chunk.id)
        # Una prosecuzione priva del nome proprio può descrivere le misure
        # più importanti: non relegarla dopo notizie estranee.
        score = (30 if direct_text else 0) + (23 if direct_title else 0)
        score += 7 if _article_key(chunk) in article_keys else 0
        score += min(6, len(RELATION_CUES.findall(chunk.text)))
        score += min(7, len(terms(chunk.text) & matched))
        if hits_rank is not None:
            score += max(0, 3 - hits_rank / 10)
        relevance.append((score, chunk))
    relevance.sort(key=lambda entry: (-entry[0], entry[1].id))
    # Il nome proprio deve rimanere rappresentato. Integrare le
    # continuazioni con un limite per articolo e non per pagina generica.
    counts = Counter()
    kept = []
    for _, chunk in relevance:
        key = _article_key(chunk) or ("chunk", chunk.id)
        if counts[key] >= 8:
            continue
        kept.append(chunk)
        counts[key] += 1
        if len(kept) == limit:
            break
    return kept
