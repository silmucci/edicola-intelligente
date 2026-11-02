"""Percorsi editoriali e invarianti delle nuove funzioni, senza API reali."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola.editorial import generate_product
from edicola.press_review import ReviewSelection, filter_catalog, review_groups
from edicola.map_exploration import focused_map
from edicola.podcast_text import CachedProduct, prepare_script
from test_editorial import make_catalog, setup_editorial
from test_podcast import editorial_product, fake_client, podcast_archive
from test_chat_ui import RESULT, script as chat_script, grant
from test_knowledge import COVERAGE, SOURCES, map_data
from test_knowledge_exploration import installed_fixture, render_script
from edicola.knowledge import KnowledgeResult
from edicola.knowledge_validation import validate_map
from test_experience_ui import archive
from test_navigation_editorial import platform


def test_review_filters_combine_keyword_sources_and_only_curated_scope():
    catalog = make_catalog()
    catalog.coverage["files"][0]["scope"] = "nazionale"
    original = deepcopy(catalog)
    chosen = filter_catalog(catalog, ReviewSelection("piano trasporti", ("giornale-0.pdf",), "nazionale"))
    assert len(chosen.chunks) == 3
    assert chosen.coverage["selection"]["editions"] == 1
    assert chosen.coverage["partial"]
    assert not filter_catalog(catalog, ReviewSelection(scope="internazionale")).chunks
    assert not filter_catalog(catalog, ReviewSelection(keyword="!!!")).chunks
    assert catalog == original
    assert sum(map(len, review_groups(chosen))) == len(chosen.chunks)


def test_filtered_briefing_separate_cache_and_no_unselected_sources(setup_editorial):
    root, _, client, _, search = setup_editorial
    chosen = ReviewSelection("trasporti", ("giornale-0.pdf",))
    first = generate_product("briefing", root=root, authorize_external=True, selection=chosen, client=client)
    assert first.sufficient
    assert {s.filename for s in first.sources} == {"giornale-0.pdf"}
    second = generate_product("briefing", root=root, authorize_external=True, selection=chosen, client=client)
    assert second.from_cache and client.models.generate_content.call_count == 1
    other = generate_product("briefing", root=root, authorize_external=True,
                             selection=ReviewSelection(filenames=("giornale-1.pdf",)), client=client)
    assert not other.from_cache and {s.filename for s in other.sources} == {"giornale-1.pdf"}
    search.assert_not_called()








@pytest.mark.parametrize("label,key,destination", [
    ("Briefing", "editorial_review_keyword", "Briefing"),
    ("Timeline", "knowledge_topic_timeline", "Timeline"),
    ("Mappa", "knowledge_topic_map", "Mappe concettuali"),
    ("Podcast", "podcast_topic", "Podcast"),
])
def test_chat_handoff_only_prepares_draft(tmp_path, label, key, destination):
    with patch("edicola.rag.ask_question", return_value=RESULT) as ask, patch(
        "edicola.editorial.generate_product") as generate, patch("edicola.knowledge.generate_knowledge") as knowledge:
        app = AppTest.from_string(chat_script(tmp_path), default_timeout=15).run()
        grant(app)
        app.chat_input[0].set_value("Progetto trasporti").run()
        app.button(key="editorial_handoff_" + label).click().run()
        assert not app.exception and app.session_state[key] == "Progetto trasporti"
        assert app.session_state["nav_section"] == destination
        assert "consent_pending" not in app.session_state
        assert "rag_pending" not in app.session_state
        ask.assert_called_once()
        generate.assert_not_called()
        knowledge.assert_not_called()


def test_focus_map_preserves_only_existing_edges_and_keeps_isolated_node():
    data = {"nodes": [{"id": str(i)} for i in range(4)],
            "edges": [{"from_id": "0", "to_id": "1"}, {"from_id": "1", "to_id": "2"}]}
    original = deepcopy(data)
    assert focused_map(data, "0") == {"nodes": data["nodes"][:2], "edges": data["edges"][:1]}
    assert focused_map(data, "3") == {"nodes": [data["nodes"][3]], "edges": []}
    assert data == original


def test_map_named_exploration_uses_generated_result_without_api():
    data, counts = validate_map(map_data(), SOURCES)
    result = KnowledgeResult("map", "Trasporti", data, SOURCES, COVERAGE, counts)
    fixture, code = render_script(result)
    with installed_fixture(fixture), patch("google.genai.Client") as api:
        app = AppTest.from_string(code, default_timeout=15).run()
        assert not app.selectbox
        assert not app.exception and app.get("graphviz_chart")
        assert any(node["label"] in text.value for node in data["nodes"] for text in app.text)
        app.segmented_control(key="knowledge_map_view").set_value("Elenco").run()
        assert not app.dataframe and not app.get("graphviz_chart")
        app.segmented_control(key="knowledge_map_view").set_value("Grafo").run()
        assert not app.exception
        api.assert_not_called()


def test_podcast_skips_large_section_but_keeps_next_whole_section():
    result = editorial_product()
    result.sections.insert(0, {"heading": "Sezione lunga [S1]", "text": "Importi non tagliabili. " * 1000 + "[S1]"})
    script = prepare_script(CachedProduct("key", "date", result))
    assert script.selected_sections == 2 and script.total_sections == 3
    assert "4,2 milioni" in script.text and "21 ottobre 2026" in script.text
    assert "Importi non tagliabili" not in script.text
    assert script.excerpt and len(script.text.split()) <= 240


def test_audio_ui_cache_rejects_previous_script_or_model(podcast_archive, monkeypatch):
    from edicola.podcast import generate_podcast
    from edicola.personalization_ui import cached_audio
    result = generate_podcast("product-1", authorize_external=True, root=podcast_archive, client=fake_client())
    assert cached_audio(podcast_archive, "product-1", "Kore", script=result.script)
    changed = replace(result.script, text="Un altro copione.")
    assert cached_audio(podcast_archive, "product-1", "Kore", script=changed) is None
    monkeypatch.setenv("GEMINI_TTS_MODEL", "different-model")
    assert cached_audio(podcast_archive, "product-1", "Kore", script=result.script) is None




def test_changing_review_filters_or_navigation_cancels_pending_send(archive):
    _, context, _ = archive
    with patch("edicola.press_review_ui.read_catalog", return_value=make_catalog()), patch(
        "edicola.editorial.generate_product") as generate:
        with platform(context) as app:
            app.pills(key="nav_section").set_value("Briefing").run()
            app.text_input(key="editorial_review_keyword").set_value("trasporti")
            app.button(key="briefing_submit").click().run()
            assert app.session_state["consent_pending"]
            app.text_input(key="editorial_review_keyword").set_value("scuola").run()
            assert "consent_pending" not in app.session_state
            app.button(key="briefing_submit").click().run()
            assert app.session_state["consent_pending"]
            app.pills(key="nav_section").set_value("Timeline").run()
            assert "consent_pending" not in app.session_state
            app.session_state["consent_choices"] = {("text", "text-v2"): True}
            app.pills(key="nav_section").set_value("Briefing").run()
            assert not app.exception
            generate.assert_not_called()
