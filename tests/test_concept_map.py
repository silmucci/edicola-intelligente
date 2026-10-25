"""Archi verificabili e selezione grafica compatta, senza API reali."""

from copy import deepcopy

import pytest

from edicola.knowledge_validation import compact_map, map_dot, validate_map
from edicola.rag import Source


def raw_map(text, relation="approva", left="Comune di Roma", right="piano", kind="documented"):
    source = Source("S1", "chunk-originale", "quotidiano.pdf", 3, text, 0.1)
    evidence = [{"source_id": "S1", "quote": text}]
    raw = {"nodes": [
        {"id": "N1", "kind": "organization", "label": {"text": left, "evidence": deepcopy(evidence)}},
        {"id": "N2", "kind": "concept", "label": {"text": right, "evidence": deepcopy(evidence)}}],
        "edges": [{"from_id": "N1", "to_id": "N2", "kind": kind,
                   "label": {"text": relation, "evidence": deepcopy(evidence)}}]}
    return raw, [source]


@pytest.mark.parametrize("text,relation,left,right", [
    ("Il Comune di Roma ha approvato il piano per i trasporti.", "approvato", "Comune di Roma", "piano"),
    ("Il Comune di Roma ha oggi approvato il piano per i trasporti.", "approvato", "Comune di Roma", "piano"),
    ("Il Comune di Roma, oggi, approva il piano per i trasporti.", "approva", "Comune di Roma", "piano"),
    ("Il Comune di Roma approva con delibera unanime il piano per i trasporti.", "approva", "Comune di Roma", "piano"),
    ("Il piano è stato approvato dal Comune di Roma per i trasporti.", "è stato approvato dal", "piano", "Comune di Roma"),
    ("Il piano, approvato dal Comune di Roma, riguarda i trasporti.", "approvato dal", "piano", "Comune di Roma"),
])
def test_documented_relation_allows_auxiliaries_modifiers_and_explicit_passive(text, relation, left, right):
    raw, sources = raw_map(text, relation, left, right)
    result, diagnostics = validate_map(raw, sources)
    assert len(result["edges"]) == 1
    edge = result["edges"][0]
    assert edge["source_ids"] == ["S1"]
    assert edge["evidence"] == [{"source_id": "S1", "quote": text}]
    assert edge["label"] == relation
    assert not diagnostics["edge_rejections"]


@pytest.mark.parametrize("text,relation,left,right", [
    ("Il Comune di Roma non approva il piano per i trasporti.", "approva", "Comune di Roma", "piano"),
    ("Il Comune di Roma potrebbe approvare il piano per i trasporti.", "approvare", "Comune di Roma", "piano"),
    ("Forse il Comune di Roma approva il piano per i trasporti.", "approva", "Comune di Roma", "piano"),
    ("Il Comune di Roma dice che la Regione approva il piano dei trasporti.", "approva", "Comune di Roma", "piano"),
    ("Il Comune di Roma commenta. La Regione approva il piano dei trasporti.", "approva", "Comune di Roma", "piano"),
    ("Il Comune di Roma parla del piano. Il sindaco approva altre misure.", "approva", "Comune di Roma", "piano"),
    ("Il Comune di Roma approva il piano per i trasporti.", "approva", "piano", "Comune di Roma"),
    ("Il piano è stato approvato dal Comune di Roma per i trasporti.", "approva", "Comune di Roma", "piano"),
    ("Il Comune di Roma discute del piano per i trasporti.", "causa", "Comune di Roma", "piano"),
    ("Il Comune di Roma commenta. La Regione approva il piano dei trasporti.", "commenta. La Regione approva", "Comune di Roma", "piano"),
    ("Il Comune di Roma dice che la Regione approva il piano dei trasporti.", "dice che la Regione approva", "Comune di Roma", "piano"),
])
def test_negation_hypothesis_other_actors_and_reversed_direction_are_not_links(text, relation, left, right):
    raw, sources = raw_map(text, relation, left, right)
    result, diagnostics = validate_map(raw, sources)
    assert len(result["nodes"]) == 2
    assert not result["edges"]
    assert diagnostics["edge_rejections"] == {"relation_not_explicit": 1}


def test_unknown_sources_and_inexact_quotes_have_distinct_diagnostics():
    raw, sources = raw_map("Il Comune di Roma approva il piano per i trasporti.")
    raw["edges"][0]["label"]["evidence"][0]["source_id"] = "N1"
    _, diagnostics = validate_map(raw, sources)
    assert diagnostics["edge_rejections"] == {"unknown_source": 1}
    raw["edges"][0]["label"]["evidence"][0] = {"source_id": "S1", "quote": "Citazione inventata che non è presente nel documento."}
    _, diagnostics = validate_map(raw, sources)
    assert diagnostics["edge_rejections"] == {"invalid_citation": 1}


