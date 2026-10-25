"""Task 14: esplorazione documentale e UI con sole API simulate."""

import json
import sys
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola.knowledge import KnowledgeResult, generate_knowledge
from edicola.knowledge_validation import validate_timeline, validate_map, map_dot, map_focus
from edicola.knowledge_presentation import strict_chronology
from edicola.rag import Source
from edicola.archive import IndexChunk
from edicola.map_context import contiguous, select_map_chunks
from edicola.knowledge_components import CSS
from test_knowledge import COVERAGE, claim, setup_knowledge, event, SOURCES
from test_map_context import adjacent_case
from test_pdf_viewer import archive


@contextmanager
def installed_fixture(module):
    # Ripristina solo questa voce: non rimuove import lazy Pandas/Arrow del browser.
    name = "edicola.exploration_fixture"
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def development(text, date=None):
    source = Source("S1", "chunk", "a.pdf", 1, text, .1)
    item = {"title": claim("Misure per la pesca", source), "description": claim(text, source),
            "event_date": date, "date_evidence": None if date is None else {"source_id": "S1", "quote": text}}
    data, diagnostics = validate_timeline({"events": [item]}, [source], COVERAGE)
    return source, data, diagnostics


@pytest.mark.parametrize("text,category,status", [
    ("L'associazione propone un credito di imposta per le imprese di pesca contro il caro carburante.", "proposal", "undetermined"),
    ("Il Comune ha approvato il sostegno alle imprese di pesca contro il caro carburante.", "decision", "occurred"),
    ("Il sostegno alle imprese di pesca è annunciato ma senza una data per l'avvio.", "announced", "announced"),
    ("Il tavolo con le imprese di pesca si è svolto per discutere il costo del carburante.", "fact", "occurred"),
    ("Le imprese di pesca e il caro carburante sono citati nella pagina del quotidiano.", "undetermined", "undetermined"),
])
def test_undated_documented_developments_keep_evidence_without_borrowing_publication(text, category, status):
    _, data, _ = development(text)
    assert not data["events"] and len(data["undated_events"]) == 1
    item = data["undated_events"][0]
    assert item["development_kind"] == category and item["event_status"] == status
    assert item["event_date"] is None and item["source_ids"] == ["S1"]
    assert item["evidence"][0]["quote"] == text


def render_script(result, context=None):
    import types
    module = types.ModuleType("edicola.exploration_fixture")
    module.result, module.context = result, context
    code = '''from edicola.exploration_fixture import result, context
from edicola.knowledge_ui import render_knowledge
render_knowledge(result, context)
'''
    return module, code


def test_undated_proposal_is_useful_without_empty_timeline_warnings():
    source, data, diagnostics = development("L'associazione propone un credito di imposta per le imprese di pesca contro il caro carburante.")
    result = KnowledgeResult("timeline", "Misure economiche per la pesca", data, [source], COVERAGE, diagnostics, from_cache=True)
    module, code = render_script(result)
    with installed_fixture(module), patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
        app.run()
    assert not app.exception and not app.warning and not app.info
    assert any(s.value == "Eventi e sviluppi documentati" for s in app.subheader)
    assert any("non cronologico" in c.value for c in app.caption)
    assert not any("Risultato già disponibile" in c.value for c in app.caption)
    assert any("Proposta documentata" in item.proto.body for item in app.get("html"))
    assert not app.get("vega_lite_chart")
    api.assert_not_called()


def test_strict_chronology_explains_undated_limit_once():
    source, data, diagnostics = development("Le imprese chiedono un sostegno economico contro il caro carburante per la pesca.")
    result = KnowledgeResult("timeline", "Ricostruzione cronologica delle proposte", data, [source], COVERAGE, diagnostics)
    module, code = render_script(result)
    with installed_fixture(module):
        app = AppTest.from_string(code).run()
    assert not app.exception and not app.info
    assert any("non cronologico" in c.value for c in app.caption)
    assert strict_chronology(result.topic)


