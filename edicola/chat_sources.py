"""Citazioni compatte: un collegamento per pagina, dettagli secondari in popover."""

from collections import OrderedDict
import re
import streamlit as st

from edicola.pdf_viewer import source_button, resolve_reference, PdfViewError
from edicola.rag_context import source_editions


def document_label(context, filename, page):
    from edicola.archive_ui import edition_metadata
    info = edition_metadata(context.root, context.documents).get(filename, {}) if context else {}
    return (info.get("title") or "Documento dell’archivio") + f" · pagina {page}"


def citation_text(text, source_ids):
    """Numeri di citazione per il lettore, senza cambiare riferimenti persistenti."""
    numbers = {identity: str(index) for index, identity in enumerate(dict.fromkeys(source_ids), 1)}
    return re.sub(r"\[(S\d+)\]", lambda match: "[" + numbers[match[1]] + "]" if match[1] in numbers else "", text)


def render_contributions(sources, used_source_ids, root, *, editions=None):
    """Distingue documenti inviati e citati, senza attribuire letture al corpus intero."""
    if not sources:
        return
    metadata = editions if editions is not None else source_editions(root, sources)
    groups = OrderedDict()
    for source in sources:
        groups.setdefault(source.filename, []).append(source)
    with st.expander("Edizioni incluse nella lettura"):
        for index, members in enumerate(groups.values(), 1):
            info = metadata.get(members[0].id, {})
            title = info.get("publication") or f"Edizione {index}"
            published = info.get("publication_date") or "Data non disponibile"
            cited = any(source.id in used_source_ids for source in members)
            st.text(title + " · " + published + (" · Citata" if cited else " · Inclusa, non citata"))
        st.caption("Sono elencate solo le edizioni presenti nei passaggi di questa lettura.")


def render_context_limit(coverage):
    if coverage.get("context_selection", {}).get("omitted_passages", 0):
        st.caption("Questa lettura è una selezione: puoi approfondire nelle edizioni originali.")


def render_sources(result, *, index, last, root, context, formatter, namespace="rag"):
    editions = getattr(result, "source_editions", {}) or source_editions(root, result.sources)
    render_contributions(result.sources, result.used_source_ids, root, editions=editions)
    references = getattr(result, "source_references", {})
    groups = OrderedDict()
    for source in result.sources:
        if source.id in result.used_source_ids:
            sha = references.get(source.id, {}).get("pdf_sha256")
            groups.setdefault((source.filename, source.page, sha), []).append(source)
    if groups:
        st.caption("Fonti")
        with st.container(horizontal=True, gap="small"):
            for (filename, page, sha), sources in groups.items():
                source = sources[0]
                if context:
                    for candidate in sources:
                        try:
                            resolve_reference(context, filename, page, candidate.chunk_id, pdf_sha256=sha)
                            source = candidate
                            break
                        except PdfViewError:
                            pass
                info = editions.get(source.id, {})
                name = info.get("publication")
                numbers = {identity: str(i) for i, identity in enumerate(dict.fromkeys(result.used_source_ids), 1)}
                ids = "/".join(numbers[s.id] for s in sources)
                published = info.get("publication_date") or "Data non disponibile"
                label = f"{ids} · {name or 'Documento dell’archivio'} · {published} · pagina {page}"
                description = name or "Documento dell’archivio"
                if info.get("publication_date"):
                    description += " · " + info["publication_date"]
                key = f"{namespace}_pdf_{source.id}" if last else f"{namespace}_history_{index}_{source.id}"
                source_button(filename, page, context=context, chunk_id=source.chunk_id, pdf_sha256=sha,
                              key=key, label=formatter(label), help_text=description)
    if result.sources:
        with st.popover("Mostra passaggi originali", type="tertiary"):
            for source in result.sources:
                if source.id not in result.used_source_ids:
                    continue
                name = editions.get(source.id, {}).get("publication") or "Documento dell’archivio"
                number = list(dict.fromkeys(result.used_source_ids)).index(source.id) + 1
                published = editions.get(source.id, {}).get("publication_date") or "Data non disponibile"
                st.caption(formatter(f"[{number}] {name} · {published} · pagina {source.page}"))
                st.text(source.text)
