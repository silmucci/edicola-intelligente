"""Selezione dei passaggi per la sola Mappa, senza riscrivere i quotidiani.

Le frasi qui restituite sono sottostringhe originali di Source.text. Il
validatore continua a usare la Source originale integrale, mai il riassunto.
Questo consente di considerare più edizioni a parità di budget di prompt.
"""
from __future__ import annotations

import re

from edicola.knowledge_relevance import Topic, RELATION_CUES, terms


SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;])\s+|\n+")
IMPORTANT = re.compile(
    r"\b(?:approv\w*|deliber\w*|annunci\w*|finanzi\w*|stanzi\w*|"
    r"present\w*|discut\w*|incontr\w*|sosten\w*|promoss\w*|"
    r"chied\w*|previst\w*|entr\w*\s+in\s+vigor\w*|"
    r"investiment\w*|milion\w*|miliard\w*|vot\w*|"
    r"conseguenz\w*|impatto|critic\w*|dichiar\w*)\b", re.I
)


def map_excerpts(text: str, topic: str, *, budget: int = 1350, max_passages: int = 5,
                 verified_article_title: str = "", semantic_hit: bool = False) -> list[str]:
    """Sceglie segmenti pertinenti, con azioni e quantità salienti.

    Le citazioni restano letterali e non attraversano segmenti artificiali.
    """
    if not text.strip() or budget < 100 or max_passages < 1:
        return []
    # Passaggi già brevi restano integri: non ridurre contesto utile quando
    # non si risparmia spazio e preservare le citazioni testuali.
    if len(text) <= budget:
        return [text]
    matcher = Topic(topic)
    # Le continuazioni dell'articolo possono non ripetere il nome della
    # vicenda, ma riportare gli stanziamenti o le conseguenze principali.
    # Il titolo deve provenire dal verificatore dell'archivio.
    same_story = bool(verified_article_title and matcher.score(verified_article_title))
    title_words = terms(verified_article_title) if same_story else set()
    # Ricompone le righe tipografiche dei PDF: il validatore confronta
    # citazioni e fonti con gli stessi spazi normalizzati.
    from edicola.map_facts import original_sentences
    segments = list(original_sentences(text))
    candidates = []
    for index, segment in enumerate(segments):
        # Il modello deve vedere periodi leggibili, non pezzi tagliati a metà.
        if not 20 <= len(segment) <= budget:
            continue
        lexical = matcher.score(segment)
        # Una domanda generica come "Finanziamenti" può lasciare il focus
        # lessicale vuoto. In tal caso il ranking non deve premiare
        # qualunque frase irrilevante o ripetuta del quotidiano.
        explicitly_related = bool(terms(topic) & terms(segment))
        has_action = bool(RELATION_CUES.search(segment) or IMPORTANT.search(segment))
        numeric = bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(?:%|euro|milion\w*|miliard\w*|vot\w*)", segment, re.I))
        # La pertinenza non dipende da un elenco di verbi: un risultato
        # sportivo, una scoperta o una mostra possono essere altrettanto salienti.
        # Gli hit semantici sono candidati, sempre con citazioni originali.
        substantive = len(segment.split()) >= 7 and len(terms(segment)) >= 4
        title_overlap = len(terms(segment) & title_words) >= 2
        if lexical <= 0 and not ((same_story and (has_action or numeric or title_overlap))
                                 or (semantic_hit and substantive)):
            continue
        if not (explicitly_related or has_action or numeric or title_overlap
                or (semantic_hit and substantive)):
            continue
        verbs = len(RELATION_CUES.findall(segment)) + len(IMPORTANT.findall(segment))
        candidates.append((max(lexical, 1.0 if same_story else 0.0)
                           + min(verbs, 5) * 0.85 + (1.3 if numeric else 0),
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


def map_prompt_source(source, article, topic, *, excerpt_budget=1350,
                      semantic_hit=False):
    """Payload più compatto, fonte originale immutata per validate_map."""
    from edicola.article_evidence import evidence_source_record
    item = evidence_source_record(source, article, include_chunk=True)
    passages = map_excerpts(source.text, topic, budget=excerpt_budget,
                            verified_article_title=article.get("title", "") if article else "",
                            semantic_hit=semantic_hit)
    if passages:
        # Ogni elemento è già parte contigua del chunk originale. Esplicitiamo
        # i confini per impedire al modello di unire citazioni diverse.
        item["text"] = "\n\n".join(passages)
    else:
        # Non inoltrare al modello un intero chunk enorme privo di passaggi
        # selezionabili: verrà escluso dalla scelta delle fonti per la Mappa.
        item["text"] = source.text if len(source.text) <= excerpt_budget else ""
    item["excerpts_are_original"] = True
    return item
