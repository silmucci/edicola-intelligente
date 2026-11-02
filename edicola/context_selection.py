"""Selezione comune in RAM: edizioni pertinenti, passaggi interi, budget globale."""

from collections import defaultdict, deque, Counter
import logging
logger = logging.getLogger(__name__)

VERSION = "corpus-context-v1"
MAX_DISTANCE = 0.65
DISTANCE_WINDOW = 0.20

COMPARISON_INSTRUCTION = """
Considera tutte e sole le fonti incluse. Accorpa contenuti sullo stesso tema o evento
solo quando le prove lo consentono. Distingui conferme, differenze e contraddizioni,
attribuendole alle rispettive fonti e citando le prove di ogni affermazione.
Non dedurre relazioni, causalità o date dalla somiglianza tematica. Non aggiungere
fonti irrilevanti per rappresentare tutte le edizioni e non dichiarare di avere
analizzato documenti non inclusi. Il campione può essere limitato dal contesto.
"""


def edition_order(items, *, filename=lambda item: item.filename):
    """Un contributo per PDF a ogni giro; conserva il ranking dentro ogni PDF."""
    groups = defaultdict(deque)
    for item in items:
        groups[filename(item)].append(item)
    while groups:
        for name in list(groups):
            yield groups[name].popleft()
            if not groups[name]:
                del groups[name]


def fit_context(items, render, budget, *, text_budget=None, max_source_chars=None):
    """Non tagliare i passaggi; saltare quelli grandi e provare anche i successivi."""
    items = list(items)
    kept, identities, chars, reasons = [], set(), 0, Counter()
    for item in edition_order(items):
        identity = (item.filename, item.chunk_id)
        if identity in identities or not item.text.strip():
            reasons["duplicate_or_empty"] += 1
            continue
        identities.add(identity)
        if max_source_chars is not None and len(item.text) > max_source_chars:
            reasons["source_size"] += 1
            continue
        if text_budget is not None and chars + len(item.text) > text_budget:
            reasons["source_budget"] += 1
            continue
        if len(render(kept + [item])) <= budget:
            kept.append(item)
            chars += len(item.text)
        else:
            reasons["prompt_budget"] += 1
    logger.info("phase=context_selection candidates=%d used=%d discarded=%d reasons=%s", len(items), len(kept), len(items)-len(kept), dict(reasons))
    return kept, render(kept)


def included_coverage(coverage, sources):
    """Metadati inviati al modello soltanto per i PDF effettivamente inclusi."""
    names = {source.filename for source in sources}
    return {**coverage, "files": [item for item in coverage.get("files", []) if item["pdf"] in names]}


def selection_coverage(coverage, candidates, sources):
    names = {source.filename for source in sources}
    candidate_names = {source.filename for source in candidates}
    return {**coverage, "context_selection": {
        "version": VERSION, "candidate_editions": len(candidate_names),
        "included_editions": len(names), "included_passages": len(sources),
        "omitted_editions": len(candidate_names - names),
        "omitted_passages": len(candidates) - len(sources)}}
