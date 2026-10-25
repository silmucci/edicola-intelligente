"""Task 14.3: pertinenza distinta dalle prove, con soli dati sintetici."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from google.genai import types
from streamlit.testing.v1 import AppTest

from edicola.archive import IndexChunk
from edicola.knowledge import KnowledgeResult, generate_knowledge
from edicola.knowledge_relevance import Topic, relevant_map, relevant_timeline, select_topic_chunks
from edicola.knowledge_validation import compact_map, map_dot, validate_map, validate_timeline
from edicola.rag import Source
from test_knowledge import COVERAGE, claim, setup_knowledge
from test_knowledge_exploration import installed_fixture, render_script
from test_navigation_editorial import archive, platform

QUESTION = "Quali misure economiche sono state proposte per sostenere le imprese di pesca contro il caro carburante?"
FISH = "Tra le proposte per le imprese di pesca contro il caro carburante figurano la proroga del credito di imposta e la modifica del bando ristori."
ROAD = "Confartigianato Trasporti Abruzzo chiede al Governo misure per gli autotrasportatori contro il caro carburante."


def example(mixed=False):
    sources = [Source("S1", "fish", "a.pdf", 2, FISH, .3), Source("S2", "road", "b.pdf", 1, ROAD, .1)]
    if mixed:
        sources = [Source("S1", "mixed", "a.pdf", 2, ROAD + " " + FISH, .1)]
    fish, road = sources[0], sources[-1]
    raw = {"nodes": [
        {"id": "N1", "kind": "organization", "label": claim("Confartigianato Trasporti Abruzzo", road)},
        {"id": "N2", "kind": "organization", "label": claim("Governo", road)},
        {"id": "N3", "kind": "proposal", "label": claim("proroga del credito di imposta", fish)},
        {"id": "N4", "kind": "proposal", "label": claim("modifica del bando ristori", fish)},
        {"id": "N5", "kind": "concept", "label": claim("imprese di pesca", fish)}],
        "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented", "label": claim("chiede al", road)}]}
    return raw, sources


@pytest.mark.parametrize("mixed", [False, True])
def test_documented_but_off_topic_edge_is_not_a_substitute_for_relevant_isolates(mixed):
    raw, sources = example(mixed)
    data, _ = validate_map(raw, sources)
    assert len(data["edges"]) == 1  # È verificata, ma non risponde alla domanda.
    selected, counts = relevant_map(data, raw, sources, Topic(QUESTION))
    assert {n["id"] for n in selected["nodes"]} == {"N3", "N4", "N5"}
    assert not selected["edges"] and not selected["context_edges"]
    assert counts["off_topic_nodes"] == 2 and counts["off_topic_edges"] == 1
    assert {n["id"] for n in compact_map(selected)["nodes"]} == {"N3", "N4", "N5"}


@pytest.mark.parametrize("question,good,bad", [
    (QUESTION, "La marineria propone un credito di imposta per i pescherecci.", ROAD),
    ("Quali aiuti per le imprese di pesca contro il costo del diesel?", FISH, ROAD),
    ("Come aiutare le scuole contro i rincari?", "Il piano per gli edifici scolastici prevede nuovi fondi.", "Il piano sanitario prevede fondi per la salute."),
    ("Finanziamenti nel Comune di Chieti", "A Chieti sono previsti nuovi fondi.", "A Pescara sono previsti nuovi fondi."),
    ("Come sostenere le imprese di pesca nel Comune di Chieti contro il caro carburante?", "A Chieti i pescatori chiedono ristori.", "A Chieti gli autotrasportatori chiedono ristori."),
    ("Come sostenere le imprese di pesca nel Comune di Chieti contro il caro carburante?", "A Chieti i pescatori chiedono ristori.", "A Pescara i pescatori chiedono ristori."),
    ("Quali aiuti per la filiera vitivinicola contro la siccità?", "Le aziende vitivinicole chiedono sostegno.", "Gli autotrasportatori chiedono sostegno."),
])
def test_general_subject_and_terminology_control(question, good, bad):
    topic = Topic(question)
    assert topic.score(good) > 0 and topic.score(bad) == 0


def test_local_indexed_candidates_can_recover_omitted_topic_without_api_or_pdf_quota():
    chunks = [IndexChunk(str(i), text, {"filename": name}) for i, (text, name) in enumerate(
        [(ROAD, "a.pdf"), (FISH, "b.pdf"), ("Le imprese di pesca chiedono sostegno per i ristori.", "b.pdf")])]
    selected = select_topic_chunks(Topic(QUESTION, chunks), chunks, [{"id": "0", "distance": .1}], 2)
    assert {c.id for c in selected} == {"1", "2"}
    assert all(c.metadata["filename"] == "b.pdf" for c in selected)


def test_generic_verified_predicate_stays_in_details_with_its_original_context():
    text = "L'associazione dei pescatori chiede al Governo un sostegno per le imprese di pesca."
    source = Source("S1", "fish", "a.pdf", 1, text, .1)
    raw = {"nodes": [{"id": "N1", "kind": "organization", "label": claim("associazione dei pescatori", source)},
                     {"id": "N2", "kind": "organization", "label": claim("Governo", source)}],
           "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented", "label": claim("chiede al", source)}]}
    data, _ = validate_map(raw, [source])
    selected, counts = relevant_map(data, raw, [source], Topic(QUESTION))
    assert not selected["edges"] and counts["context_only_edges"] == 1
    assert selected["context_edges"][0]["evidence"][0]["quote"] == text
    assert "chiede al" not in map_dot(selected)


def test_ranking_comes_before_degree_and_does_not_remove_an_isolated_priority_node():
    nodes = [{"id": f"N{i}", "label": f"Concetto {i}", "kind": "concept", "source_ids": ["S1"]} for i in range(12)]
    edges = [{"from_id": "N11", "to_id": n["id"], "kind": "documented", "label": "riguarda", "source_ids": ["S1"]} for n in nodes[:10]]
    data = {"nodes": nodes, "edges": edges}
    original = deepcopy(data)
    view = compact_map(data)
    assert [n["id"] for n in view["nodes"]] == [n["id"] for n in nodes[:10]]
    assert not view["edges"] and data == original


def test_relevance_can_use_only_verified_contiguous_relation_context():
    from test_map_context import adjacent_case
    raw, sources, contexts, _ = adjacent_case()
    topic = Topic("Finanziamenti nel Comune di Chieti")
    data, _ = validate_map(raw, sources, contexts=contexts)
    selected, _ = relevant_map(data, raw, sources, topic, contexts=contexts)
    assert len(selected["nodes"]) == 2 and len(selected["edges"]) == 1
    assert selected["edges"][0]["source_ids"] == ["S1", "S2"]
    assert selected["edges"][0]["evidence"] == data["edges"][0]["evidence"]
    contexts["S2"]["page"] = 999
    checked, _ = validate_map(raw, sources, contexts=contexts)
    restricted, _ = relevant_map(checked, raw, sources, topic, contexts=contexts)
    assert len(restricted["nodes"]) == 1 and not restricted["edges"]


@pytest.mark.parametrize("count", [2, 3, 5, 10])
def test_intrinsic_graph_size_and_readable_fonts_prevent_fitting_two_nodes_to_the_page(count):
    data = {"nodes": [{"id": f"N{i}", "label": f"Concetto verificato {i}", "kind": "concept", "source_ids": []}
                      for i in range(count)], "edges": []}
    dot = map_dot(data, grouping=True)
    assert "fontsize=12" in dot and "size=" not in dot.replace("fontsize=", "font=").replace("arrowsize=", "arrow=")
    result = KnowledgeResult("map", "Tema sintetico", data, [], COVERAGE)
    module, code = render_script(result)
    with installed_fixture(module):
        app = AppTest.from_string(code).run()
    assert not app.exception and not app.dataframe
    assert len(app.get("graphviz_chart")) == 1
    # Le impostazioni del layout sono nei messaggi del contenitore Streamlit;
    # la chiamata documentata non deve richiedere stretch o un'altezza forzata.
    with installed_fixture(module), patch("streamlit.graphviz_chart") as graph:
        AppTest.from_string(code).run()
    assert graph.call_args.kwargs["width"] == "content" and graph.call_args.kwargs["height"] == "content"


def test_timeline_subject_guard_does_not_change_verified_dates():
    sources = [Source("S1", "a", "a.pdf", 1, "Il 12 ottobre 2026 le imprese di pesca hanno presentato una proposta.", .1),
               Source("S2", "b", "b.pdf", 1, "Il 13 ottobre 2026 gli autotrasportatori hanno presentato una proposta.", .2)]
    events = [{"title": claim(s.text, s), "description": claim(s.text, s), "event_date": date,
               "date_evidence": {"source_id": s.id, "quote": s.text}} for s, date in zip(sources, ("2026-10-12", "2026-10-13"))]
    data, _ = validate_timeline({"events": events}, sources, COVERAGE)
    selected, excluded = relevant_timeline(data, sources, Topic(QUESTION))
    assert excluded == 1 and len(selected["events"]) == 1
    assert selected["events"][0] == data["events"][0] and selected["events"][0]["event_date"] == "2026-10-12"


def test_full_map_flow_uses_one_search_one_generation_and_versioned_cache(setup_knowledge, monkeypatch, caplog):
    root, catalog, client, _, search = setup_knowledge
    raw, sources = example()
    catalog.chunks = [IndexChunk(s.chunk_id, s.text, {"filename": s.filename, "page": s.page, "pdf_sha256": str(i) * 64}) for i, s in enumerate(sources)]
    search.return_value = [{"id": "road", "distance": .1}]
    # Il modello riceve la sola fonte pertinente, rinumerata S1.
    raw["nodes"] = raw["nodes"][2:]
    raw["edges"] = []
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(raw), candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    with caplog.at_level("INFO", logger="edicola.knowledge"):
        result = generate_knowledge("map", QUESTION, authorize_external=True, root=root, client=client)
    assert len(result.data["nodes"]) == 3 and result.sources[0].filename == "a.pdf"
    assert not search.call_args.kwargs["diversify_by_pdf"]
    assert ROAD not in client.models.generate_content.call_args.kwargs["contents"]
    assert FISH not in caplog.text and QUESTION not in caplog.text
    assert generate_knowledge("map", QUESTION, authorize_external=True, root=root, client=client).from_cache
    search.assert_called_once()
    client.models.generate_content.assert_called_once()
    monkeypatch.setattr("edicola.knowledge.MAP_VERSION", "next-map-only")
    assert not generate_knowledge("map", QUESTION, authorize_external=True, root=root, client=client).from_cache


def test_old_ram_map_is_not_shown_or_regenerated_after_strategy_change(archive):
    _, context, _ = archive
    with platform(context) as app, patch("edicola.knowledge.generate_knowledge") as generate:
        raw, sources = example()
        data, counts = validate_map(raw, sources)
        app.session_state["knowledge_results"] = {"map": KnowledgeResult("map", QUESTION, data, sources, COVERAGE, counts)}
        app.pills(key="nav_section").set_value("Mappe concettuali").run()
        assert not app.get("graphviz_chart") and not app.exception
        assert any("precedente va aggiornata" in item.value for item in app.info)
        generate.assert_not_called()