def test_shared_theme_requires_two_explicit_theme_connections():
    text = "Il piano riguarda i trasporti. La commissione si occupa di trasporti."
    raw, sources = raw_map(text, "trasporti", "piano", "commissione", "thematic")
    result, diagnostics = validate_map(raw, sources)
    edge = result["edges"][0]
    assert edge["kind"] == "thematic" and edge["topic"] == "trasporti"
    assert edge["label"] == "associazione tematica"
    assert "dir=none" in map_dot(result)
    assert not diagnostics["rejected_edges"]


def test_same_article_and_shared_word_are_not_enough_for_theme_link():
    text = "Il piano dei trasporti è in discussione. La commissione si riunisce domani."
    raw, sources = raw_map(text, "trasporti", "piano", "commissione", "thematic")
    result, diagnostics = validate_map(raw, sources)
    assert not result["edges"]
    assert diagnostics["edge_rejections"] == {"theme_not_supported": 1}


def test_link_cites_only_the_evidence_that_proves_it_and_deduplicates():
    text = "Il Comune di Roma approva il piano per i trasporti."
    raw, sources = raw_map(text)
    sources.append(Source("S2", "other", "altro.pdf", 8, "Il Comune di Roma discute del piano per i trasporti.", 0.2))
    raw["edges"][0]["label"]["evidence"].append({"source_id": "S2", "quote": sources[1].text})
    raw["edges"].append(deepcopy(raw["edges"][0]))
    result, _ = validate_map(raw, sources)
    assert len(result["edges"]) == 1
    assert result["edges"][0]["source_ids"] == ["S1"]
    assert result["edges"][0]["evidence"] == [{"source_id": "S1", "quote": text}]


def large_map():
    return {"nodes": [{"id": f"N{i}", "label": f"Concetto {i} con una denominazione molto lunga da non espandere su una sola riga",
                       "kind": ["concept", "place", "event", "organization"][i % 4], "source_ids": ["S1"]}
                      for i in range(1, 17)],
            "edges": [{"from_id": f"N{i}", "to_id": f"N{i + 1}", "label": "riguarda",
                       "kind": "documented", "source_ids": ["S1"]} for i in range(2, 16)]}


def test_compact_layout_limits_nodes_wraps_labels_and_preserves_source_data():
    data = large_map()
    original = deepcopy(data)
    view = compact_map(data)
    assert len(view["nodes"]) == 10
    identities = {node["id"] for node in view["nodes"]}
    assert "N1" in identities  # L'isolato pertinente non scompare a favore degli archi.
    assert all({edge["from_id"], edge["to_id"]} <= identities for edge in view["edges"])
    assert data == original
    dot = map_dot(data)
    assert "rankdir=TB" in dot and "fontsize=12" in dot and "nodesep=0.22" in dot
    assert 'size="' not in dot and "\\n" in dot
    assert dot.count("fillcolor=") == 10
    for color in ("#F2F7FD", "#EDF5FF", "#FFF1F2", "#E6F0FF"):
        assert color in dot
    assert 'tooltip="Concetto' in dot and "[S1]" not in dot
    assert data == original  # I riferimenti restano nel risultato, non nell'etichetta.


def test_no_edges_returns_compact_concept_list():
    data = large_map()
    data["edges"] = []
    assert compact_map(data) == {"nodes": data["nodes"][:10], "edges": []}


def test_semantic_label_is_not_published_in_place_of_verified_financial_predicate():
    raw, sources = raw_map("Il Comune di Chieti stanzia oltre quattro milioni per le opere pubbliche cittadine.",
                           "finanzia", "Comune di Chieti", "opere pubbliche cittadine")
    raw["edges"][0]["predicate"] = "stanzia oltre quattro milioni per"
    result, diagnostics = validate_map(raw, sources)
    assert result["edges"][0]["label"] == "stanzia oltre quattro milioni per"
    assert diagnostics["labels_normalized"] == 1
    assert diagnostics["relations_status"] == "accepted"
    assert diagnostics["candidate_edges"] == diagnostics["accepted_edges"] == 1
    assert not result["edges"][0]["adjacent_evidence"]


def test_paraphrased_label_without_literal_predicate_has_specific_reason():
    raw, sources = raw_map("Il Comune di Chieti stanzia oltre quattro milioni per le opere pubbliche cittadine.",
                           "finanzia", "Comune di Chieti", "opere pubbliche cittadine")
    result, diagnostics = validate_map(raw, sources)
    assert not result["edges"]
    assert diagnostics["relations_status"] == "all_rejected"
    assert diagnostics["edge_rejection_details"] == {"predicate_not_literal": 1}
