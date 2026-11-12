"""Task 14.2: percorsi reali dell'app, nessuna richiesta esterna."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from editorial_adapter import navigate_to
from edicola.product_navigation import PRODUCTS, SECTIONS
from edicola.profiles import Profile
from edicola.knowledge import KnowledgeResult
from edicola.knowledge_validation import validate_map
from edicola.knowledge_components import CSS
from edicola.knowledge_presentation import theme_title
from test_experience_ui import archive
from test_knowledge import COVERAGE, SOURCES, map_data
from test_knowledge_exploration import development, render_script, installed_fixture


@contextmanager
def platform(context):
    with patch("edicola.ingestion.ingest_directory", return_value=context.documents), patch(
        "edicola.chunking.prepare_documents", return_value=[]
    ), patch("edicola.pdf_viewer.archive_context", return_value=context), patch(
        "edicola.podcast_ui.list_episodes", return_value=[]
    ), patch("edicola.personalization_ui.load_profile", return_value=Profile()):
        yield AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()


VISIBLE_PRODUCTS = [product for product in PRODUCTS if product["id"] != "profile"]


@pytest.mark.parametrize("index", range(len(VISIBLE_PRODUCTS)))
def test_product_cards_open_real_destinations_without_generating(archive, index):
    _, context, _ = archive
    target = VISIBLE_PRODUCTS[index]
    with platform(context) as app, patch("edicola.rag.ask_question") as rag, patch(
        "edicola.editorial.generate_product") as editorial, patch(
        "edicola.knowledge.generate_knowledge") as knowledge:
        assert not app.exception
        app.button(key=f"home_products_test_{index}").click().run()
        assert not app.exception
        assert app.session_state["nav_section"] == target["section"]
        assert len(app.chat_input) == (1 if target["id"] == "chat" else 0)
        rag.assert_not_called()
        editorial.assert_not_called()
        knowledge.assert_not_called()


def test_explore_switches_views_preserving_results_without_extra_generation(archive):
    _, context, _ = archive
    source, timeline_data, timeline_counts = development("Le imprese chiedono sostegno economico.")
    timeline = KnowledgeResult("timeline", "Sostegno", timeline_data, [source], COVERAGE, timeline_counts)
    data, counts = validate_map(map_data(), SOURCES)
    mapping = KnowledgeResult("map", "Trasporti", data, SOURCES, COVERAGE, counts)
    with platform(context) as app, patch("edicola.knowledge.generate_knowledge", side_effect=[timeline, mapping]) as generate:
        app.session_state["consent_choices"] = {("text", "text-v3"): True}
        navigate_to(app, "Timeline")
        assert app.session_state["knowledge_kind"] == "Timeline"
        app.text_input(key="knowledge_topic").set_value("Sostegno").run()
        app.button(key="timeline_submit").click().run()
        assert not app.exception and "timeline" in app.session_state["knowledge_results"]
        app.segmented_control(key="knowledge_kind").set_value("Mappa").run()
        assert app.session_state["knowledge_kind"] == "Mappa"
        app.text_input(key="knowledge_topic").set_value("Trasporti").run()
        app.button(key="map_submit").click().run()
        assert not app.exception and "map" in app.session_state["knowledge_results"]
        app.segmented_control(key="knowledge_map_view").set_value("Elenco").run()
        app.segmented_control(key="knowledge_kind").set_value("Timeline").run()
        assert app.text_input(key="knowledge_topic").value == "Trasporti"
        app.segmented_control(key="knowledge_kind").set_value("Mappa").run()
        assert app.segmented_control(key="knowledge_map_view").value == "Elenco"
        assert generate.call_count == 2

def test_switching_explore_mode_cancels_pending_generation_and_keeps_consent(archive):
    _, context, _ = archive
    with platform(context) as app, patch("edicola.knowledge.generate_knowledge") as generate:
        navigate_to(app, "Timeline")
        app.text_input(key="knowledge_topic").set_value("Tema").run()
        app.button(key="timeline_submit").click().run()
        generate.assert_not_called()
        assert app.session_state["consent_pending"]
        app.segmented_control(key="knowledge_kind").set_value("Mappa").run()
        assert "consent_pending" not in app.session_state
        app.session_state["consent_choices"] = {("text", "text-v3"): True}
        app.segmented_control(key="knowledge_kind").set_value("Timeline").run()
        generate.assert_not_called()
        assert app.session_state["consent_choices"][("text", "text-v3")]

def test_graph_and_list_keep_documented_sources_without_api(archive):
    _, context, _ = archive
    data, counts = validate_map(map_data(), SOURCES)
    result = KnowledgeResult("map", "Trasporti", data, SOURCES, COVERAGE, counts)
    module, code = render_script(result, context)
    with installed_fixture(module), patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
        assert not app.exception and not app.dataframe
        assert not any("cache" in c.value.casefold() for c in app.caption)
        app.segmented_control(key="knowledge_map_view").set_value("Elenco").run()
        assert not app.exception and not app.dataframe
        api.assert_not_called()

def test_responsive_timeline_preserves_undated_developments():
    assert "max-width:100%" in CSS and "@media(max-width:600px)" in CSS
    source, data, counts = development("Le imprese propongono una misura di sostegno.")
    result = KnowledgeResult("timeline", "Sostegno", data, [source], COVERAGE, counts)
    module, code = render_script(result)
    with installed_fixture(module):
        app = AppTest.from_string(code).run()
    assert not app.exception
    assert not app.info
    assert not any(h.value == "Cronologia documentata" for h in app.subheader)

def test_briefing_keeps_legacy_result_readable_without_generating_dossier(archive):
    from edicola.editorial import EditorialResult
    _, context, _ = archive
    briefing = EditorialResult("briefing", "Sintesi disponibile", [], [], [], COVERAGE, True)
    dossier = EditorialResult("dossier", "Approfondimento disponibile", [], [], [], COVERAGE, True)
    with platform(context) as app, patch("edicola.editorial.generate_product", return_value=briefing) as generate:
        app.session_state["editorial_results"] = {"dossier": dossier}
        app.session_state["consent_choices"] = {("text", "text-v3"): True}
        navigate_to(app, "Briefing")
        app.selectbox(key="editorial_saved_product").set_value("session:dossier").run()
        assert any(h.value == dossier.title for h in app.subheader)
        generate.assert_not_called()
        app.button(key="briefing_submit").click().run()
        assert any(h.value == briefing.title for h in app.subheader)
        assert app.session_state["editorial_results"]["dossier"] == dossier
        assert generate.call_args.args[0] == "briefing"
        assert generate.call_count == 1 and not app.exception


def test_briefing_preserves_last_verified_result_when_gemini_is_busy(archive):
    from edicola.editorial import EditorialError, EditorialResult
    _, context, _ = archive
    previous = EditorialResult("briefing", "Briefing già verificato", [], [], [], COVERAGE, True)
    with platform(context) as app, patch(
        "edicola.editorial.generate_product",
        side_effect=EditorialError("Gemini non disponibile: HTTP 503.")
    ) as generate:
        app.session_state["editorial_result"] = previous
        app.session_state["editorial_results"] = {"briefing": previous}
        app.session_state["consent_choices"] = {("text", "text-v3"): True}
        navigate_to(app, "Briefing")
        app.button(key="briefing_submit").click().run()
        assert not app.exception
        assert generate.call_count == 1
        assert app.session_state["editorial_results"]["briefing"] == previous
        assert any(header.value == previous.title for header in app.subheader)
        assert app.error
