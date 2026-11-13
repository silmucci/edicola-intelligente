"""Fatti giornalistici ancorati alle fonti per le sole Mappe concettuali.

Funziona per qualunque rubrica: cronaca, sanità, lavoro, politica,
economia. Non attribuisce causalità, decisioni o ruoli assenti dalla
citazione; organizza passi *originali* appartenenti alla stessa notizia.
Un articolo verificato delimita la vicenda, non diventa una prova
sostitutiva del testo. In assenza di metadati, sono utilizzabili
soltanto frasi collegate all'interno dello stesso paragrafo.
"""
from __future__ import annotations

from collections import defaultdict
import re

from edicola.knowledge_relevance import Topic, terms

_CONTENT = re.compile(
    r"\b(?:approv\w*|respint\w*|bocciat\w*|vot\w*|"
    r"rinviat\w*|saltat\w*|salta|"
    r"annunc\w*|present\w*|decis\w*|decid\w*|"
    r"chied\w*|richiest\w*|sollecit\w*|"
    r"dichiar\w*|critic\w*|accus\w*|sosten\w*|"
    r"mobilit\w*|scioper\w*|trattativ\w*|"
    r"conciliazion\w*|accord\w*|contratt\w*|"
    r"incident\w*|mort\w*|vittim\w*|ferit\w*|"
    r"registrat\w*|risultat\w*|"
    r"preved\w*|previst\w*|stanziat\w*|finanziat\w*|"
    r"conseguenz\w*|effett\w*|impatto|"
    r"milion\w*|miliard\w*|percentual\w*)\b",
    re.I,
)
_EDITORIAL = re.compile(
    r"\b(?:edizione\s+del|quotidiano|pagina\s+\d+|pagg?\.?\s*\d+)\b",
    re.I,
)
_NEUTRAL = {"notizi", "giornal", "ital", "italia", "edizion",
            "princip", "protagonist", "tema", "intervent", "previst",
            "misur", "conseguenz", "rapport", "relazion"}


def _parts(text):
    """Frasi contigue: normalizzazione whitespace senza ricostruire fatti."""
    for paragraph in re.split(r"\n\s*\n+", text):
        normalized = " ".join(paragraph.split()).strip()
        if not normalized:
            continue
        sentences = [part.strip() for part in re.split(r"(?<=[.!?;])\s+", normalized)
                     if part.strip()]
        yield sentences


def _meaningful(sentence):
    return (38 <= len(sentence) <= 195
            and len(sentence.split()) >= 7
            and not _EDITORIAL.search(sentence)
            and bool(_CONTENT.search(sentence) or re.search(r"\b\d+(?:[.,]\d+)?\b", sentence)))


def _similar(a, b):
    first, second = terms(a), terms(b)
    return bool(first and second and len(first & second) / max(1, min(len(first), len(second))) >= .78)


def _unique_title(articles, source):
    article = articles.get(source.id) if isinstance(articles, dict) else None
    if not isinstance(article, dict) or not isinstance(article.get("title"), str):
        return ""
    return " ".join(article["title"].split()).strip()


def _source_records(sources, articles, topic, *, max_stories):
    matcher = Topic(topic)
    stories = defaultdict(list)
    for source in sources:
        title = _unique_title(articles, source)
        if not title or matcher.score(title) <= 0:
            continue
        story_id = (source.filename, title.casefold())
        stories[story_id].append((source, title))
    ranked = []
    for key, members in stories.items():
        title = members[0][1]
        title_terms = terms(title) - _NEUTRAL
        candidates = []
        for source, _ in members:
            for paragraph in _parts(source.text):
                for passage in paragraph:
                    if not _meaningful(passage):
                        continue
                    overlap = terms(passage) & title_terms
                    topical = matcher.score(passage)
                    if not overlap and topical <= 0:
                        continue
                    score = (3 * len(overlap) + min(topical, 8)
                             + 2 * bool(_CONTENT.search(passage))
                             + bool(re.search(r"\b\d+", passage)))
                    candidates.append((score, source, passage))
        candidates.sort(key=lambda x: -x[0])
        picked = []
        for score, source, passage in candidates:
            if any(_similar(passage, old) for _, _, old in picked):
                continue
            picked.append((score, source, passage))
            if len(picked) == 3:
                break
        if picked:
            ranked.append((max(item[0] for item in picked), key, title, picked))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return ranked[:max_stories]


