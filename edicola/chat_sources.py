"""Citazioni compatte: un collegamento per pagina, dettagli secondari in popover."""

from collections import OrderedDict
import re
import streamlit as st

from edicola.pdf_viewer import source_button, resolve_reference, PdfViewError
from edicola.rag_context import source_editions
from edicola.article_evidence import article_reference


def document_label(context, filename, page):
    from edicola.archive_ui import edition_metadata
    info = edition_metadata(context.root, context.documents).get(filename, {}) if context else {}
    return (info.get("title") or "Documento dell’archivio") + f" · pagina {page}"


def citation_text(text, source_ids):
    """Numeri di citazione per il lettore, senza cambiare riferimenti persistenti."""
    numbers = {identity: str(index) for index, identity in enumerate(dict.fromkeys(source_ids), 1)}
    return re.sub(r"\[(S\d+)\]", lambda match: "[" + numbers[match[1]] + "]" if match[1] in numbers else "", text)


def render_contributions(sources, used_source_ids, root, *, editions=None, compact=False):
    """Compatibilità con vecchi prodotti; le fonti sono mostrate nei rispettivi link PDF."""
    return



def render_context_limit(coverage):
    if coverage.get("partial") or coverage.get("context_selection", {}).get("omitted_passages", 0):
        st.caption("Questa lettura è una selezione: puoi approfondire nelle edizioni originali.")


def render_sources(result, *, index, last, root, context, formatter, namespace="rag"):
    """Elenca soltanto le fonti citate, con link diretto al PDF e alla pagina."""
    editions = getattr(result, "source_editions", {}) or source_editions(root, result.sources)
    references = getattr(result, "source_references", {}) or {}
    articles = getattr(result, "source_articles", {}) or {}
    used = set(result.used_source_ids)
    groups = OrderedDict()
    for source in result.sources:
        if source.id not in used:
            continue
        sha = references.get(source.id, {}).get("pdf_sha256")
        groups.setdefault((source.filename, source.page, sha), []).append(source)
    if not groups:
        return
    st.markdown("**Fonti**")
    with st.container(horizontal=True, gap="small"):
        for (filename, page, sha), members in groups.items():
            source = members[0]
            if context:
                for candidate in members:
                    try:
                        resolve_reference(context, filename, page, candidate.chunk_id, pdf_sha256=sha)
                        source = candidate
                        break
                    except PdfViewError:
                        pass
            info = editions.get(source.id, {})
            name = info.get("publication") or "Quotidiano"
            published = info.get("publication_date")
            label = name + (f" · {published}" if published else "") + f" · pagina {page}"
            article = articles.get(source.id)
            if article and article.get("title"):
                label += " · " + article["title"]
            key = f"{namespace}_pdf_{source.id}" if last else f"{namespace}_history_{index}_{source.id}"
            source_button(filename, page, context=context, chunk_id=source.chunk_id, pdf_sha256=sha,
                          key=key, label=formatter(label), help_text="Apri la pagina del quotidiano")
