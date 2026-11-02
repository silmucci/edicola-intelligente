"""UI cliente con catalogo e cache simulati: nessuna scrittura dei dati dell’app."""

from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola.chat_sources import citation_text
from edicola.design import product_notice
from edicola.editorial import EditorialResult
from edicola.editorial_handoff import TARGETS, open_draft
from edicola.podcast_text import CachedProduct
from edicola.product_navigation import PRODUCTS
from edicola.rag import Source
from test_editorial import make_catalog


@pytest.fixture
def consumer_ui():
    catalog = make_catalog()
    source = Source("S7", "private-chunk", "giornale-0.pdf", 2, "Estratto letterale della fonte.", .1)
    legacy = EditorialResult("dossier", "Approfondimento salvato [S7]",
        [{"heading": "Una sezione [S7]", "text": "Una notizia documentata. [S7]"}],
        [source], ["S7"], catalog.coverage, True)
    current = EditorialResult("briefing", "Briefing corrente [S7]", legacy.sections,
                              [source], ["S7"], catalog.coverage, True)
    fixture = ModuleType("edicola.consumer_fixture")
    fixture.root = Path(__file__).parent / "__consumer_fixture_only__"
    code = '''from edicola.consumer_fixture import root
from edicola.reading_ui import render_editorial
render_editorial(root, None)
'''
    with patch.dict("sys.modules", {"edicola.consumer_fixture": fixture}), patch(
        "edicola.press_review_ui.read_catalog", return_value=catalog), patch(
        "edicola.podcast_text.list_products", return_value=[CachedProduct("saved-key", "2026-10-22", legacy)]), patch(
        "edicola.chat_sources.source_editions", return_value={"S7": {"publication": "Testata"}}), patch(
        "edicola.chat_sources.source_button") as pdf, patch(
        "edicola.reading_ui.diagnostics_enabled", return_value=False), patch(
        "edicola.editorial.generate_product", return_value=current) as generate, patch(
        "edicola.editorial.cache_write", side_effect=AssertionError("Scrittura vietata")), patch(
        "google.genai.Client", side_effect=AssertionError("API vietate")):
        yield AppTest.from_string(code), legacy, current, generate, pdf


def test_single_product_has_no_retired_controls_and_uses_editorial_labels(consumer_ui):
    app, _, _, generate, _ = consumer_ui
    app.run()
    assert not app.exception
    assert not app.segmented_control
    assert len([p for p in PRODUCTS if p["id"] == "briefing"]) == 1
    assert len(PRODUCTS) == 8 and all(p["id"] != "dossier" for p in PRODUCTS)
    assert not {"Dossier", "Infografica", "Rassegna"} & TARGETS.keys()
    assert all(".pdf" not in label for label in app.multiselect[0].options)
    assert all("indicizz" not in text.value for text in app.caption)
    generate.assert_not_called()


def test_legacy_reading_and_citations_are_available_without_generation(consumer_ui):
    app, legacy, _, generate, pdf = consumer_ui
    original = deepcopy(legacy)
    app.run().selectbox(key="editorial_saved_product").set_value("saved-key").run()
    assert not app.exception
    assert any("Approfondimento salvato" in h.value for h in app.subheader)
    assert any("1" in text.value for text in app.markdown)
    assert not app.json and not app.dataframe
    assert all("S7" not in text.value for text in app.caption)
    assert all("private-chunk" not in text.value for text in app.text)
    assert pdf.call_args.args[:2] == ("giornale-0.pdf", 2)
    assert pdf.call_args.kwargs["chunk_id"] == "private-chunk"
    assert "S7" not in pdf.call_args.kwargs["label"]
    app.run()
    assert legacy == original
    generate.assert_not_called()


def test_only_authorized_explicit_send_generates_briefing(consumer_ui):
    app, _, _, generate, _ = consumer_ui
    app.run()
    app.session_state["consent_choices"] = {("text", "text-v2"): True}
    app.selectbox(key="editorial_saved_product").set_value("saved-key").run()
    generate.assert_not_called()
    app.text_input(key="editorial_review_keyword").set_value("trasporti").run()
    generate.assert_not_called()
    app.button(key="briefing_submit").click().run()
    assert not app.exception
    assert generate.call_args.args == ("briefing", "")
    assert generate.call_args.kwargs["selection"].keyword == "trasporti"
    assert any("Briefing corrente" in h.value for h in app.subheader)
    app.run()
    generate.assert_called_once()


