"""Verifica l'avvio della UI su archivio temporaneo."""

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from edicola.ingestion import ingest_directory
from edicola.chunking import prepare_documents
from edicola.rag import RagError, RagResult, Source
from edicola.experience_ui import readable
from edicola.reading_ui import chat_markdown
from edicola.editorial import EditorialResult
from edicola.knowledge import KnowledgeResult
from edicola.knowledge_validation import validate_map, validate_timeline
import pytest
from test_ingestion import make_pdf


@pytest.fixture(autouse=True)
def isolated_podcast_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("EDICOLA_ARCHIVE_DIAGNOSTICS", "1")
    from edicola.profiles import Profile
    from edicola.pdf_viewer import archive_context
    with patch("edicola.podcast_ui.list_products", return_value=[]), patch(
        "edicola.personalization_ui.load_profile", return_value=Profile()
    ), patch("edicola.personalization_ui.list_products", return_value=[]), patch(
        "edicola.pdf_viewer.archive_context", side_effect=lambda _, docs, prepared: archive_context(tmp_path, docs, prepared)
    ):
        yield


def test_app_acquires_on_start_and_consults_without_extracting_again(tmp_path):
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "quotidiano.pdf").write_bytes(make_pdf())
    registry = tmp_path / "registry.sqlite3"

    def ingest_test_archive(*_args):
        return ingest_directory(incoming, registry)

    def prepare_test_archive(documents, _registry):
        return prepare_documents(documents, registry)

    with patch("edicola.ingestion.ingest_directory", side_effect=ingest_test_archive), patch(
        "edicola.chunking.prepare_documents", side_effect=prepare_test_archive
    ), patch("google.genai.Client", side_effect=AssertionError("Chiamata esterna all'avvio")), patch(
        "edicola.rag.ask_question", side_effect=AssertionError("RAG automatico non consentito")
    ) as ask, patch("edicola.editorial.generate_product", side_effect=AssertionError("Prodotti automatici non consentiti")) as generate, patch(
        "edicola.knowledge.generate_knowledge", side_effect=AssertionError("Visualizzazioni automatiche non consentite")
    ) as knowledge:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=10).run()
        assert not app.exception
        assert app.metric[0].value == "1"
        assert app.metric[2].value == "2"
        assert app.get("bidi_component")
        assert not app.chat_input
        ask.assert_not_called()
        generate.assert_not_called()
        knowledge.assert_not_called()
        assert len(app.get("file_uploader")) == 0
        app.pills(key="nav_section").set_value("Archivio PDF").run()
        assert app.dataframe[0].value.iloc[0]["Pagine"] == 2
        assert "pagina 1" in app.selectbox(key="archive_chunk").options[0]
        with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("estrazione ripetuta")), patch(
            "edicola.chunking.build_chunks", side_effect=AssertionError("chunking ripetuto")
        ):
            app.selectbox(key="archive_extracted_page").select_index(1).run()
            assert not app.exception
            assert any("Seconda pagina" in item.value for item in app.text)
            app.selectbox(key="archive_chunk").select_index(1).run()
            assert not app.exception
            assert any(item.value == "Seconda pagina" for item in app.text)


def test_rag_ui_requires_authorization_and_keeps_response_on_rerun(tmp_path):
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "quotidiano.pdf").write_bytes(make_pdf())
    registry = tmp_path / "registry.sqlite3"
    result = RagResult("Il consiglio ha approvato il piano. [S1]", [
        Source("S1", prepare_documents(ingest_directory(incoming, registry), registry)[0].chunks[0].id,
               "quotidiano.pdf", 1, "Il consiglio ha approvato il piano.", 0.2)
    ], ["S1"], True)
    with patch("edicola.ingestion.ingest_directory", side_effect=lambda *_: ingest_directory(incoming, registry)), patch(
        "edicola.chunking.prepare_documents", side_effect=lambda docs, _: prepare_documents(docs, registry)
    ), patch("edicola.rag.ask_question", return_value=result) as ask, patch(
        "google.genai.Client", side_effect=AssertionError("API reali vietate")
    ):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=10).run()
        app.pills(key="nav_section").set_value("Chat AI").run()
        app.chat_input(key="rag_input").set_value("Quale piano è stato approvato?")
        ask.assert_not_called()
        app.run()
        ask.assert_not_called()
        assert app.button(key="consent_accept")
        app.button(key="consent_accept").click().run()
        assert not app.exception
        ask.assert_called_once()
        assert ask.call_args.kwargs["authorize_external"] is True
        assert any(item.value == chat_markdown(result.answer) for item in app.markdown)
        assert app.button(key="rag_pdf_S1")
        app.pills(key="nav_section").set_value("Archivio PDF").run()
        app.selectbox(key="archive_extracted_page").select_index(1).run()
        app.pills(key="nav_section").set_value("Chat AI").run()
        assert ask.call_count == 1
        assert any(item.value == chat_markdown(result.answer) for item in app.markdown)
        ask.side_effect = RagError("Quota Gemini esaurita.")
        app.chat_input(key="rag_input").set_value("Quale piano è stato approvato?")
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.run()
        assert not app.exception
        assert "limite di utilizzo" in app.error[0].value
        assert len(app.chat_message) == 4  # La nuova domanda e il suo errore non cancellano il turno precedente.
        assert ask.call_count == 2  # Un flusso per ciascuno dei due invii autorizzati.
        app.pills(key="nav_section").set_value("Archivio PDF").run()
        app.selectbox(key="archive_extracted_page").select_index(0).run()
        assert not app.exception
        assert ask.call_count == 2  # Il rerun dopo l'errore non ritenta la domanda.


