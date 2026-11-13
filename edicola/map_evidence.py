"""Selezione dei passaggi per la sola Mappa, senza riscrivere i quotidiani.

Le frasi qui restituite sono sottostringhe originali di Source.text. Il
validatore continua a usare la Source originale integrale, mai il riassunto.
Questo consente di considerare più edizioni a parità di budget di prompt.
"""
from __future__ import annotations

import re

from edicola.knowledge_relevance import Topic, RELATION_CUES


SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;])\s+|\n+")
IMPORTANT = re.compile(
    r"\b(?:approv\w*|deliber\w*|annunci\w*|finanzi\w*|stanzi\w*|"
    r"present\w*|discut\w*|incontr\w*|sosten\w*|promoss\w*|"
    r"chied\w*|previst\w*|entr\w*\s+in\s+vigor\w*|"
    r"investiment\w*|milion\w*|miliard\w*|vot\w*|"
    r"conseguenz\w*|impatto|critic\w*|dichiar\w*)\b", re.I
)


def map_excerpts(text: str, topic: str, *, budget: int = 1350, max_passages: int = 5) -> list[str]:
    """Sceglie segmenti pertinenti, con azioni e quantità salienti.

    Le citazioni restano letterali e non attraversano segmenti artificiali.
    """
    if not text.strip() or budget < 100 or max_passages < 1:
        return []
    matcher = Topic(topic)
    segments = [item.strip() for item in SENTENCE_BOUNDARY.split(text) if item.strip()]
    candidates = []
    for index, segment in enumerate(segments):
        # Il modello deve vedere periodi leggibili, non pezzi tagliati a metà.
        if not 20 <= len(segment) <= budget:
            continue
        lexical = matcher.score(segment)
        if lexical <= 0:
            continue
        verbs = len(RELATION_CUES.findall(segment)) + len(IMPORTANT.findall(segment))
        numeric = bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(?:%|euro|milion\w*|miliard\w*|vot\w*)", segment, re.I))
        candidates.append((lexical + min(verbs, 5) * 0.85 + (1.3 if numeric else 0),
                           index, segment))
    if not candidates:
        # Se il tema appare soltanto nel contesto del paragrafo, conservare
        # un pezzo originale intero anziché creare un estratto arbitrario.
        return [text] if len(text) <= budget else []
    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected = []
    remaining = budget
    for _score, index, segment in candidates:
        if len(selected) >= max_passages or len(segment) + 2 > remaining:
            continue
        if any(segment == existing[1] for existing in selected):
            continue
        selected.append((index, segment))
        remaining -= len(segment) + 2
    return [segment for _index, segment in sorted(selected)]


def map_prompt_source(source, article, topic, *, excerpt_budget=1350):
    """Payload più compatto, fonte originale immutata per validate_map."""
    from edicola.article_evidence import evidence_source_record
    item = evidence_source_record(source, article, include_chunk=True)
    passages = map_excerpts(source.text, topic, budget=excerpt_budget)
    if passages:
        # Ogni elemento è già parte contigua del chunk originale. Esplicitiamo
        # i confini per impedire al modello di unire citazioni diverse.
        item["text"] = "\n\n".join(passages)
    else:
        item["text"] = source.text
    item["excerpts_are_original"] = True
    return item
