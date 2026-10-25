"""Lettore PDF locale: raster delle pagine originali, nessun testo ricostruito."""

import hashlib
import io
import math
import threading
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import streamlit as st

PDF_LOCK = threading.Lock()  # PDFium non va eseguito in parallelo tra sessioni.


class PdfViewError(RuntimeError):
    """Errore leggibile senza percorsi locali o dettagli del parser."""


@dataclass
class ArchiveContext:
    root: Path
    documents: list
    chunk_references: dict


def archive_context(root, documents, prepared):
    references = {}
    documents_by_name = {d.filename: d for d in documents}
    for item in prepared:
        for chunk in item.chunks:
            references.setdefault(chunk.id, set()).add((chunk.filename, chunk.page, documents_by_name[chunk.filename].sha256))
    return ArchiveContext(root, documents, references)


def resolve_reference(context, filename, page, chunk_id=None, *, pdf_sha256=None):
    if (not isinstance(filename, str) or not filename or any(c in filename for c in ("/", "\\", ":", "\0"))
            or Path(filename).name != filename or Path(filename).suffix.lower() != ".pdf"):
        raise PdfViewError("Riferimento al PDF non valido.")
    document = next((d for d in context.documents if d.filename == filename), None)
    if document is None:
        raise PdfViewError("Il PDF non appartiene all'archivio corrente.")
    if pdf_sha256 is not None and document.sha256 != pdf_sha256:
        raise PdfViewError("La fonte non corrisponde più all'edizione salvata nella conversazione.")
    if type(page) is not int or not 1 <= page <= document.total_pages:
        raise PdfViewError("La pagina richiesta non esiste in questo quotidiano.")
    if chunk_id is not None and (filename, page, document.sha256) not in context.chunk_references.get(chunk_id, set()):
        raise PdfViewError("La fonte appartiene a una versione precedente o non è più presente nell'archivio corrente.")
    safe_path(context, filename)
    return document


def safe_path(context, filename):
    try:
        base = (context.root / "data/incoming").resolve()
        candidate = context.root / "data/incoming" / filename
        if (not base.is_relative_to(context.root.resolve()) or candidate.is_symlink()
                or candidate.resolve().parent != base or not candidate.is_file()):
            raise PdfViewError("PDF locale non disponibile nella cartella autorizzata.")
        return candidate
    except (OSError, RuntimeError, ValueError):
        raise PdfViewError("PDF locale non disponibile nella cartella autorizzata.")


def read_original(context, document):
    # Solo documenti dell'elenco acquisito, mai un percorso fornito dalla UI.
    if not any(d is document for d in context.documents):
        raise PdfViewError("Documento non appartenente all'archivio.")
    try:
        data = safe_path(context, document.filename).read_bytes()
    except OSError:
        raise PdfViewError("Impossibile leggere il PDF locale.") from None
    if not data or not document.sha256 or hashlib.sha256(data).hexdigest() != document.sha256:
        raise PdfViewError("Il PDF è vuoto o è cambiato rispetto alla versione acquisita. Aggiornare l'archivio prima di consultarlo.")
    return data


@st.cache_data(show_spinner=False, max_entries=12)
def render_page(data: bytes, page: int, total: int, zoom: int):
    if type(page) is not int or type(total) is not int or not 1 <= page <= total or zoom not in (75, 100, 125, 150, 200):
        raise PdfViewError("Pagina o zoom non validi.")
    with PDF_LOCK:
        return raster_page(data, page, total, zoom)


def raster_page(data, page, total, zoom):
    document = pdf_page = bitmap = image = None
    try:
        document = pdfium.PdfDocument(data)
        if len(document) != total:
            raise PdfViewError("Il numero di pagine del PDF non coincide con l'archivio. Aggiornare la consultazione.")
        pdf_page = document[page - 1]
        width, height = pdf_page.get_size()
        if not width > 0 or not height > 0:
            raise PdfViewError("Dimensioni della pagina PDF non valide.")
        # Limite di memoria per grandi pagine di giornale: massimo 12 megapixel.
        scale = min(1.4 * zoom / 100, math.sqrt(12_000_000 / (width * height)))
        bitmap = pdf_page.render(scale=scale)
        image = bitmap.to_pil()
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    except PdfViewError:
        raise
    except Exception:
        raise PdfViewError("PDF non visualizzabile: documento danneggiato, protetto o formato non supportato.") from None
    finally:
        for resource in (image, bitmap, pdf_page, document):
            if resource is not None:
                resource.close()


def open_reference(context, filename, page, chunk_id=None, *, pdf_sha256=None):
    document = resolve_reference(context, filename, page, chunk_id, pdf_sha256=pdf_sha256)
    read_original(context, document)  # Verifica anche il contenuto attuale prima del salto.
    st.session_state["archive_pdf"] = filename
    st.session_state["archive_page"] = page
    st.session_state["archive_open"] = True
    from edicola.product_navigation import destination, cancel_navigation_action
    cancel_navigation_action()
    st.session_state["nav_section"] = destination("archive")


def source_button(filename, page, *, context=None, key, chunk_id=None, label=None, help_text=None, pdf_sha256=None):
    if context is None:
        return
    try:
        resolve_reference(context, filename, page, chunk_id, pdf_sha256=pdf_sha256)
    except PdfViewError as exc:
        st.caption(str(exc))
        return
    def navigate():
        try:
            open_reference(context, filename, page, chunk_id, pdf_sha256=pdf_sha256)
        except PdfViewError as exc:
            st.session_state["pdf_navigation_error"] = str(exc)
            from edicola.product_navigation import destination, cancel_navigation_action
            cancel_navigation_action()
            st.session_state["nav_section"] = destination("archive")
    st.button(label or f"Apri PDF · pagina {page}", key=key, help=help_text if help_text is not None else filename,
              on_click=navigate, type="tertiary" if label else "secondary", width="content")


def render_archive(context, prepared):
    from edicola.archive_ui import render_archive_view
    render_archive_view(context, prepared)

