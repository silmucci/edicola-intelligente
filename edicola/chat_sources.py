"""Citazioni compatte: un collegamento per pagina, dettagli secondari in popover."""

from collections import OrderedDict
import streamlit as st

from edicola.pdf_viewer import source_button, resolve_reference, PdfViewError
from edicola.rag_context import source_editions


def render_sources(result, *, index, last, root, context, formatter, namespace="rag"):
    editions = getattr(result, "source_editions", {}) or source_editions(root, result.sources)
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
                ids = "/".join(s.id for s in sources)
                label = f"{ids} · {name[:48]} · p. {page}" if name else f"{ids} · p. {page}"
                description = name or "Documento dell’archivio"
                if info.get("publication_date"):
                    description += " · " + info["publication_date"]
                key = f"{namespace}_pdf_{source.id}" if last else f"{namespace}_history_{index}_{source.id}"
                source_button(filename, page, context=context, chunk_id=source.chunk_id, pdf_sha256=sha,
                              key=key, label=formatter(label), help_text=description)
    if result.sources:
        with st.popover("Mostra passaggi originali", type="tertiary"):
            for source in result.sources:
                name = editions.get(source.id, {}).get("publication") or "Documento dell’archivio"
                status = "Citata" if source.id in result.used_source_ids else "Recuperata, non citata"
                st.caption(formatter(f"[{source.id}] {name} · p. {source.page} · {status}"))
                st.text(source.text)
