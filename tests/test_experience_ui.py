"""Esperienza editoriale: archivio sintetico, identità simulate, nessuna API."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola.archive import read_active_chunks
from edicola.chunking import prepare_documents
from edicola.editorial_selection import Catalog
from edicola.experience_ui import SECTIONS, excerpt, home_selection, readable, recent_editions
from edicola.ingestion import ingest_directory
from edicola.pdf_viewer import archive_context
from edicola.profiles import Profile, load_profile, save_profile
from edicola.rag import RagError, RagResult, Source
from test_ingestion import make_pdf


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("EDICOLA_ARCHIVE_DIAGNOSTICS", "0")
    monkeypatch.setenv("EDICOLA_CLOUD_DEMO", "0")
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    for name, text in (("a.pdf", "Il Comune ha approvato il piano dei trasporti. "),
                       ("b.pdf", "La Regione finanzia i trasporti e le opere pubbliche. ")):
        (incoming / name).write_bytes(make_pdf((text * 40, "I lavori della scuola iniziano il 12 novembre 2026. " * 25)))
    registry = tmp_path / "data/archive.sqlite3"
    documents = ingest_directory(incoming, registry)
    prepared = prepare_documents(documents, registry)
    chunks, _ = read_active_chunks(registry, incoming)
    files = [{"pdf": name, "publication": "Testata di prova", "date": "2026-10-23"} for name in ("a.pdf", "b.pdf")]
    catalog = Catalog(chunks, {}, {"indexed": len(chunks), "total": len(chunks) + 2, "partial": True, "files": files, "warnings": []})
    (tmp_path / "data/editions.json").write_text(json.dumps({"a.pdf": {"publication": "Edizione A", "date": "2026-10-21"},
                                                          "b.pdf": {"publication": "Edizione B", "date": "2026-10-23"}}), encoding="utf-8")
    with patch("google.genai.Client", side_effect=AssertionError("API vietate")), patch(
        "edicola.experience_ui.read_catalog", return_value=catalog
    ), patch("edicola.personalization_ui.read_catalog", return_value=catalog), patch(
        "edicola.personalization_ui.list_products", return_value=[]
    ):
        yield tmp_path, archive_context(tmp_path, documents, prepared), catalog


def script(root):
    return f'''
from pathlib import Path
import streamlit as st
from edicola.ingestion import ingest_directory
from edicola.chunking import prepare_documents
from edicola.pdf_viewer import archive_context, render_archive
from edicola.experience_ui import SECTIONS, render_home
from edicola.reading_ui import render_chat
from edicola.personalization_ui import render_personalization_ui
root = Path({str(root)!r})
docs = ingest_directory(root / "data/incoming", root / "data/archive.sqlite3")
prepared = prepare_documents(docs, root / "data/archive.sqlite3")
context = archive_context(root, docs, prepared)
if "nav_section" not in st.session_state:
    st.session_state["nav_section"] = "Home"
tabs = st.tabs(SECTIONS, key="nav_section", on_change="rerun")
with tabs[0]: render_home(root, context)
with tabs[1]: render_archive(context, prepared)
with tabs[2]: render_chat(root, context)
with tabs[6]: render_personalization_ui(root, archive=context)
'''


@pytest.mark.parametrize("logged_in", [False, True])
def test_identity_home_and_logout_are_not_fake_authentication(archive, logged_in):
    root, context, _ = archive
    save_profile(root, Profile(interests=["trasporti"]))
    with patch("streamlit.user", SimpleNamespace(is_logged_in=logged_in)), patch("streamlit.logout") as logout:
        app = AppTest.from_string(script(root), default_timeout=15).run()
        assert not app.exception
        assert app.button(key="account_logout").disabled is (not logged_in)
        # La homepage personalizzata usa SOLO la sessione nativa verificata.
        home_headers = [h.value for h in app.tabs[0].subheader]
        assert ("Consigliati per te" in home_headers) is logged_in
        assert any("condiviso" in caption.value for caption in app.caption)
        assert load_profile(root).user_id == "demo"  # Identità/storage del prototipo invariati.
        if logged_in:
            app.session_state["rag_history"] = [{"question": "Domanda", "result": RagResult("Risposta", [], [], False)}]
            app.button(key="account_logout").click().run()
            logout.assert_called_once()
            assert "rag_history" not in app.session_state
            assert load_profile(root).interests == ["trasporti"]  # Logout non cancella dati persistenti.
        else:
            logout.assert_not_called()


@pytest.mark.parametrize("button,destination", [("home_chat", "Chat AI"), ("home_briefing", "Approfondimenti"),
                                                ("home_podcast", "Podcast"), ("home_profile", "Personalizzazione")])
def test_shortcuts_keep_consents_and_do_not_generate(archive, button, destination):
    root, _, _ = archive
    with patch("edicola.rag.ask_question", side_effect=AssertionError("RAG automatico")), patch(
        "edicola.personalization_ui.generate_personal_briefing", side_effect=AssertionError("Generazione automatica")
    ):
        app = AppTest.from_string(script(root), default_timeout=15).run()
        app.checkbox(key="rag_authorized").check().run()
        app.text_input(key="rag_input").set_value("Quali opere pubbliche?").run()
        app.button(key=button).click().run()
        assert not app.exception
        assert app.session_state["nav_section"] == destination
        assert app.text_input(key="rag_input").value == "Quali opere pubbliche?"
        assert app.checkbox(key="rag_authorized").value
        assert [tab.label for tab in app.tabs] == SECTIONS


def test_cards_save_remove_and_preferences_feedback(archive):
    root, _, catalog = archive
    save_profile(root, Profile(interests=["trasporti"]))
    app = AppTest.from_string(script(root), default_timeout=15).run()
    save = next(button for button in app.button if button.label == "Salva lettura")
    app.button(key=save.key).click().run()
    assert not app.exception
    assert len(load_profile(root).saved) == 1
    assert any("Lettura salvata" in success.value for success in app.success)
    identity = next(iter(load_profile(root).saved))
    app.button(key=f"personal_remove_{identity}").click().run()
    assert not load_profile(root).saved
    assert any("rimossa" in success.value for success in app.success)
    app.multiselect(key="personal_interests").set_value(["scuola", "cultura locale"])
    app.selectbox(key="personal_minutes").set_value(2)
    app.button(key="FormSubmitter:personal_preferences-Salva preferenze").click().run()
    assert not app.exception
    assert load_profile(root).interests == ["scuola", "cultura locale"]
    assert load_profile(root).minutes == 2
    assert any("Preferenze salvate" in s.value for s in app.success)


def test_home_selection_uses_real_passages_and_deduplicates(archive):
    _, _, catalog = archive
    repeated = replace(catalog.chunks[0], id="copy")
    catalog.chunks.append(repeated)
    selected = home_selection(catalog)
    assert 1 < len(selected) <= 4
    assert len({c.metadata["filename"] for c in selected[:2]}) == 2
    assert len({c.text for c in selected}) == len(selected)
    assert all(chunk in catalog.chunks for chunk in selected)


def test_recent_editions_use_verified_dates_and_handle_missing_metadata(archive):
    root, context, _ = archive
    assert recent_editions(context)[0].filename == "b.pdf"
    (root / "data/editions.json").write_text('{"a.pdf": {"date": "not-a-date"}}', encoding="utf-8")
    assert recent_editions(context) == context.documents


def test_home_source_opens_original_page_without_api(archive):
    root, _, catalog = archive
    expected = home_selection(catalog)[0]
    app = AppTest.from_string(script(root), default_timeout=15).run()
    app.button(key="home_selected_0_pdf").click().run()
    assert not app.exception
    assert app.session_state["nav_section"] == "Archivio"
    assert app.session_state["archive_pdf"] == expected.metadata["filename"]
    assert app.session_state["archive_page"] == expected.metadata["page"]


def test_conversational_history_does_not_repeat_requests_and_handles_failure(archive):
    root, _, catalog = archive
    chunk = catalog.chunks[0]
    result = RagResult("Risposta documentata. [S1]", [Source("S1", chunk.id, chunk.metadata["filename"], chunk.metadata["page"], chunk.text, .2)], ["S1"], True)
    with patch("edicola.rag.ask_question", return_value=result) as ask:
        app = AppTest.from_string(script(root), default_timeout=15).run()
        app.text_input(key="rag_input").set_value("Prima domanda")
        app.checkbox(key="rag_authorized").check()
        app.button(key="rag_submit").click().run()
        assert not app.exception and len(app.chat_message) == 2
        assert app.chat_message[0].name == "user" and app.chat_message[1].name == "assistant"
        app.button(key="home_profile").click().run()
        assert ask.call_count == 1
        app.text_input(key="rag_input").set_value("Seconda domanda")
        app.button(key="rag_submit").click().run()
        assert not app.exception and len(app.chat_message) == 4 and ask.call_count == 2
        app.button(key="rag_pdf_S1").click().run()
        assert ask.call_count == 2
        ask.side_effect = RagError("Servizio momentaneamente non disponibile.")
        app.button(key="rag_submit").click().run()
        assert not app.exception and app.error and len(app.chat_message) == 4
        assert ask.call_count == 3
        visible = " ".join(item.value for item in app.caption)
        assert chunk.id not in visible and "distanza" not in visible


def test_empty_home_and_guest_have_clear_states_and_no_fake_content(archive):
    root, _, catalog = archive
    catalog.chunks.clear()
    with patch("streamlit.user", SimpleNamespace(is_logged_in=False)):
        app = AppTest.from_string(script(root), default_timeout=15).run()
    assert not app.exception
    assert any("Non ci sono ancora letture" in message.value for message in app.info)
    assert not any("account personale" in item.value and "non" not in item.value for item in app.caption)
    assert not app.get("file_uploader")


def test_excerpts_do_not_invent_headlines_or_activate_embedded_markup():
    original = "Il Comune ha approvato il piano. Il costo è 250.000 euro."
    short = excerpt(original, 35)
    assert short.endswith("…") and original.startswith(short[:-1])
    assert excerpt(original, 100) == original
    encoded = readable('<script>alert(1)</script> ![foto](https://example.org/x.png)')
    assert "<script>" not in encoded and "![foto](" not in encoded


def test_cards_and_shortcuts_wrap_for_narrow_containers(archive):
    root, _, _ = archive
    from streamlit.proto.Block_pb2 import Block
    app = AppTest.from_string(script(root), default_timeout=15).run()
    horizontal = [block for block in app.get("flex_container")
                  if block.proto.flex_container.direction == Block.FlexContainer.HORIZONTAL]
    assert horizontal and all(block.proto.flex_container.wrap for block in horizontal)
    # Un'unica griglia non impone la larghezza di quattro schede al viewport.
    cards = [block for block in app.get("flex_container") if block.proto.width_config.pixel_width == 340]
    assert cards and all(block.proto.flex_container.border for block in cards)


def test_untrusted_session_flags_do_not_authenticate(archive):
    root, _, _ = archive
    with patch("streamlit.user", SimpleNamespace(is_logged_in=False)), patch("streamlit.logout") as logout:
        app = AppTest.from_string(script(root), default_timeout=15)
        app.session_state["authenticated"] = True
        app.session_state["user_id"] = "another-user"
        app.run()
        assert not app.exception and app.button(key="account_logout").disabled
        assert not any(h.value == "Consigliati per te" for h in app.tabs[0].subheader)
        logout.assert_not_called()
