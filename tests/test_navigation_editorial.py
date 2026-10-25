"""Task 14.2: percorsi reali dell'app, nessuna richiesta esterna."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

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
        "edicola.podcast_ui.list_products", return_value=[]
    ), patch("edicola.personalization_ui.load_profile", return_value=Profile()):
        yield AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()


@pytest.mark.parametrize("index", range(9))
def test_home_cards_and_top_navigation_share_the_nine_real_destinations(archive, index):
    _, context, _ = archive
    with platform(context) as app, patch("edicola.rag.ask_question") as rag, patch(
        "edicola.editorial.generate_product") as editorial, patch("edicola.knowledge.generate_knowledge") as knowledge:
        assert app.pills(key="nav_section").options == SECTIONS
        app.button(key=f"home_products_test_{index}").click().run()
        assert not app.exception
        assert app.pills(key="nav_section").value == PRODUCTS[index]["title"]
        assert app.session_state["nav_section"] == PRODUCTS[index]["section"]
        assert not any(w.key in {"editorial_kind", "knowledge_kind"} for w in app.segmented_control)
        assert len(app.chat_input) == (1 if index == 2 else 0)
        rag.assert_not_called()
        editorial.assert_not_called()
        knowledge.assert_not_called()


def test_product_drafts_results_and_graph_mode_survive_navigation_without_api(archive):
    _, context, _ = archive
    source, timeline_data, timeline_counts = development("Le imprese chiedono sostegno economico.")
    timeline = KnowledgeResult("timeline", "Sostegno", timeline_data, [source], COVERAGE, timeline_counts)
    data, counts = validate_map(map_data(), SOURCES)
    mapping = KnowledgeResult("map", "Trasporti", data, SOURCES, COVERAGE, counts)
    with platform(context) as app, patch("edicola.knowledge.generate_knowledge", side_effect=[timeline, mapping]) as generate:
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.pills(key="nav_section").set_value("Timeline").run()
        app.text_input(key="knowledge_topic_timeline").set_value("Sostegno")
        app.button(key="timeline_submit").click().run()
        assert any(h.value == "Eventi e sviluppi documentati" for h in app.subheader)
        app.pills(key="nav_section").set_value("Mappe concettuali").run()
        assert not app.get("graphviz_chart")
        app.text_input(key="knowledge_topic_map").set_value("Trasporti")
        app.button(key="map_submit").click().run()
        assert not app.exception and app.get("graphviz_chart")
        app.segmented_control(key="knowledge_map_view").set_value("Elenco").run()
        app.pills(key="nav_section").set_value("Timeline").run()
        assert app.text_input(key="knowledge_topic_timeline").value == "Sostegno"
        assert not app.get("graphviz_chart") and not app.segmented_control
        app.pills(key="nav_section").set_value("Mappe concettuali").run()
        assert app.text_input(key="knowledge_topic_map").value == "Trasporti"
        assert app.segmented_control(key="knowledge_map_view").value == "Elenco"
        assert app.dataframe and not app.get("graphviz_chart")
        assert generate.call_count == 2


def test_navigation_cancels_old_pending_generation_and_keeps_consent(archive):
    _, context, _ = archive
    with platform(context) as app, patch("edicola.knowledge.generate_knowledge") as generate:
        app.pills(key="nav_section").set_value("Timeline").run()
        app.text_input(key="knowledge_topic_timeline").set_value("Tema").run()
        app.button(key="timeline_submit").click().run()
        generate.assert_not_called()
        assert app.session_state["consent_pending"]
        app.pills(key="nav_section").set_value("Mappe concettuali").run()
        assert "consent_pending" not in app.session_state
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.pills(key="nav_section").set_value("Timeline").run()
        generate.assert_not_called()
        assert app.session_state["consent_choices"][("text", "text-v2")]


def test_graph_and_list_are_alternatives_with_editorial_sources_only(archive):
    _, context, _ = archive
    data, counts = validate_map(map_data(), SOURCES)
    result = KnowledgeResult("map", "Quali misure sono proposte per i trasporti nel territorio?", data, SOURCES, COVERAGE, counts)
    module, code = render_script(result, context)
    with installed_fixture(module):
        app = AppTest.from_string(code).run()
        assert not app.exception and not app.dataframe
        assert app.get("graphviz_chart")
        assert not any("sviluppo" in e.label for e in app.expander)
        assert not any("cache" in c.value.casefold() or "validazione" in c.value.casefold() for c in app.caption)
        assert all("S1" not in b.label for b in app.button)
        assert len(theme_title(result.topic)) <= 63
        app.segmented_control(key="knowledge_map_view").set_value("Elenco").run()
        assert app.dataframe and not app.get("graphviz_chart")


def test_responsive_cards_have_no_fixed_width_or_false_undated_axis():
    # Contratto CSS: la colonna narrativa si adatta al contenitore e le card
    # senza data non ereditano l'asse. La verifica browser resta distinta.
    assert "max-width:100%" in CSS and ".edi-event.undated:before{display:none}" in CSS
    assert "@media(max-width:600px)" in CSS
    source, data, counts = development("Le imprese propongono una misura di sostegno.")
    result = KnowledgeResult("timeline", "Sostegno", data, [source], COVERAGE, counts)
    module, code = render_script(result)
    with installed_fixture(module):
        app = AppTest.from_string(code).run()
    assert not app.exception
    assert not any(h.value == "Cronologia documentata" for h in app.subheader)
    cards = [item.proto.body for item in app.get("html") if 'class="edi-event ' in item.proto.body]
    assert cards and all('proposal undated"' in card for card in cards)
    assert not app.info


def test_briefing_and_dossier_results_stay_separate(archive):
    from edicola.editorial import EditorialResult
    _, context, _ = archive
    briefing = EditorialResult("briefing", "Sintesi disponibile", [], [], [], COVERAGE, True)
    dossier = EditorialResult("dossier", "Approfondimento disponibile", [], [], [], COVERAGE, True)
    with platform(context) as app, patch("edicola.editorial.generate_product", side_effect=[briefing, dossier]) as generate:
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.pills(key="nav_section").set_value("Briefing").run()
        app.button(key="briefing_submit").click().run()
        app.pills(key="nav_section").set_value("Dossier").run()
        assert not any(h.value == briefing.title for h in app.subheader)
        app.text_input(key="editorial_topic").set_value("Trasporti")
        app.button(key="dossier_submit").click().run()
        assert any(h.value == dossier.title for h in app.subheader)
        app.pills(key="nav_section").set_value("Briefing").run()
        assert any(h.value == briefing.title for h in app.subheader)
        assert not any(h.value == dossier.title for h in app.subheader)
        app.pills(key="nav_section").set_value("Dossier").run()
        assert app.text_input(key="editorial_topic").value == "Trasporti"
        assert generate.call_count == 2 and not app.exception