@pytest.mark.parametrize("data", [{}, {"events": [], "undated_events": []}])
def test_no_events_single_useful_empty_state(data):
    result = KnowledgeResult("timeline", "Tema assente", data, [], COVERAGE)
    module, code = render_script(result)
    with installed_fixture(module):
        app = AppTest.from_string(code).run()
    assert not app.exception and len(app.info) == 1 and not app.warning and not app.subheader
    assert "copertura dell’archivio è parziale" in app.info[0].value


def test_verified_and_incomplete_dates_remain_separate():
    text = "Il tavolo si è svolto il 12 ottobre 2026 per le imprese di pesca contro il caro carburante."
    _, data, _ = development(text, "2026-10-12")
    assert data["events"][0]["event_date"] == "2026-10-12"
    text = "Le imprese chiedono un incontro il 12 ottobre per discutere il caro carburante."
    source, data, _ = development(text)
    assert data["undated_events"][0]["event_date"] is None


def test_map_new_categories_still_require_literal_evidence_and_valid_relations():
    text = "Mario Rossi propone il credito di imposta per le imprese di pesca contro il caro carburante."
    source = Source("S1", "chunk", "a.pdf", 1, text, .1)
    raw = {"nodes": [{"id": "N1", "kind": "person", "label": claim("Mario Rossi", source)},
                     {"id": "N2", "kind": "proposal", "label": claim("credito di imposta", source)}],
           "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented", "label": claim("propone", source)}]}
    data, counts = validate_map(raw, [source])
    assert len(data["edges"]) == 1 and not counts["rejected_nodes"]
    assert "style=solid, dir=forward" in map_dot(data)
    assert map_focus(data, "credito di imposta") == "N2"
    raw["edges"][0]["label"]["text"] = "garantisce"
    assert not validate_map(raw, [source])[0]["edges"]


def test_map_switch_to_readable_list_keeps_evidence_without_api():
    raw, sources, contexts, _ = adjacent_case()
    data, diagnostics = validate_map(raw, sources, contexts=contexts)
    result = KnowledgeResult("map", "Opere pubbliche", data, sources, COVERAGE, diagnostics)
    module, code = render_script(result)
    with installed_fixture(module), patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
        assert len(app.get("graphviz_chart")) == 1
        app.segmented_control(key="knowledge_map_view").set_value("Elenco").run()
        assert not app.exception and not app.get("graphviz_chart") and app.dataframe
        assert any("stanzia oltre quattro milioni" in t.value for t in app.text)
        api.assert_not_called()


def test_event_reference_opens_original_page(archive):
    context, prepared = archive
    chunk = next(p for p in prepared if p.filename == "a.pdf").chunks[-1]
    source = Source("S1", chunk.id, "a.pdf", chunk.page, chunk.text, .1)
    item = {"title": claim("Lettura documentata", source), "description": claim(chunk.text, source), "event_date": None, "date_evidence": None}
    data, diagnostics = validate_timeline({"events": [item]}, [source], COVERAGE)
    result = KnowledgeResult("timeline", "Archivio", data, [source], COVERAGE, diagnostics)
    module, code = render_script(result, context)
    with installed_fixture(module), patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
        app.button(key="undated_0_pdf_S1").click().run()
        assert not app.exception and app.session_state["archive_page"] == chunk.page
        assert app.session_state["archive_pdf"] == "a.pdf"
        api.assert_not_called()


def test_neighbor_lookup_distinguishes_same_hash_other_filename_and_article_boundary():
    _, _, _, chunks = adjacent_case()
    other = replace(chunks[1], metadata={**chunks[1].metadata, "filename": "copia.pdf"})
    assert select_map_chunks([chunks[0]], chunks + [other]) == chunks
    other = replace(chunks[1], metadata={**chunks[1].metadata, "article_id": "another-article"})
    assert not contiguous(chunks[0], other)
    assert select_map_chunks([chunks[0]], [chunks[0], other]) == [chunks[0]]


