"""Fatti dai titoli giornalistici, per le Mappe prive di triple esplicite.

Un titolo articolo verificato può contenere più proposizioni informative,
anche senza un verbo nella forma usata da un estrattore SVO. Le presenta
come *affermazioni riportate dal titolo*, NON come nessi causali o azioni
attribuite ad attori che il testo non documenta. Nessun LLM aggiuntivo.
"""
from __future__ import annotations

import re

from edicola.knowledge_relevance import Topic, terms


_LAYOUT = re.compile(r"\b(?:edizione\s+del|pagg?\.?\s*\d+|documento\s+dell['’]archivio)\b", re.I)
_SPLIT = re.compile(r"\s*[:;]\s*|\s+[\u2013\u2014]\s+")
_BAD = re.compile(r"^(?:questo|questa|questi|tale|un|una|il|la)\s+(?:articolo|misura|notizia)\b", re.I)


def headline_parts(title: str) -> list[str]:
    """Raccoglie un soggetto della notizia e almeno un dettaglio distinto."""
    title = " ".join(title.split()).strip(" .;,")
    if not 18 <= len(title) <= 220 or _LAYOUT.search(title):
        return []
    pieces = _SPLIT.split(title, maxsplit=1)
    if len(pieces) == 1 and ", " in title:
        pieces = title.split(", ", 1)
    if len(pieces) != 2:
        return []
    first, tail = (part.strip(" .;,'\"«»“”") for part in pieces)
    if not 9 <= len(first) <= 100 or len(tail) < 12:
        return []
    # Due dati nella stessa testata non dimostrano di per sé una
    # dipendenza: il titolo li sintetizza, senza introdurre causalità.
    details = [part.strip(" .;,'\"«»“”") for part in re.split(r",\s+", tail)]
    details = [d for d in details if 12 <= len(d) <= 115 and not _BAD.search(d)
               and not _LAYOUT.search(d)]
    if not details or _BAD.search(first):
        return []
    return [first, *details[:2]]


def reported_headline_facts(data: dict, sources: list, articles: dict, topic: str,
                            *, max_articles: int = 3) -> dict:
    """Fallback editoriale controllato, quando mancano relazioni informative.

    Qualsiasi arco ha la forma 'il titolo sintetizza', con quote esatta dal
    metadato *verificato* e puntatore al PDF. Non usa il titolo per inventare
    un'approvazione, un rapporto diretto o una conseguenza causale.
    """
    if any(edge.get("kind") in {"documented", "contextual"}
           for edge in data.get("edges", [])):
        return data
    matcher = Topic(topic)
    seen, ranked = set(), []
    for source in sources:
        article = articles.get(source.id)
        if not isinstance(article, dict):
            continue
        title = article.get("title", "")
        if not isinstance(title, str):
            continue
        key = (source.filename, " ".join(title.casefold().split()))
        if key in seen:
            continue
        seen.add(key)
        phrases = headline_parts(title)
        if not phrases:
            continue
        overlap = terms(topic) & terms(title)
        # Un'unica parola generica come 'lavoro' in un titolo altrimenti
        # estraneo non basta per aggiungere un ramo alla vicenda.
        if len(overlap) < min(2, len(terms(topic))) or matcher.score(title) <= 0:
            continue
        ranked.append((len(overlap), matcher.score(title), source, title, phrases))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2].id))
    if not ranked:
        return data
    nodes, edges = list(data.get("nodes", [])), list(data.get("edges", []))
    nxt = max((int(n["id"][1:]) for n in nodes
               if re.fullmatch(r"N\d+", n.get("id", ""))), default=0) + 1
    labels = {n["label"].casefold(): n["id"] for n in nodes
              if isinstance(n.get("label"), str)}
    accepted = 0
    for _overlap, _score, source, title, pieces in ranked:
        if accepted >= max_articles or len(nodes) >= 18:
            break
        identifiers = []
        for index, phrase in enumerate(pieces):
            key = phrase.casefold()
            if key not in labels:
                labels[key] = f"N{nxt}"
                nxt += 1
                nodes.append({"id": labels[key], "kind": "event" if index == 0 else "concept",
                              "label": phrase, "source_ids": [source.id],
                              "origin": "verified_article_headline"})
            identifiers.append(labels[key])
        if len(set(identifiers)) < 2:
            continue
        for detail_id in dict.fromkeys(identifiers[1:]):
            if len(edges) >= 28:
                break
            edges.append({"from_id": identifiers[0], "to_id": detail_id,
                          "kind": "contextual", "label": "sintetizza",
                          "source_ids": [source.id],
                          "evidence": [{"source_id": source.id, "quote": title}],
                          "context_scope": "verified_article_title"})
        accepted += 1
    if not accepted:
        return data
    return {**data, "nodes": nodes, "edges": edges}
