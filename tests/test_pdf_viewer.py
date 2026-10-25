"""PDF sintetici reali: pagine originali, isolamento dei file e navigazione UI."""

import io
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from streamlit.testing.v1 import AppTest

from edicola.chunking import prepare_documents
from edicola.ingestion import ingest_directory
from edicola.pdf_viewer import (PdfViewError, archive_context, read_original, render_page,
                                resolve_reference)
from edicola.rag import RagResult, Source
from test_ingestion import make_pdf


@pytest.fixture(autouse=True)
def offline():
    with patch("google.genai.Client", side_effect=AssertionError("API reali vietate")):
        yield


@pytest.fixture
def archive(tmp_path):
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "a.pdf").write_bytes(make_pdf())
    (incoming / "b.pdf").write_bytes(make_pdf(("Altra edizione.",)))
    registry = tmp_path / "data/archive.sqlite3"
    documents = ingest_directory(incoming, registry)
    prepared = prepare_documents(documents, registry)
    return archive_context(tmp_path, documents, prepared), prepared


def script(context):
    return f'''from pathlib import Path
import streamlit as st
from edicola.ingestion import ingest_directory
from edicola.chunking import prepare_documents
from edicola.pdf_viewer import archive_context, render_archive, source_button
root=Path({str(context.root)!r})
documents=ingest_directory(root / "data/incoming", root / "data/archive.sqlite3")
prepared=prepare_documents(documents, root / "data/archive.sqlite3")
context=archive_context(root, documents, prepared)
st.tabs(["Archivio PDF", "Chat AI"], key="nav_section", on_change="rerun")
render_archive(context, prepared)
'''


def test_selection_validation_original_download_and_page_png(archive):
    context, _ = archive
    document = resolve_reference(context, "a.pdf", 2)
    data = read_original(context, document)
    assert data == (context.root / "data/incoming/a.pdf").read_bytes()
    first = render_page(data, 1, 2, 100)
    second = render_page(data, 2, 2, 100)
    assert first.startswith(b"\x89PNG") and first != second
    with Image.open(io.BytesIO(first)) as image:
        assert image.width * image.height <= 12_000_000
        assert image.getbbox()


def test_pdf_graphics_and_layout_are_rendered_even_without_extractable_text(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=300)
    commands = DecodedStreamObject()
    commands.set_data(b"0 0 1 rg 20 30 50 60 re f")  # Rettangolo blu, senza testo.
    page[NameObject("/Contents")] = writer._add_object(commands)
    output = io.BytesIO()
    writer.write(output)
    png = render_page(output.getvalue(), 1, 1, 100)
    with Image.open(io.BytesIO(png)).convert("RGB") as image:
        assert image.size == (280, 420)
        assert image.getpixel((63, 336)) == (0, 0, 255)
        assert image.getpixel((5, 5)) == (255, 255, 255)


@pytest.mark.parametrize("filename,page", [("../a.pdf", 1), ("C:\\secret.pdf", 1), ("/secret.pdf", 1),
    ("a.pdf:stream.pdf", 1), ("not-acquired.pdf", 1), ("a.pdf", 0), ("a.pdf", 3), ("a.pdf", -1), ("a.pdf", True), ("a.pdf", "1")])
def test_invalid_paths_and_pages_are_rejected(archive, filename, page):
    with pytest.raises(PdfViewError):
        resolve_reference(archive[0], filename, page)


def test_unknown_and_obsolete_chunk_cannot_open_new_edition(archive):
    context, prepared = archive
    chunk = next(p for p in prepared if p.filename == "a.pdf").chunks[0]
    assert resolve_reference(context, "a.pdf", chunk.page, chunk.id)
    with pytest.raises(PdfViewError, match="versione precedente"):
        resolve_reference(context, "a.pdf", 1, "old-chunk")
    with pytest.raises(PdfViewError):
        resolve_reference(context, "b.pdf", 1, chunk.id)
    document = resolve_reference(context, "a.pdf", 1)
    (context.root / "data/incoming/a.pdf").write_bytes(make_pdf(("Nuovo contenuto.",)))
    with pytest.raises(PdfViewError, match="cambiato"):
        read_original(context, document)


def test_symlink_to_external_pdf_is_rejected(archive):
    context, _ = archive
    with patch.object(Path, "is_symlink", side_effect=lambda: True):
        with pytest.raises(PdfViewError, match="autorizzata"):
            resolve_reference(context, "a.pdf", 1)


@pytest.mark.parametrize("data,page,total", [(b"broken", 1, 1), (b"", 1, 1), (make_pdf(), 0, 2), (make_pdf(), 3, 2), (make_pdf(), 1, 3)])
def test_corrupt_and_nonexistent_pages_return_safe_errors(data, page, total):
    with pytest.raises(PdfViewError):
        render_page(data, page, total, 100)


def test_components_are_self_contained_and_support_fullscreen():
    from edicola.archive_components import GALLERY_JS, READER_JS, READER_CSS
    assert "data:image/png;base64," in READER_JS
    assert "https://" not in READER_JS + GALLERY_JS and "http://" not in READER_JS + GALLERY_JS
    assert "requestFullscreen" in READER_JS and "fullscreenEnabled" in READER_JS
    assert "textContent=item.title" in GALLERY_JS and "innerHTML" not in GALLERY_JS
    assert "height:70dvh" in READER_CSS