def test_editorial_ui_only_generates_on_authorized_submit(tmp_path):
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "quotidiano.pdf").write_bytes(make_pdf())
    registry = tmp_path / "registry.sqlite3"
    result = EditorialResult("dossier", "Dossier sui trasporti [S1]", [
        {"heading": "Introduzione", "text": "Testo documentato. [S1]"}
    ], [Source("S1", "id", "quotidiano.pdf", 1, "Un passaggio del quotidiano realmente recuperato.", 0.1)],
        ["S1"], {"indexed": 1, "total": 2, "partial": True, "warnings": ["Data non disponibile."],
                 "files": [{"pdf": "quotidiano.pdf", "publication": "", "date": "", "indexed": 1, "total": 2}]}, True)
    with patch("edicola.ingestion.ingest_directory", side_effect=lambda *_: ingest_directory(incoming, registry)), patch(
        "edicola.chunking.prepare_documents", side_effect=lambda docs, _: prepare_documents(docs, registry)
    ), patch("edicola.editorial.generate_product", return_value=result) as generate, patch(
        "google.genai.Client", side_effect=AssertionError("API reali vietate")
    ):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=10).run()
        generate.assert_not_called()
        app.pills(key="nav_section").set_value("Dossier").run()
        app.button(key="dossier_submit").click().run()
        generate.assert_not_called()
        app.text_input(key="editorial_topic").set_value("Trasporti")
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.button(key="dossier_submit").click().run()
        assert not app.exception
        generate.assert_called_once()
        assert generate.call_args.args[:2] == ("dossier", "Trasporti")
        assert generate.call_args.kwargs["authorize_external"] is True
        assert any("parzialmente indicizzato" in item.value for item in app.warning)
        assert any("quotidiano.pdf" in item.value for item in app.text)
        app.pills(key="nav_section").set_value("Archivio PDF").run()
        app.selectbox(key="archive_extracted_page").select_index(1).run()
        assert generate.call_count == 1
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.pills(key="nav_section").set_value("Briefing").run()
        app.button(key="briefing_submit").click().run()
        assert not app.exception
        assert generate.call_args.args[0] == "briefing"
        assert generate.call_count == 2


def test_timeline_ui_shows_context_date_and_announced_state_without_api():
    script = '''
from edicola.knowledge_ui import render_event
from edicola.knowledge_validation import validate_timeline
from edicola.rag import Source
text = "Mercoledì 21 ottobre si terrà l'incontro sui trasporti del Comune di Roma."
source = Source("S1", "a", "a.pdf", 2, text, 0.2)
claim = {"text": "Incontro sui trasporti", "evidence": [{"source_id": "S1", "quote": text}]}
event = {"title": claim, "description": claim, "event_date": None,
         "date_evidence": {"source_id": "S1", "quote": text}}
coverage = {"files": [{"pdf": "a.pdf", "publication": "Testata verificata", "date": "2026-10-17"}]}
data, _ = validate_timeline({"events": [event]}, [source], coverage)
render_event(data["events"][0])
'''
    with patch("google.genai.Client", side_effect=AssertionError("API reali vietate")):
        app = AppTest.from_string(script, default_timeout=10).run()
    assert not app.exception
    captions = " ".join(item.value for item in app.caption)
    assert "2026-10-21" in captions
    assert "Data completata tramite metadati verificati" in captions
    assert "Annunciato / programmato" in captions
    assert "edizione 2026-10-17" in captions
    assert "Data di pubblicazione delle fonti: [S1] 2026-10-17" in captions
    assert any("Mercoledì 21 ottobre" in item.value for item in app.text)


