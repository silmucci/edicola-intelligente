"""Testata e ricerca locale: nessun embedding, nessuna richiesta Gemini."""

import re
import streamlit as st
from edicola import identity
from edicola.design_tokens import page_css
from edicola.product_navigation import PRODUCTS, open_product, destination, cancel_navigation_action
from edicola.archive_ui import edition_metadata
from edicola.pdf_viewer import source_button

LOGO = '<svg viewBox="0 0 48 48" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 8h15l4 4 4-4h15v31H28l-4 3-4-3H5zM24 12v30M10 15h8M10 21h8M10 27h8M10 33h8M30 15h8M30 21h8M30 27h8M30 33h8"/></svg>'


def local_matches(query, documents, metadata, chunks=()):
    terms = re.findall(r"\w+", query.casefold())
    if not terms:
        return [], [], []
    def matches(text):
        words = re.findall(r"\w+", text.casefold())
        return all(any(word.startswith(term) for word in words) for term in terms)
    products = [i for i, p in enumerate(PRODUCTS) if matches(p["title"] + " " + p["description"])]
    editions = [d for d in documents if matches(metadata[d.filename]["title"] + " " + metadata[d.filename]["date"])]
    passages = [c for c in chunks if matches(c.text)][:5]
    return products[:5], editions[:5], passages


def _profile():
    cancel_navigation_action()
    st.session_state["nav_section"] = destination("profile")
    st.session_state["personal_area"] = "Preferenze"


def render_header(root, context):
    identity.synchronize_identity()
    with st.container(horizontal=True, vertical_alignment="center", gap="large"):
        with st.container(width=490):
            st.html(f'<style>{page_css()}</style><header class="edi-brand">{LOGO}<div>'
                    '<h1>Edicola Digitale <strong>Intelligente</strong></h1>'
                    '<p>Quotidiani, analisi e fonti per capire il mondo.</p></div></header>')
        with st.container(width=350):
            query = st.text_input("Cerca nell'Edicola", max_chars=120, key="account_header_search",
                                  placeholder="Cerca un argomento o una testata...", label_visibility="collapsed")
            if query.strip():
                with st.popover("Risultati della ricerca", icon=":material/search:", width="stretch"):
                    st.caption("Ricerca testuale locale, senza chiamate AI o verifica web.")
                    render_search_results(root, context, query)
        with st.container(horizontal=True, width="content", vertical_alignment="center"):
            person = identity.current_identity() if not identity.local_demo() else None
            name = st.user.get("name", "") if person else ""
            initials = "".join(part[0] for part in name.split()[:2]).upper() if isinstance(name, str) else ""
            st.button((initials + " · " if initials else "") + "Il mio profilo", key="header_profile", on_click=_profile,
                      icon=":material/person:")
            if identity.local_demo():
                st.caption("Sviluppo locale · profilo demo condiviso")
            else:
                identity.login_controls(key="header_auth")


def render_search_results(root, context, query):
    metadata = edition_metadata(root, context.documents)
    try:
        from edicola.editorial_selection import read_catalog
        chunks = read_catalog(root).chunks
    except Exception:
        chunks = []
        st.caption("Testi indicizzati momentaneamente non disponibili; puoi cercare funzioni ed edizioni.")
    products, editions, passages = local_matches(query, context.documents, metadata, chunks)
    for index in products:
        st.button(PRODUCTS[index]["title"], key=f"header_product_{index}", on_click=open_product, args=(index,))
    for index, document in enumerate(editions):
        source_button(document.filename, 1, context=context, key=f"header_edition_{index}",
                      label=metadata[document.filename]["title"] + " · prima pagina")
    for index, chunk in enumerate(passages):
        title = metadata.get(chunk.metadata["filename"], {}).get("title", "Documento dell’archivio")
        # Mostra solo testo, senza eseguire Markdown o markup dei PDF.
        st.text(chunk.text[:160] + ("…" if len(chunk.text) > 160 else ""))
        source_button(chunk.metadata["filename"], chunk.metadata["page"], context=context, chunk_id=chunk.id,
                      key=f"header_passage_{index}", label=title + f" · p. {chunk.metadata['page']}")
    if not (products or editions or passages):
        st.info("Nessuna corrispondenza locale. Prova un altro termine.")