def test_ui_selects_pdf_turns_pages_zooms_and_preserves_original_files(archive):
    context, _ = archive
    files_before = {p.name: p.read_bytes() for p in (context.root / "data/incoming").iterdir()}
    source = script(context).replace('render_archive(context, prepared)', '''
if "archive_open" not in st.session_state:
    st.session_state["archive_open"]=True
    st.session_state["archive_pdf"]="a.pdf"
render_archive(context, prepared)''')
    app = AppTest.from_string(source, default_timeout=10).run()
    assert not app.exception and not app.error
    assert app.get("download_button") and app.get("bidi_component")
    app.button(key="archive_back").click().run()
    assert not app.exception and not app.session_state["archive_open"]
    assert files_before == {p.name: p.read_bytes() for p in (context.root / "data/incoming").iterdir()}
    assert not app.expander


def test_source_button_opens_exact_page_and_keeps_consent_without_api(archive):
    context, prepared = archive
    chunk = next(p for p in prepared if p.filename == "a.pdf").chunks[1]
    source = script(context) + f'''
st.checkbox("Consenso generazione", key="consent")
source_button("a.pdf", 2, context=context, chunk_id={chunk.id!r}, key="open_source")
'''
    app = AppTest.from_string(source, default_timeout=10).run()
    app.checkbox(key="consent").check().run()
    app.session_state["nav_section"] = "Chat AI"
    app.run()
    app.button(key="open_source").click().run()
    assert not app.exception and not app.error
    assert app.session_state["nav_section"] == "Archivio PDF"
    assert app.session_state["archive_pdf"] == "a.pdf"
    assert app.session_state["archive_page"] == 2 and app.session_state["archive_open"]
    assert app.checkbox(key="consent").value


def test_bad_source_is_not_an_active_button(archive):
    context, _ = archive
    source = script(context) + '\nsource_button("a.pdf", 99, context=context, key="invalid_source")'
    app = AppTest.from_string(source, default_timeout=10).run()
    assert not app.exception
    assert not any(b.key == "invalid_source" for b in app.button)
    assert any("pagina richiesta non esiste" in c.value for c in app.caption)


def test_chat_citation_navigates_without_regenerating_answer(archive):
    context, prepared = archive
    chunk = next(p for p in prepared if p.filename == "a.pdf").chunks[1]
    answer = RagResult("Risposta di prova. [S1]", [Source("S1", chunk.id, "a.pdf", 2, chunk.text, 0.1)], ["S1"], True)
    source = script(context) + '\nfrom edicola.reading_ui import render_chat\nrender_chat(root, context)'
    with patch("edicola.rag.ask_question", return_value=answer) as ask:
        app = AppTest.from_string(source, default_timeout=10).run()
        app.chat_input(key="rag_input").set_value("Domanda di prova")
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.run()
        assert not app.exception
        ask.assert_called_once()
        app.button(key="rag_pdf_S1").click().run()
        assert not app.exception and app.session_state["archive_page"] == 2
        ask.assert_called_once()
        assert app.session_state["consent_choices"][("text", "text-v2")]


@pytest.mark.parametrize("kind", ["dossier", "briefing", "personal", "timeline", "map"])
def test_sources_across_editorial_products_open_original_page(archive, kind):
    context, prepared = archive
    chunk = next(p for p in prepared if p.filename == "a.pdf").chunks[1]
    setup = f'''
from edicola.rag import Source
from edicola.editorial import EditorialResult
source=Source("S1", {chunk.id!r}, "a.pdf", 2, {chunk.text!r}, 0.1)
coverage={{"indexed":1,"total":2,"partial":True,"warnings":[],"files":[]}}
result=EditorialResult({kind!r}, "Titolo", [{{"heading":"Notizia [S1]","text":"Seconda pagina. [S1]"}}], [source], ["S1"], coverage, True)
'''
    if kind in ("dossier", "briefing"):
        action = '\nfrom edicola.reading_ui import render_editorial\nst.session_state["editorial_result"]=result\nrender_editorial(root, context, kind=result.kind.title())'
        button = "editorial_pdf_S1"
    elif kind == "personal":
        action = '\nfrom edicola.personalization_ui import show_product\nshow_product(result, context)'
        button = "personal_brief_pdf_S1"
    else:
        action = f'''
from edicola.knowledge import KnowledgeResult
from edicola.knowledge_validation import validate_timeline, validate_map
from edicola.knowledge_ui import render_knowledge
claim={{"text":"Seconda", "evidence":[{{"source_id":"S1","quote":source.text}}]}}
if {kind!r} == "timeline":
    data, diagnostics=validate_timeline({{"events":[{{"title":claim,"description":claim,"event_date":None,"date_evidence":None}}]}}, [source], coverage)
else:
    data, diagnostics=validate_map({{"nodes":[{{"id":"N1","kind":"concept","label":claim}}],"edges":[]}}, [source])
render_knowledge(KnowledgeResult({kind!r}, "Argomento", data, [source], coverage, diagnostics), context)
'''
        button = "undated_0_pdf_S1" if kind == "timeline" else "map_node_N1_pdf_S1"
    app = AppTest.from_string(script(context) + setup + action, default_timeout=10).run()
    assert not app.exception
    app.button(key=button).click().run()
    assert not app.exception and app.session_state["archive_page"] == 2