@pytest.mark.parametrize("has_edges", [True, False, "rejected"])
def test_map_ui_uses_compact_list_when_no_links_and_preserves_evidence(has_edges):
    script = '''
from types import SimpleNamespace
from edicola.knowledge_ui import render_knowledge
from edicola.knowledge_validation import validate_map
from edicola.rag import Source
text = "Il Comune di Roma ha approvato il piano per i trasporti."
source = Source("S1", "chunk-1", "giornale.pdf", 3, text, 0.1)
evidence = [{"source_id": "S1", "quote": text}]
raw = {"nodes": [
    {"id": "N1", "kind": "organization", "label": {"text": "Comune di Roma", "evidence": evidence}},
    {"id": "N2", "kind": "concept", "label": {"text": "piano", "evidence": evidence}}],
    "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented",
               "label": {"text": "approvato", "evidence": evidence}}]}
if HAS_EDGES == "rejected":
    raw["edges"][0]["label"]["text"] = "causa"
elif not HAS_EDGES:
    raw["edges"] = []
data, diagnostics = validate_map(raw, [source])
result = SimpleNamespace(kind="map", topic="Trasporti", data=data, sources=[source], diagnostics=diagnostics,
    coverage={"indexed": 1, "total": 1, "partial": False, "warnings": []}, from_cache=False)
render_knowledge(result)
'''.replace("HAS_EDGES", repr(has_edges))
    with patch("google.genai.Client", side_effect=AssertionError("API reali vietate")):
        app = AppTest.from_string(script, default_timeout=10).run()
    assert not app.exception
    assert len(app.get("graphviz_chart")) == 1  # Anche soli concetti: raggruppamento senza archi.
    assert any(exp.label == "Diagnostica · sviluppo" for exp in app.expander)
    if has_edges is True:
        assert app.json
        assert any("[S1] giornale.pdf — pagina 3" in caption.value for caption in app.caption)
        assert any("ha approvato il piano" in text.value for text in app.text)
    elif has_edges == "rejected":
        assert app.json and not app.info
        assert any("Predicato non presente" in str(frame.value) for frame in app.dataframe)
    else:
        assert app.json and not app.info
        assert any("senza relazioni documentate" in caption.value for caption in app.caption)


@pytest.mark.parametrize("kind,submit_key", [("timeline", "timeline_submit"), ("map", "map_submit")])
def test_knowledge_ui_renders_and_does_not_repeat_calls(tmp_path, kind, submit_key):
    from test_knowledge import COVERAGE, SOURCES, event, map_data
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "quotidiano.pdf").write_bytes(make_pdf())
    registry = tmp_path / "registry.sqlite3"
    data, diagnostics = (validate_timeline({"events": [event()]}, SOURCES, COVERAGE) if kind == "timeline"
                         else validate_map(map_data(), SOURCES))
    result = KnowledgeResult(kind, "Trasporti", data, SOURCES, COVERAGE, diagnostics)
    with patch("edicola.ingestion.ingest_directory", side_effect=lambda *_: ingest_directory(incoming, registry)), patch(
        "edicola.chunking.prepare_documents", side_effect=lambda docs, _: prepare_documents(docs, registry)
    ), patch("edicola.knowledge.generate_knowledge", return_value=result) as generate, patch(
        "google.genai.Client", side_effect=AssertionError("API reali vietate")
    ):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=10).run()
        generate.assert_not_called()
        app.pills(key="nav_section").set_value("Mappe concettuali" if kind == "map" else "Timeline").run()
        app.button(key=submit_key).click().run()
        generate.assert_not_called()
        app.text_input(key="knowledge_topic_" + kind).set_value("Trasporti")
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.button(key=submit_key).click().run()
        assert not app.exception
        assert generate.call_args.args[:2] == (kind, "Trasporti")
        assert generate.call_args.kwargs["authorize_external"] is True
        assert any("Copertura parziale" in item.value for item in app.caption)
        if kind == "map":
            assert len(app.get("graphviz_chart")) == 1
        else:
            assert any("2026-10-12" in item.value for item in app.caption)
        app.pills(key="nav_section").set_value("Archivio PDF").run()
        app.selectbox(key="archive_extracted_page").select_index(1).run()
        assert not app.exception
        assert generate.call_count == 1

