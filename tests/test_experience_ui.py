"""Esperienza editoriale: archivio sintetico, identità simulate, nessuna API."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from editorial_adapter import navigate_to
from edicola.archive import read_active_chunks
from edicola.chunking import prepare_documents
from edicola.editorial_selection import Catalog
from edicola.for_you import select_feed
from edicola.experience_ui import SECTIONS, excerpt, home_selection, readable, recent_editions
from edicola.ingestion import ingest_directory
from edicola.pdf_viewer import archive_context
from edicola.profiles import Profile, load_profile, save_profile
from edicola.rag import RagError, RagResult, Source
from test_ingestion import make_pdf
from editorial_adapter import cards_adapter


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
    with patch("edicola.editorial_components.cards_component", side_effect=cards_adapter), patch("google.genai.Client", side_effect=AssertionError("API vietate")), patch(
        "edicola.experience_ui.read_catalog", return_value=catalog
    ), patch("edicola.personalization_ui.read_catalog", return_value=catalog), patch(
        "edicola.personalization_ui.list_products", return_value=[]
    ):
        yield tmp_path, archive_context(tmp_path, documents, prepared), catalog


def script(root):
    # Monta l'app reale con il solo archivio sintetico della fixture.
    return (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8").replace(
        "ROOT = Path(__file__).resolve().parent", f"ROOT = Path({str(root)!r})")


@pytest.mark.parametrize("logged_in", [False, True])
def test_identity_home_and_logout_are_not_fake_authentication(archive, logged_in):
    root, context, _ = archive
    save_profile(root, Profile(interests=["trasporti"]))
    with patch("streamlit.user", SimpleNamespace(is_logged_in=logged_in)), patch("streamlit.logout") as logout:
        app = AppTest.from_string(script(root), default_timeout=15).run()
        assert not app.exception
        navigate_to(app, "Per te")
        assert any(h.value == ("Notizie per i tuoi interessi" if logged_in else "Notizie da esplorare")
                   for h in app.subheader)
        navigate_to(app, "Il mio profilo")
        # La demo locale è condivisa: non presenta pulsanti Google fittizi.
        assert not [button for button in app.button if button.key == "account_logout"]
        home_headers = [h.value for h in app.subheader]
        assert home_headers
        assert any("condiviso" in caption.value for caption in app.caption)
        assert load_profile(root).user_id == "demo"
        assert load_profile(root).interests == ["trasporti"]
        logout.assert_not_called()


@pytest.mark.parametrize("button,destination", [("home_products_test_2", "Chat AI"), ("home_products_test_3", "Briefing"),
                                                ("home_products_test_4", "Podcast"), ("home_products_test_5", "Esplora")])
def test_shortcuts_keep_consents_and_do_not_generate(archive, button, destination):
    root, _, _ = archive
    with patch("edicola.rag.ask_question", side_effect=AssertionError("RAG automatico")), patch(
        "edicola.personalization_ui.generate_personal_briefing", side_effect=AssertionError("Generazione automatica")
    ):
        app = AppTest.from_string(script(root), default_timeout=15).run()
        app.session_state["consent_choices"] = {("text", "text-v3"): True}
        app.run()
        app.button(key=button).click().run()
        assert not app.exception
        assert app.session_state["nav_section"] == destination
        assert len(app.chat_input) == (1 if destination == "Chat AI" else 0)
        assert app.session_state["consent_choices"][("text", "text-v3")]
        assert app.session_state["nav_section"] in SECTIONS


def test_cards_save_remove_and_preferences_feedback(archive):
    root, _, catalog = archive
    save_profile(root, Profile(interests=["trasporti"]))
    with patch("streamlit.user", SimpleNamespace(is_logged_in=True)):
        app = AppTest.from_string(script(root), default_timeout=15).run()
        navigate_to(app, "Per te")
        save = next(button for button in app.button if button.label == "Salva lettura")
    app.button(key=save.key).click().run()
    assert not app.exception
    assert len(load_profile(root).saved) == 1
    assert any("Lettura salvata" in success.value for success in app.success)
    identity = next(iter(load_profile(root).saved))
    navigate_to(app, "Il mio profilo")
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


def test_recommended_news_open_original_page_without_api(archive):
    root, _, catalog = archive
    app = AppTest.from_string(script(root), default_timeout=15).run()
    navigate_to(app, "Per te")
    entries = select_feed(catalog, None)
    assert entries
    app.button(key="for_you_0_pdf").click().run()
    assert not app.exception
    assert app.session_state["nav_section"] == "In edicola"
    assert app.session_state["archive_pdf"] == entries[0].chunk.metadata["filename"]
    assert app.session_state["archive_page"] == entries[0].chunk.metadata["page"]


def test_conversational_history_does_not_repeat_requests_and_handles_failure(archive):
    root, _, catalog = archive
    chunk = catalog.chunks[0]
    result = RagResult("Risposta documentata. [S1]", [Source("S1", chunk.id, chunk.metadata["filename"], chunk.metadata["page"], chunk.text, .2)], ["S1"], True)
    with patch("edicola.rag.ask_question", return_value=result) as ask:
        app = AppTest.from_string(script(root), default_timeout=15).run()
        navigate_to(app, "Chat AI")
        app.chat_input(key="rag_input").set_value("Prima domanda")
        app.session_state["consent_choices"] = {("text", "text-v3"): True}
        app.run()
        assert not app.exception and len(app.chat_message) == 2
        assert app.chat_message[0].name == "user" and app.chat_message[1].name == "assistant"
        navigate_to(app, "Podcast")
        navigate_to(app, "Chat AI")
        assert ask.call_count == 1
        app.chat_input(key="rag_input").set_value("Seconda domanda")
        app.run()
        assert not app.exception and len(app.chat_message) == 4 and ask.call_count == 2
        app.button(key="rag_pdf_S1").click().run()
        assert ask.call_count == 2
        navigate_to(app, "Chat AI")
        ask.side_effect = RagError("Servizio momentaneamente non disponibile.")
        app.chat_input(key="rag_input").set_value("Terza domanda").run()
        assert not app.exception and app.error and len(app.chat_message) == 6
        assert ask.call_count == 3
        visible = " ".join(item.value for item in app.caption)
        assert chunk.id not in visible and "distanza" not in visible


def test_empty_home_and_guest_have_clear_states_and_no_fake_content(archive):
    root, _, catalog = archive
    catalog.chunks.clear()
    with patch("streamlit.user", SimpleNamespace(is_logged_in=False)):
        app = AppTest.from_string(script(root), default_timeout=15).run()
    assert not app.exception
    navigate_to(app, "Per te")
    assert any("non sono disponibili" in message.value for message in app.info)
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
    from edicola.editorial_components import CARD_CSS
    assert "overflow-x:auto" in CARD_CSS and "@media(max-width:600px)" in CARD_CSS
    assert ".cards.products{display:grid;grid-template-columns:repeat(2" in CARD_CSS



def test_untrusted_session_flags_do_not_authenticate(archive):
    root, _, _ = archive
    with patch("streamlit.user", SimpleNamespace(is_logged_in=False)), patch("streamlit.logout") as logout:
        app = AppTest.from_string(script(root), default_timeout=15)
        app.session_state["authenticated"] = True
        app.session_state["user_id"] = "another-user"
        app.run()
        assert not app.exception
        navigate_to(app, "Per te")
        assert not any(h.value == "Notizie per i tuoi interessi" for h in app.subheader)
        navigate_to(app, "Il mio profilo")
        assert not [b for b in app.button if b.key == "account_logout"]
        assert any("condivis" in c.value for c in app.caption)
        logout.assert_not_called()


def test_home_selection_whitespace_duplicates_are_per_edition(archive):
    _, _, catalog = archive
    original = catalog.chunks[0]
    duplicate = replace(original, id="copy-whitespace", text="  " + "   ".join(original.text.split()) + " ")
    catalog.chunks.append(duplicate)
    selected = home_selection(catalog, limit=20)
    from_original = [chunk for chunk in selected if chunk.metadata["filename"] == original.metadata["filename"]
                     and " ".join(chunk.text.split()) == " ".join(original.text.split())]
    assert len(from_original) == 1