def test_handoff_prepares_single_briefing_without_retired_state():
    state = {"editorial_workspace": "Infografica", "consent_pending": {"action": "briefing"}}
    with patch("streamlit.session_state", state):
        open_draft("Briefing", "Un tema")
    assert state["nav_section"] == "Briefing"
    assert state["editorial_review_keyword"] == "Un tema"
    assert "consent_pending" not in state


def test_home_opens_briefing_with_same_filters_without_generating():
    fixture = ModuleType("edicola.consumer_fixture")
    fixture.context = SimpleNamespace(root=Path(__file__).parent / "__consumer_fixture_only__", documents=[])
    code = '''from edicola.consumer_fixture import context
from edicola.experience_ui import render_home
render_home(context.root, context)
'''
    with patch.dict("sys.modules", {"edicola.consumer_fixture": fixture}), patch(
        "edicola.experience_ui.read_catalog", return_value=make_catalog()), patch(
        "edicola.experience_ui.render_products"), patch("edicola.experience_ui.render_highlights"), patch(
        "edicola.experience_ui.source_button"), patch("edicola.experience_ui.authenticated", return_value=False), patch(
        "edicola.editorial.generate_product") as generate, patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
        app.text_input(key="editorial_review_keyword").set_value("trasporti").run()
        app.button(key="home_prepare_briefing").click().run()
        assert not app.exception and app.session_state["nav_section"] == "Briefing"
        assert app.session_state["editorial_review_keyword"] == "trasporti"
        assert not any(button.key == "briefing_submit" for button in app.button)
        generate.assert_not_called()
        api.assert_not_called()


def test_actual_app_mounts_only_eight_supported_destinations_with_mocked_archive():
    from contextlib import ExitStack
    context = SimpleNamespace(root=Path(__file__).parent / "__consumer_fixture_only__", documents=[], chunk_references={})
    with ExitStack() as stack:
        stack.enter_context(patch("edicola.ingestion.ingest_directory", return_value=[]))
        stack.enter_context(patch("edicola.chunking.prepare_documents", return_value=[]))
        stack.enter_context(patch("edicola.pdf_viewer.archive_context", return_value=context))
        stack.enter_context(patch("edicola.archive_ui.diagnostics_enabled", return_value=False))
        stack.enter_context(patch("edicola.header_ui.render_header"))
        for name in ("edicola.experience_ui.render_home", "edicola.pdf_viewer.render_archive",
                     "edicola.reading_ui.render_chat", "edicola.reading_ui.render_visuals",
                     "edicola.podcast_ui.render_podcast_ui", "edicola.personalization_ui.render_personalization_ui"):
            stack.enter_context(patch(name))
        editorial = stack.enter_context(patch("edicola.reading_ui.render_editorial"))
        api = stack.enter_context(patch("google.genai.Client"))
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run()
        assert not app.exception
        assert app.selectbox(key="nav_section").options == [p["title"] for p in PRODUCTS]
        for product in PRODUCTS:
            app.selectbox(key="nav_section").set_value(product["title"]).run()
            assert not app.exception and not app.segmented_control
        editorial.assert_called_once()
        api.assert_not_called()


def test_numeric_citations_do_not_change_original_results():
    original = "Una notizia [S7] e una seconda [S2]."
    assert citation_text(original, ["S2", "S7"]) == "Una notizia [2] e una seconda [1]."
    assert original == "Una notizia [S7] e una seconda [S2]."
    assert "<img" in citation_text("<img src=x> [S7]", ["S7"])  # L’escaping resta al renderer.


@pytest.mark.parametrize("status", ["invalid_json", "output_truncated", "prompt_budget_exceeded"])
def test_errors_do_not_expose_technical_messages_or_blame_the_reader(status):
    product = EditorialResult("briefing", "", [], [Source("S1", "id", "a.pdf", 1, "Fonte", 0)], [], {}, False,
                              "Aumentare EDITORIAL_BRIEFING_MAX_PROMPT_CHARS; JSON", diagnostics={"status": status})
    message = product_notice(product)
    assert "JSON" not in message and "EDITORIAL_" not in message
    assert "edizioni originali" in message
