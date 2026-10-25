"""Task 14.1: sintassi italiana e dati sintetici, mai richieste Gemini reali."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from google.genai import types
from streamlit.testing.v1 import AppTest

from edicola.archive import IndexChunk
from edicola.knowledge import KnowledgeResult, KnowledgeError, generate_knowledge
from edicola.knowledge_validation import validate_timeline, validate_map, map_dot
from edicola.map_relations import documented_relation
from edicola.proposal_extraction import proposal_items
from edicola.rag import Source
from test_knowledge import COVERAGE, SOURCES, claim, setup_knowledge, event
from test_knowledge_exploration import render_script, installed_fixture
from test_pdf_viewer import archive


TEXT = "Tra le proposte presentate al Governo la proroga del credito di imposta; la sospensione dei pagamenti dei mutui."
SOURCE = Source("S1", "synthetic", "a.pdf", 1, TEXT, .1)


def concept_map(source=SOURCE):
    raw = {"nodes": [{"id": "N1", "kind": "proposal", "label": claim("proroga del credito di imposta", source)},
                     {"id": "N2", "kind": "proposal", "label": claim("sospensione dei pagamenti dei mutui", source)}], "edges": []}
    data, diagnostics = validate_map(raw, [source])
    return KnowledgeResult("map", "Misure per le imprese", data, [source], COVERAGE, diagnostics)


def test_concept_only_map_is_visual_but_has_no_factual_or_decorative_edges():
    result = concept_map()
    dot = map_dot(result.data, topic=result.topic, grouping=True)
    assert '"N1"' in dot and '"N2"' in dot
    assert "->" not in dot and not result.data["edges"]
    module, code = render_script(result)
    with installed_fixture(module), patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
        assert not app.exception and len(app.get("graphviz_chart")) == 1
        assert any("senza relazioni documentate" in c.value for c in app.caption)
        app.segmented_control(key="knowledge_map_view").set_value("Elenco").run()
        assert not app.exception and not app.get("graphviz_chart") and app.dataframe
        api.assert_not_called()


@pytest.mark.parametrize("sources,diagnostics,expected", [
    ([], {"status": "no_sources"}, "Non ho trovato passaggi"),
    ([SOURCE], {"candidate_events": 0, "rejected_events": 0}, "non emergono eventi o sviluppi documentati"),
    ([SOURCE], {"candidate_events": 2, "rejected_events": 2}, "non consentono una ricostruzione affidabile"),
])
def test_timeline_empty_messages_match_the_actual_phase(sources, diagnostics, expected):
    result = KnowledgeResult("timeline", "Tema test", {"events": [], "undated_events": []}, sources, COVERAGE, diagnostics)
    module, code = render_script(result)
    with installed_fixture(module), patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
    assert not app.exception and len(app.info) == 1 and expected in app.info[0].value
    assert not app.warning and not app.get("graphviz_chart")
    api.assert_not_called()


def test_nominal_enumeration_produces_only_literal_complete_undated_items():
    items = proposal_items([SOURCE])
    assert len(items) == 2
    assert items[0]["title"]["text"] != items[1]["title"]["text"]
    data, diagnostics = validate_timeline({"events": items}, [SOURCE], COVERAGE)
    assert len(data["undated_events"]) == 2 and not data["events"]
    assert diagnostics["candidate_events"] == 2
    for item in data["undated_events"]:
        assert item["development_kind"] == "proposal" and item["event_date"] is None
        assert item["source_ids"] == ["S1"] and item["evidence"][0]["quote"] in TEXT
    assert "proroga" in data["undated_events"][0]["title"]
    assert "sospensione" in data["undated_events"][1]["title"]


@pytest.mark.parametrize("text", [
    "Non figurano tra le proposte presentate al Governo la sospensione dei mutui.",
    "Tra le proposte presentate al Governo la sospensione dei mutui",  # Confine non completo.
    "Si parla di credito di imposta e di mutui nello stesso articolo.",
    "Tra le proposte presentate al Governo la modifica non riguarda il credito di imposta.",
])
def test_enumeration_never_completes_fragments_or_ignores_negations(text):
    source = Source("S1", "synthetic", "a.pdf", 1, text, .1)
    assert not proposal_items([source])


def test_deadline_of_proposed_measure_is_not_an_event_date():
    text = "Tra le proposte presentate al Governo la proroga fino al 31 dicembre 2026 del credito di imposta."
    source = Source("S1", "synthetic", "a.pdf", 1, text, .1)
    item = {"title": claim("Proroga del credito", source), "description": claim(text, source),
            "event_date": "2026-12-31", "date_evidence": {"source_id": "S1", "quote": text}}
    data, _ = validate_timeline({"events": [item]}, [source], COVERAGE)
    assert not data["events"]
    assert data["undated_events"][0]["date_reason"] == "deadline_reference"
    assert "31 dicembre 2026" in data["undated_events"][0]["description"]


@pytest.mark.parametrize("text,valid", [
    ("La modifica dei criteri del Bando (ex 5.68) per il ristoro alle imprese è una proposta.", True),
    ("La modifica dei criteri del Bando (un altro soggetto) per il ristoro alle imprese è una proposta.", False),
    ("Non è prevista la modifica dei criteri del Bando (ex 5.68) per il ristoro alle imprese.", False),
    ("Sarebbe prevista la modifica dei criteri del Bando (ex 5.68) per il ristoro alle imprese.", False),
])
def test_numeric_parenthesis_is_allowed_without_skipping_actors_or_modality(text, valid):
    assert documented_relation("modifica dei criteri del Bando", "per", "ristoro alle imprese", text) is valid


def test_reported_attribution_and_conditional_are_not_rewritten_as_facts():
    text = "Secondo la nota, il Comune propone il sostegno alle imprese di pesca contro il caro carburante."
    source = Source("S1", "synthetic", "a.pdf", 1, text, .1)
    raw = {"nodes": [{"id": "N1", "kind": "organization", "label": claim("Comune", source)},
                     {"id": "N2", "kind": "measure", "label": claim("sostegno alle imprese di pesca", source)}],
           "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented", "label": claim("propone", source)}]}
    data, _ = validate_map(raw, [source])
    assert data["edges"][0]["label"] == "propone"
    assert data["edges"][0]["evidence"][0]["quote"].startswith("Secondo la nota")
    assert not documented_relation("Comune", "avrebbe approvato", "sostegno", "Il Comune avrebbe approvato il sostegno.")


def test_valid_empty_ai_output_can_use_local_verified_enumeration_and_cache(setup_knowledge):
    root, catalog, client, _, search = setup_knowledge
    chunk = IndexChunk("nominal", TEXT, {**catalog.chunks[0].metadata, "page": 1})
    catalog.chunks = [chunk]
    search.return_value = [{"id": chunk.id, "distance": .1}]
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text='{"events":[]}', candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    result = generate_knowledge("timeline", "Misure economiche", authorize_external=True, root=root, client=client)
    assert result.diagnostics["candidate_events"] == 0
    assert result.diagnostics["extracted_developments"] == 2
    assert result.diagnostics["rejected_events"] == 0 and len(result.data["undated_events"]) == 2
    assert generate_knowledge("timeline", "Misure economiche", authorize_external=True, root=root, client=client).from_cache
    search.assert_called_once()
    client.models.generate_content.assert_called_once()


def test_wrong_product_in_cache_fails_without_regeneration(setup_knowledge):
    root, _, client, _, search = setup_knowledge
    generate_knowledge("timeline", "Test cache", authorize_external=True, root=root, client=client)
    path = next((root / "data/knowledge_cache").glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["kind"] = "map"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="Cache non coerente"):
        generate_knowledge("timeline", "Test cache", authorize_external=True, root=root, client=client)
    search.assert_called_once()
    client.models.generate_content.assert_called_once()


@pytest.mark.parametrize("failure", ["api", "json"])
def test_local_extraction_does_not_mask_api_or_format_errors(setup_knowledge, failure):
    root, catalog, client, _, search = setup_knowledge
    chunk = IndexChunk("nominal", TEXT, catalog.chunks[0].metadata)
    catalog.chunks = [chunk]
    search.return_value = [{"id": chunk.id, "distance": .1}]
    client.models.generate_content.side_effect = None
    if failure == "api":
        from google.genai import errors
        client.models.generate_content.side_effect = errors.ClientError(400, {"error": {"message": "invalid request"}})
    else:
        client.models.generate_content.return_value = SimpleNamespace(text="not json", candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    with pytest.raises(KnowledgeError):
        generate_knowledge("timeline", "Misure", authorize_external=True, root=root, client=client)
    client.models.generate_content.assert_called_once()
    assert not list((root / "data/knowledge_cache").glob("*.json"))


def test_local_enumeration_never_joins_incomplete_chunks():
    sources = [Source("S1", "first", "a.pdf", 1,
                      "Tra le proposte presentate al Governo la sospensione dei", .1),
               Source("S2", "second", "a.pdf", 1, "pagamenti dei mutui.", .1)]
    assert not proposal_items(sources)


def test_empty_map_and_grouping_reference_open_current_pdf(archive):
    context, prepared = archive
    chunk = next(p for p in prepared if p.filename == "a.pdf").chunks[-1]
    source = Source("S1", chunk.id, "a.pdf", chunk.page, chunk.text, .1)
    raw = {"nodes": [{"id": "N1", "kind": "concept", "label": claim("Seconda", source)}], "edges": []}
    data, diagnostics = validate_map(raw, [source])
    result = KnowledgeResult("map", "Tema di navigazione", data, [source], COVERAGE, diagnostics)
    module, code = render_script(result, context)
    with installed_fixture(module), patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
        app.button(key="map_node_N1_pdf_S1").click().run()
        assert app.session_state["archive_page"] == chunk.page and not app.exception
        api.assert_not_called()
    result.data = {"nodes": [], "edges": []}
    with installed_fixture(module):
        empty = AppTest.from_string(code).run()
    assert not empty.exception and not empty.get("graphviz_chart") and len(empty.info) == 1