def test_timeline_budget_keeps_whole_original_chunks(setup_knowledge):
    root, catalog, client, _, search = setup_knowledge
    original = catalog.chunks[0]
    large = IndexChunk("too-large", "Testo molto lungo del quotidiano. " * 800, {**original.metadata, "filename": "b.pdf"})
    catalog.chunks = [original, large]
    search.return_value = [{"id": original.id, "distance": .1}, {"id": large.id, "distance": .2}]
    result = generate_knowledge("timeline", "Misure per la pesca", authorize_external=True, root=root, client=client)
    assert len(result.sources) == 1 and result.sources[0].text == original.text
    assert result.diagnostics["chunks_dropped_for_budget"] == 1
    prompt = client.models.generate_content.call_args.kwargs
    assert len(prompt["contents"]) + len(prompt["config"].system_instruction) <= 12000
    second = generate_knowledge("timeline", "Misure per la pesca", authorize_external=True, root=root, client=client)
    assert second.from_cache
    search.assert_called_once()
    client.models.generate_content.assert_called_once()


def test_card_html_is_escaped_and_responsive():
    from edicola.knowledge_components import event_card
    item = dict(title='<img src=x onerror=x>', description='<script>x</script>', event_date=None, development_kind="proposal")
    with patch("streamlit.html") as html:
        event_card(item)
    assert "<img src=x" not in html.call_args.args[0] and "&lt;script&gt;" in html.call_args.args[0]
    assert "@media(max-width:600px)" in CSS and "max-width:100%" in CSS


def test_timeline_strategy_invalidates_only_timeline_cache(setup_knowledge, monkeypatch):
    root, _, client, _, _ = setup_knowledge
    for kind in ("map", "timeline"):
        generate_knowledge(kind, "Trasporti", authorize_external=True, root=root, client=client)
    monkeypatch.setattr("edicola.knowledge.TIMELINE_CONTENT_VERSION", "test-next")
    assert generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    assert not generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    assert client.models.generate_content.call_count == 3


def test_first_oversized_source_does_not_discard_other_useful_chunks(setup_knowledge):
    root, catalog, client, _, search = setup_knowledge
    original = catalog.chunks[0]
    large = IndexChunk("too-large", "Un passaggio troppo lungo del quotidiano. " * 800, {**original.metadata, "filename": "b.pdf"})
    catalog.chunks = [large, original]
    search.return_value = [{"id": large.id, "distance": .1}, {"id": original.id, "distance": .2}]
    from types import SimpleNamespace
    from google.genai import types
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text='{"events":[]}', candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    result = generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client)
    assert len(result.sources) == 1 and result.sources[0].text == original.text
    assert result.sources[0].id == "S2" and result.diagnostics["chunks_dropped_for_budget"] == 1


def test_switch_product_retains_its_own_result_without_generation(tmp_path):
    from test_knowledge import map_data
    source, data, diagnostics = development("Le imprese chiedono sostegno economico contro il caro carburante per la pesca.")
    timeline = KnowledgeResult("timeline", "Pesca", data, [source], COVERAGE, diagnostics)
    map_result, map_diagnostics = validate_map(map_data(), SOURCES)
    map_product = KnowledgeResult("map", "Pesca", map_result, SOURCES, COVERAGE, map_diagnostics)
    code = f'''from pathlib import Path
from edicola.reading_ui import render_visuals
render_visuals(Path({str(tmp_path)!r}), None)
'''
    with patch("edicola.knowledge.generate_knowledge", side_effect=[timeline, map_product]) as generate:
        app = AppTest.from_string(code).run()
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.text_input(key="knowledge_topic").set_value("Pesca").run()
        app.button(key="timeline_submit").click().run()
        assert any(h.value == "Eventi e sviluppi documentati" for h in app.subheader)
        app.segmented_control(key="knowledge_kind").set_value("Mappa").run()
        assert not any(h.value == "Eventi e sviluppi documentati" for h in app.subheader)
        generate.assert_called_once()
        app.button(key="map_submit").click().run()
        app.segmented_control(key="knowledge_kind").set_value("Timeline").run()
        assert not app.exception and any(h.value == "Eventi e sviluppi documentati" for h in app.subheader)
        assert generate.call_count == 2
