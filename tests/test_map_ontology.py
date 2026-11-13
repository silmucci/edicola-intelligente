"""Regressioni ontologia delle Mappe: provenienza, menzioni e identità."""
from copy import deepcopy

from edicola.map_ontology import enrich_map_with_provenance, link_entities
from edicola.knowledge_validation import map_dot
from edicola.rag import Source


TEXT_A = ("Il Senato ha approvato il disegno di legge ColtivaItalia. "
          "Lollobrigida ha illustrato il provvedimento durante una conferenza.")
TEXT_B = ("Il Senato torna a discutere ColtivaItalia nella seduta successiva.")
SOURCES = [
    Source("S1", "c1", "prima.pdf", 5, TEXT_A, 0.1),
    Source("S2", "c2", "seconda.pdf", 7, TEXT_B, 0.2),
]
COVERAGE = {"files": [
    {"pdf": "prima.pdf", "publication": "Quotidiano A", "date": "2026-11-05"},
    {"pdf": "seconda.pdf", "publication": "Quotidiano B", "date": "2026-11-07"},
]}


def data():
    return {
        "nodes": [
            {"id": "N1", "kind": "organization", "label": "Senato", "source_ids": ["S1", "S2"]},
            {"id": "N2", "kind": "proposal", "label": "disegno di legge ColtivaItalia",
             "source_ids": ["S1"]},
            {"id": "N3", "kind": "person", "label": "Lollobrigida", "source_ids": ["S1"]},
            {"id": "N4", "kind": "concept", "label": "ColtivaItalia", "source_ids": ["S1", "S2"]},
        ],
        "edges": [
            {"from_id": "N1", "to_id": "N2", "kind": "documented", "label": "ha approvato",
             "source_ids": ["S1"], "evidence": [{"source_id": "S1", "quote": TEXT_A}]}
        ],
    }


def test_ontology_makes_verified_article_and_grounded_mentions_without_inventing_actor_relation():
    original = data()
    articles = {"S1": {"title": "ColtivaItalia, approvazione al Senato", "pages": [5]}}
    graph = enrich_map_with_provenance(original, SOURCES, articles, COVERAGE)
    assert graph["edges"][0] == original["edges"][0]
    article = next(n for n in graph["nodes"] if n["kind"] == "article")
    assert article["label"] == articles["S1"]["title"]
    assert article["publication_date"] == "2026-11-05"
    assert article["source_ids"] == ["S1"]
    mentions = [e for e in graph["edges"] if e["kind"] == "mention"]
    assert mentions
    assert {e["to_id"] for e in mentions if e["from_id"] == article["id"]} >= {"N1", "N2", "N3"}
    for edge in mentions:
        assert edge["label"] == "menziona"
        assert len(edge["evidence"]) == 1
        item = edge["evidence"][0]
        assert item["quote"] in next(s.text for s in SOURCES if s.id == item["source_id"])
        assert edge["source_ids"] == [item["source_id"]]
    assert not any({e["from_id"], e["to_id"]} == {"N1", "N3"} for e in graph["edges"])
    assert graph is not original and original == data()
    dot = map_dot(graph)
    assert "style=dotted, dir=forward" in dot


def test_ontology_never_fakes_article_identity_when_title_is_not_verified():
    graph = enrich_map_with_provenance(data(), SOURCES, {}, COVERAGE)
    hubs = [n for n in graph["nodes"] if n["kind"] in {"article", "source"}]
    assert hubs and all(n["kind"] == "source" for n in hubs)
    assert all("Fonte" in n["label"] for n in hubs)
    assert {n["publication_date"] for n in hubs} <= {"2026-11-05", "2026-11-07"}


def test_ontology_does_not_make_edges_to_entities_absent_from_original_source():
    graph = data()
    graph["nodes"].append({"id": "N5", "kind": "person", "label": "Mario Rossi",
                           "source_ids": ["S1"]})
    result = enrich_map_with_provenance(graph, SOURCES, {}, COVERAGE)
    assert not any(edge["to_id"] == "N5" and edge["kind"] == "mention"
                   for edge in result["edges"])


def test_single_unrelated_mention_cannot_create_source_hub():
    only = {"nodes": [{"id": "N1", "kind": "organization", "label": "Senato",
                        "source_ids": ["S1"]}], "edges": []}
    result = enrich_map_with_provenance(only, SOURCES, {}, COVERAGE)
    assert result == only


def test_entity_linking_merges_surname_only_when_unique_and_from_same_source():
    sentence = "Francesco Lollobrigida dichiara che Lollobrigida presenterà il piano."
    raw = {
        "nodes": [
            {"id": "N1", "kind": "person", "label": {"text": "Francesco Lollobrigida",
                "evidence": [{"source_id": "S1", "quote": sentence}]}},
            {"id": "N2", "kind": "person", "label": {"text": "Lollobrigida",
                "evidence": [{"source_id": "S1", "quote": sentence}]}},
        ],
        "edges": [{"from_id": "N2", "to_id": "N1", "kind": "documented",
                   "label": {"text": "dichiara",
                   "evidence": [{"source_id": "S1", "quote": sentence}]}}],
    }
    original = deepcopy(raw)
    merged = link_entities(raw, SOURCES)
    assert [n["id"] for n in merged["nodes"]] == ["N1"]
    assert not merged["edges"]
    assert raw == original
    separate = deepcopy(raw)
    separate["nodes"][1]["label"]["evidence"][0]["source_id"] = "S2"
    assert len(link_entities(separate, SOURCES)["nodes"]) == 2


def test_article_metadata_is_not_transferred_from_another_pdf():
    graph = enrich_map_with_provenance(
        data(), SOURCES,
        {"S99": {"title": "Titolo non presente", "pages": [99]}},
        COVERAGE)
    assert all(n["kind"] != "article" for n in graph["nodes"])