def verified_news_relations(data, sources, articles, topic, *,
                            max_stories=3, max_statements=8):
    """Integra un fatto/contesto per notizie non riconosciute come triple.

    Un titolo verificato identifica il gruppo; la prova del contenuto è
    esclusivamente la citazione testuale presente nel chunk originale.
    """
    if not sources or max_stories < 1 or max_statements < 1:
        return data
    groups = _source_records(sources, articles, topic, max_stories=max_stories)
    if not groups:
        return data
    nodes, edges = list(data.get("nodes", [])), list(data.get("edges", []))
    next_id = max((int(node["id"][1:]) for node in nodes
                   if re.fullmatch(r"N\d+", str(node.get("id", "")))), default=0) + 1
    added = 0
    for _rank, _key, title, statements in groups:
        selected = statements[:max(0, max_statements - added)]
        if not selected:
            break
        hub_id = f"N{next_id}"
        next_id += 1
        distinct_ids = list(dict.fromkeys(src.id for _, src, _ in selected))
        nodes.append({"id": hub_id, "kind": "event", "label": title,
                      "source_ids": distinct_ids,
                      "origin": "verified_article_story"})
        for _score, source, passage in selected:
            detail_id = f"N{next_id}"
            next_id += 1
            nodes.append({"id": detail_id, "kind": "concept", "label": passage,
                          "source_ids": [source.id],
                          "origin": "literal_news_statement"})
            edges.append({"from_id": hub_id, "to_id": detail_id,
                          "kind": "contextual", "label": "riporta",
                          "source_ids": [source.id],
                          "evidence": [{"source_id": source.id, "quote": passage}],
                          "context_scope": "same_verified_article"})
            added += 1
    return {**data, "nodes": nodes, "edges": edges} if added else data


def same_paragraph_relations(data, sources, topic, *, max_stories=2):
    """Ultima riserva per articoli senza titolo verificato.

    Richiede due passi informativi nello stesso paragrafo, entrambi
    pertinenti alla richiesta e con termini non banali in comune.
    Non unisce mai frasi di pagine o paragrafi differenti.
    """
    if data.get("edges"):
        return data
    matcher = Topic(topic)
    nodes, edges = list(data.get("nodes", [])), list(data.get("edges", []))
    next_id = max((int(n["id"][1:]) for n in nodes if re.fullmatch(r"N\d+", str(n.get("id", "")))), default=0) + 1
    groups = 0
    for source in sources:
        if groups >= max_stories:
            break
        for paragraph in _parts(source.text):
            good = [p for p in paragraph if _meaningful(p) and matcher.score(p) > 0]
            if len(good) < 2:
                continue
            primary = good[0]
            partner = next((p for p in good[1:]
                            if (terms(primary) & terms(p)) - _NEUTRAL
                            and not _similar(primary, p)), None)
            if not partner:
                continue
            primary_id, secondary_id = f"N{next_id}", f"N{next_id+1}"
            next_id += 2
            nodes.extend([
                {"id": primary_id, "kind": "event", "label": primary,
                 "source_ids": [source.id], "origin": "literal_paragraph_fact"},
                {"id": secondary_id, "kind": "concept", "label": partner,
                 "source_ids": [source.id], "origin": "literal_paragraph_fact"},
            ])
            edges.append({
                "from_id": primary_id, "to_id": secondary_id,
                "kind": "contextual", "label": "stesso passaggio",
                "source_ids": [source.id],
                "evidence": [{"source_id": source.id, "quote": primary},
                             {"source_id": source.id, "quote": partner}],
                "context_scope": "same_source_paragraph",
            })
            groups += 1
            break
    return {**data, "nodes": nodes, "edges": edges} if groups else data
