"""Galleria editoriale e lettore: nessun contenuto tecnico nella vista cliente."""

import base64
import io
import json
import os
from datetime import date

from PIL import Image
from dotenv import dotenv_values
import streamlit as st

from edicola.archive_components import gallery_component, reader_component
from edicola.pdf_viewer import PdfViewError, open_reference, read_original, render_page, resolve_reference
from edicola.design import section_intro


def diagnostics_enabled(root):
    flag = "EDICOLA_ARCHIVE_DIAGNOSTICS"
    configured = os.environ.get(flag)
    if configured is None:
        configured = dotenv_values(root / ".env").get(flag, "0")
    return str(configured).strip().lower() in ("1", "true", "yes")


def edition_metadata(root, documents):
    try:
        raw = json.loads((root / "data/editions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    result = {}
    for index, document in enumerate(documents, 1):
        item = raw.get(document.filename, {}) if isinstance(raw, dict) else {}
        item = item if isinstance(item, dict) else {}
        publication = item.get("publication")
        title = publication.strip() if isinstance(publication, str) and publication.strip() else f"Edizione {index}"
        published = None
        try:
            value = item.get("date")
            if isinstance(value, str) and len(value) == 10:
                published = date.fromisoformat(value)
        except ValueError:
            pass
        months = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")
        label = f"{published.day} {months[published.month-1]} {published.year}" if published else "Data non disponibile"
        result[document.filename] = {"title": title, "date": label, "pages": document.total_pages}
    return result


@st.cache_data(show_spinner=False, max_entries=24)
def cover_thumbnail(data, total):
    png = render_page(data, 1, total, 75)
    with Image.open(io.BytesIO(png)) as image:
        image.thumbnail((320, 420))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def edition_filter(documents, metadata, *, key):
    """Filtro condiviso Home/Archivio: soltanto date curate, mai Oggi/Ieri fittizi."""
    dates = list(dict.fromkeys(metadata[d.filename]["date"] for d in documents
                              if metadata[d.filename]["date"] != "Data non disponibile"))
    selected = st.selectbox("Edizioni disponibili", ["Tutte le edizioni"] + dates, key=key, width=280)
    return [d for d in documents if selected == "Tutte le edizioni" or metadata[d.filename]["date"] == selected]


def render_gallery(context, metadata, *, documents=None, title="Le edizioni", key="archive_gallery"):
    documents = context.documents if documents is None else documents
    section_intro(title, "Sfoglia le prime pagine e apri il quotidiano originale.", "Le edizioni dell’archivio")
    cards = []
    for document in documents:
        thumbnail = None
        if document.total_pages > 0:
            try:
                original = read_original(context, document)
                thumbnail = base64.b64encode(cover_thumbnail(original, document.total_pages)).decode("ascii")
            except PdfViewError:
                pass
        cards.append({**metadata[document.filename], "thumbnail": thumbnail})
    def selected():
        index = st.session_state.get(key, {}).get("open_edition")
        if type(index) is not int or not 0 <= index < len(documents):
            st.session_state["pdf_navigation_error"] = "Edizione non disponibile."
            return
        try:
            open_reference(context, documents[index].filename, 1)
        except PdfViewError:
            st.session_state["pdf_navigation_error"] = "Questa edizione non è consultabile al momento."
    gallery_component(data={"editions": cards}, key=key, on_open_edition_change=selected)


def render_reader(context, document, metadata):
    def back():
        st.session_state["archive_open"] = False
    actions = st.container(horizontal=True, width="content")
    with actions:
        st.button("← Edizioni", key="archive_back", on_click=back)
    st.subheader(metadata["title"])
    st.caption(f"{metadata['date']} · {document.total_pages} pagine")
    page = st.session_state.get("archive_page", 1)
    if type(page) is not int or not 1 <= page <= document.total_pages:
        st.info("La pagina richiesta non è disponibile. Torna alle edizioni e riapri il quotidiano.")
        return
    st.session_state["archive_page_jump"] = page
    def jump():
        target = st.session_state.get("archive_page_jump")
        if type(target) is int and 1 <= target <= document.total_pages:
            st.session_state["archive_page"] = target
    with st.container(horizontal=True, width="content", vertical_alignment="center"):
        st.number_input("Vai a pagina", min_value=1, max_value=document.total_pages,
                        key="archive_page_jump", on_change=jump, width=150)
        st.caption("Frecce per sfogliare · zoom e schermo intero nel lettore")
    try:
        resolve_reference(context, document.filename, page)
        original = read_original(context, document)
        def turn():
            target = st.session_state.get("archive_reader", {}).get("page")
            try:
                resolve_reference(context, document.filename, target)
                st.session_state["archive_page"] = target
            except PdfViewError:
                st.session_state["pdf_navigation_error"] = "Pagina non disponibile."
        # Una sola pagina in alta risoluzione; zoom e adattamento restano locali al browser.
        with st.spinner("Apertura del quotidiano…"):
            png = render_page(original, page, document.total_pages, 150)
        reader_component(data={"png": base64.b64encode(png).decode("ascii"), "page": page,
                               "total": document.total_pages, "title": metadata["title"]},
                         key="archive_reader", on_page_change=turn)
        with actions:
            st.download_button("Scarica PDF", original, file_name=document.filename,
                               mime="application/pdf", key="pdf_download", on_click="ignore", icon=":material/download:")
    except PdfViewError:
        st.info("Questa edizione non è consultabile al momento. Torna alla galleria e scegli un altro quotidiano.")


def render_diagnostics(context, prepared):
    if not diagnostics_enabled(context.root):
        return
    with st.expander("Diagnostica archivio"):
        st.dataframe([{"PDF": d.filename, "Pagine": d.total_pages, "Stato": d.status_label,
                       "SHA-256": d.sha256} for d in context.documents], hide_index=True)
        if prepared:
            filename = st.session_state.get("archive_pdf", context.documents[0].filename)
            document = next((d for d in context.documents if d.filename == filename), context.documents[0])
            if document.pages:
                page = st.selectbox("Testo estratto · pagina", document.pages, format_func=lambda p: str(p.number), key="archive_extracted_page")
                st.text(page.text)
            chunks = next((p.chunks for p in prepared if p.filename == document.filename), [])
            if chunks:
                chunk = st.selectbox("Anteprima chunk", chunks, format_func=lambda c: f"Chunk {c.position} — pagina {c.page}", key="archive_chunk")
                st.caption(f"ID: {chunk.id}")
                st.text(chunk.text)


def render_archive_view(context, prepared):
    if st.session_state.pop("pdf_navigation_error", None):
        st.info("La fonte richiesta non è disponibile nell'edizione corrente.")
    if not context.documents:
        st.header("Le edizioni")
        st.info("Non ci sono ancora edizioni disponibili.")
        return
    metadata = edition_metadata(context.root, context.documents)
    selected = st.session_state.get("archive_pdf")
    document = next((d for d in context.documents if d.filename == selected), None)
    if st.session_state.get("archive_open") and document is not None:
        with st.container(horizontal=True, horizontal_alignment="center"):
            with st.container(width=740):
                render_reader(context, document, metadata[selected])
    else:
        with st.container(horizontal=True, horizontal_alignment="center"):
            with st.container(width=1120):
                visible = edition_filter(context.documents, metadata, key="archive_edition_date")
                render_gallery(context, metadata, documents=visible)
    render_diagnostics(context, prepared)
