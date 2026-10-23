"""Prove distribuite tra chunk, senza fusioni arbitrarie o richieste esterne."""

from copy import deepcopy
from dataclasses import replace

import pytest

from edicola.archive import IndexChunk
from edicola.knowledge_validation import validate_map
from edicola.map_context import contiguous, select_map_chunks
from edicola.rag import Source


def adjacent_case():
    text = "Il Comune di Chieti stanzia oltre quattro milioni per la riqualificazione del viadotto cittadino."
    bounds = [(0, 60), (40, len(text))]
    chunks = [IndexChunk(f"chunk-{i}", text[start:end], {
        "filename": "giornale.pdf", "pdf_sha256": "a" * 64, "chunk_config": "verified-config",
        "page": 3, "position": i, "start": start, "end": end,
    }) for i, (start, end) in enumerate(bounds, 1)]
    sources = [Source(f"S{i}", c.id, "giornale.pdf", 3, c.text, 0.2) for i, c in enumerate(chunks, 1)]
    contexts = {s.id: c.metadata for s, c in zip(sources, chunks)}
    evidence = [{"source_id": s.id, "quote": s.text} for s in sources]
    raw = {"nodes": [
        {"id": "N1", "kind": "organization", "label": {"text": "Comune di Chieti", "evidence": [evidence[0]]}},
        {"id": "N2", "kind": "event", "label": {"text": "riqualificazione del viadotto cittadino", "evidence": [evidence[1]]}}],
        "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented", "predicate": "stanzia oltre quattro milioni per",
                   "label": {"text": "finanzia", "evidence": evidence}}]}
    return raw, sources, contexts, chunks


def test_financing_relation_is_verified_across_original_chunk_intervals():
    raw, sources, contexts, _ = adjacent_case()
    result, diagnostics = validate_map(raw, sources, contexts=contexts)
    assert diagnostics["candidate_edges"] == diagnostics["accepted_edges"] == 1
    assert diagnostics["rejected_edges"] == 0
    assert diagnostics["adjacent_edges"] == 1
    edge = result["edges"][0]
    assert edge["label"] == "stanzia oltre quattro milioni per"
    assert edge["source_ids"] == ["S1", "S2"]
    assert edge["evidence"] == raw["edges"][0]["label"]["evidence"]
    assert edge["adjacent_evidence"]
    assert diagnostics["labels_normalized"] == 1


@pytest.mark.parametrize("field,value", [("page", 4), ("pdf_sha256", "b" * 64), ("chunk_config", "different"),
                                       ("position", 3), ("start", 41), ("filename", "altro.pdf")])
def test_nearby_text_without_verified_document_continuity_is_not_joined(field, value):
    raw, sources, contexts, _ = adjacent_case()
    contexts["S2"][field] = value
    result, diagnostics = validate_map(raw, sources, contexts=contexts)
    assert not result["edges"]
    assert diagnostics["accepted_edges"] == 0 and diagnostics["rejected_edges"] == 1


def test_missing_intervening_quote_text_cannot_be_filled_in():
    raw, sources, contexts, _ = adjacent_case()
    raw["edges"][0]["label"]["evidence"] = [
        {"source_id": "S1", "quote": sources[0].text[:25]},
        {"source_id": "S2", "quote": sources[1].text[16:]},
    ]
    result, _ = validate_map(raw, sources, contexts=contexts)
    assert not result["edges"]


def test_overlap_must_match_exactly_even_when_node_names_match():
    raw, sources, contexts, _ = adjacent_case()
    sources[1] = replace(sources[1], text="X" + sources[1].text[1:])
    evidence = {"source_id": "S2", "quote": sources[1].text}
    raw["nodes"][1]["label"]["evidence"] = [evidence]
    raw["edges"][0]["label"]["evidence"][1] = evidence
    result, _ = validate_map(raw, sources, contexts=contexts)
    assert not result["edges"]


def test_adjacent_evidence_still_requires_an_actual_predicate():
    raw, sources, contexts, _ = adjacent_case()
    raw["edges"][0]["predicate"] = "causa il crollo di"
    result, diagnostics = validate_map(raw, sources, contexts=contexts)
    assert not result["edges"]
    assert diagnostics["edge_rejection_details"] == {"predicate_not_literal": 1}


def test_neighbor_selection_uses_only_supplied_indexed_chunks_and_respects_limit():
    _, _, _, chunks = adjacent_case()
    assert contiguous(*chunks)
    assert select_map_chunks([chunks[0]], chunks) == chunks
    assert select_map_chunks([chunks[0]], chunks, 0) == [chunks[0]]
    assert select_map_chunks([chunks[0]], [chunks[0]]) == [chunks[0]]
    assert select_map_chunks(chunks, chunks) == chunks  # Nessun duplicato dei seed.


def test_citations_with_invented_source_ids_are_not_joined():
    raw, sources, contexts, _ = adjacent_case()
    raw["edges"][0]["label"]["evidence"][1] = {"source_id": "N2", "quote": sources[1].text}
    result, diagnostics = validate_map(raw, sources, contexts=contexts)
    assert not result["edges"]
    assert diagnostics["edge_rejection_details"] == {"unknown_source": 1}


def test_candidates_generated_and_rejected_are_accounted_for_separately():
    raw, sources, contexts, _ = adjacent_case()
    empty = deepcopy(raw)
    empty["edges"] = []
    _, diagnostics = validate_map(empty, sources, contexts=contexts)
    assert diagnostics["relations_status"] == "none_generated"
    assert diagnostics["candidate_edges"] == diagnostics["accepted_edges"] == 0
    raw["edges"].append(deepcopy(raw["edges"][0]))
    raw["edges"][1]["to_id"] = "N99"
    raw["edges"].append(deepcopy(raw["edges"][0]))
    _, diagnostics = validate_map(raw, sources, contexts=contexts)
    assert diagnostics["candidate_edges"] == 3
    assert diagnostics["accepted_edges"] == 1 and diagnostics["rejected_edges"] == 2
    assert diagnostics["edge_rejection_details"] == {"unknown_endpoint": 1, "duplicate": 1}
    assert diagnostics["relations_status"] == "partial"
