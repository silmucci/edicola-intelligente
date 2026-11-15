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


_CAMELCASE = re.compile(r"(?<!\w)[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+[A-ZÀ-ÖØ-Þ]\w+(?!\w)")
_UPPER_NAME = re.compile(r"^(?:[A-ZÀ-ÖØ-Þ][\w’'-]+\s+){1,3}[A-ZÀ-ÖØ-Þ][\w’'-]+$")
def request_focus(topic: str) -> str | None:
    """Solo nomi propri identificabili, mai l'intero tema prima dei due punti.

    'Sicurezza sul lavoro: incidenti' non è un nome di iniziativa:
    restringere l'intero archivio a quella sequenza causava mappe vuote.
    """
    quoted = re.search(r"[«“\"]([^»”\"]{4,65})[»”\"]", topic)
    if quoted and quoted.group(1).casefold().strip() not in _GENERIC:
        return quoted.group(1).strip()
    named = _CAMELCASE.search(topic)
    if named and named.group().casefold() not in _GENERIC:
        return named.group()
    before, colon, _ = topic.partition(":")
    if not colon:
        return None
    candidate = " ".join(before.strip(" \"'«»“”").split())
    if (4 <= len(candidate) <= 65 and len(candidate.split()) <= 4
            and "," not in candidate
            and _UPPER_NAME.fullmatch(candidate)):
        return candidate
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


def _declared_article_pages(chunk):
    """Pagine dichiarate dal parsing dell'articolo, solo se titolo verificato."""
    if not _verified_title(chunk):
        return ()
    raw = chunk.metadata.get("article_pages_json", "[]")
    try:
        pages = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ()
    if not isinstance(pages, list) or len(pages) > 80:
        return ()
    if not all(type(page) is int and page >= 1 for page in pages):
        return ()
    return tuple(sorted(set(pages)))


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
    # Se l'articolo verificato prosegue su altre pagine, queste sono
    # candidati di recupero. Si escludono altri articoli identificati,
    # anche quando si trovano nello stesso foglio.
    article_pages = set()
    for match in direct:
        for page in _declared_article_pages(match):
            if page != match.metadata.get("page"):
                article_pages.add((match.metadata.get("filename"), page))
    selected = {c.id: c for c in direct}
    for chunk in chunks:
        key = _article_key(chunk)
        if key in article_keys and key is not None:
            selected[chunk.id] = chunk
            continue
        if (chunk.metadata.get("filename"), chunk.metadata.get("page")) not in article_pages:
            continue
        if key is not None and key not in article_keys:
            continue  # Un'altra identità articolo accertata.
        if chunk.metadata.get("article_id"):
            continue  # Non attribuire una prosecuzione ad altro articolo.
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
        if (chunk.metadata.get("filename"), chunk.metadata.get("page")) in article_pages:
            score += 5
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
