"""Consultazione della rassegna senza invii esterni."""

import streamlit as st
from collections import Counter

from edicola.press_review import ReviewSelection, filter_catalog, review_groups, ranked_chunks, article_groups
from edicola.editorial_selection import read_catalog


def render_press_review(catalog, context, metadata):
    """Un invio locale esplicito, nessuna API durante digitazione o navigazione."""
    from edicola.experience_ui import excerpt, readable
    from edicola.pdf_viewer import source_button
    for suffix in ("files", "scope", "from", "to", "latest", "group", "limit", "keyword"):
        st.session_state.pop("editorial_review_" + suffix, None)
    with st.form("press_search_form"):
        query = st.text_input("Cerca una notizia o un argomento", key="editorial_press_draft", max_chars=500,
                              placeholder="Es. sanità abruzzese, caro carburante, tribunali...",
                              help="Se hai autorizzato le funzioni AI, all’invio la domanda può essere usata anche per cercare per significato. Altrimenti la ricerca resta locale.")
        submitted = st.form_submit_button("Cerca")
    if submitted:
        st.session_state["editorial_press_query"] = query.strip()
        st.session_state["editorial_press_hits"] = []
        st.session_state.pop("editorial_press_more", None)
        # Solo l'invio corrente può cercare semanticamente. Il consenso non viene
        # richiesto né riattivato da bozza, navigazione, errori o rerun.
        if query.strip():
            from edicola import consent
            from edicola.search import semantic_search
            try:
                if consent.decision("text") is True:
                    st.session_state["editorial_press_hits"] = consent.perform("text", semantic_search, query.strip(),
                        authorize_external=True, root=context.root, corpus_wide=True,
                        allowed_ids={c.id for c in catalog.chunks}, filenames={c.metadata["filename"] for c in catalog.chunks})
            except Exception:
                # Restano disponibili i risultati locali; nessun retry remoto.
                st.info("La ricerca approfondita non è disponibile in questo momento. Qui trovi i risultati disponibili.")
    query = st.session_state.get("editorial_press_query", "")
    ranked = ranked_chunks(catalog.chunks, query, st.session_state.get("editorial_press_hits", []))
    groups = article_groups(ranked)
    if not groups:
        st.info("Non ci sono notizie corrispondenti. Prova un altro argomento.")
        return
    limit = len(groups) if st.session_state.get("editorial_press_more") else 12
    for index, members in enumerate(groups[:limit]):
        chunk = members[0]
        info = metadata.get(chunk.metadata["filename"], {})
        title = chunk.metadata.get("article_title", "")
        trusted_title = chunk.metadata.get("article_title_verified") is True and title and title in chunk.text
        with st.container(border=True):
            st.caption((info.get("title") or "Documento dell’archivio") + " · " + (info.get("date") or "Data non disponibile"))
            st.markdown("**" + readable(title if trusted_title else "Dalle notizie del quotidiano") + "**")
            st.markdown(readable(excerpt(chunk.text, 340)))
            source_button(chunk.metadata["filename"], chunk.metadata["page"], context=context, chunk_id=chunk.id,
                          key=f"press_article_{index}", label="Leggi l’articolo")
            with st.popover("Leggi la fonte", key=f"press_original_{index}"):
                for member in members:
                    st.text(member.text)
                    if member is not chunk:
                        source_button(member.metadata["filename"], member.metadata["page"], context=context, chunk_id=member.id,
                                      key=f"press_article_{index}_{member.id}", label=f"Apri pagina {member.metadata['page']}")
    if limit < len(groups) and st.button("Mostra altre notizie", key="press_more"):
        st.session_state["editorial_press_more"] = True
        st.rerun()


def review_controls(root, catalog=None):
    try:
        catalog = catalog if catalog is not None else read_catalog(root)
    except Exception:
        st.info("La selezione delle fonti non è disponibile in questo momento.")
        return None, ReviewSelection()
    keyword = st.text_input("Tema o parole chiave", key="editorial_review_keyword", max_chars=500)
    names = {chunk.metadata["filename"] for chunk in catalog.chunks}
    files = {item["pdf"]: item for item in catalog.coverage["files"] if item["pdf"] in names}
    labels = {name: " · ".join(filter(None, [item.get("publication") or f"Edizione {index}", item.get("date")]))
              for index, (name, item) in enumerate(files.items(), 1)}
    repeated = Counter(labels.values())
    labels = {name: label + (f" · edizione {index}" if repeated[label] > 1 else "")
              for index, (name, label) in enumerate(labels.items(), 1)}
    # Una selezione obsoleta non deve causare errori dei widget.
    if "editorial_review_files" in st.session_state:
        st.session_state["editorial_review_files"] = [f for f in st.session_state["editorial_review_files"] if f in files]
    selected = st.multiselect("Fonti / edizioni", list(files), key="editorial_review_files",
        format_func=labels.__getitem__)
    scopes = sorted({item.get("scope") for item in files.values()} & {"nazionale", "internazionale"})
    options = [""] + scopes
    if st.session_state.get("editorial_review_scope", "") not in options:
        st.session_state["editorial_review_scope"] = ""
    scope = st.selectbox("Ambito delle edizioni", options, key="editorial_review_scope",
                         format_func=lambda value: value.capitalize() if value else "Tutti gli ambiti")
    st.caption("L’ambito riguarda l’edizione, non i singoli articoli. Alcune edizioni non hanno un ambito indicato.")
    # Vecchie bozze non devono mantenere filtri che non sono più visibili.
    for key in ("editorial_review_from", "editorial_review_to"):
        st.session_state.pop(key, None)
    latest = st.selectbox("Copertura delle edizioni", [False, True], key="editorial_review_latest",
                          format_func=lambda value: "Solo le più recenti della selezione" if value else "Tutte le edizioni selezionate")
    selection = ReviewSelection(keyword=keyword.strip(), filenames=tuple(sorted(selected)), scope=scope, latest=latest)
    filtered = filter_catalog(catalog, selection)
    st.caption("La ricerca include i testi che contengono tutte le parole chiave indicate.")
    return filtered, selection


def render_review_passages(catalog, context, metadata):
    from edicola.experience_ui import home_selection, passage_card
    if not catalog.chunks:
        st.info("Non ci sono letture corrispondenti ai filtri scelti.")
        return
    grouping = all(chunk.id in catalog.vectors for chunk in catalog.chunks)
    st.caption("Estratti raggruppati per affinità di tema; ogni estratto può comprendere più notizie." if grouping else "Esplora gli estratti disponibili.")
    groups = review_groups(catalog) if grouping else [catalog.chunks]
    options = list(range(len(groups)))
    if st.session_state.get("editorial_review_group", 0) not in options:
        st.session_state["editorial_review_group"] = 0
    index = st.selectbox("Esplora per tema", options, key="editorial_review_group",
                         format_func=lambda i: f"Estratto {i + 1}: {groups[i][0].text[:80]}")
    members = groups[index]
    # Il campione visibile è dichiarato, il resto resta consultabile.
    limits = sorted({min(4, len(members)), min(12, len(members)), len(members)})
    if st.session_state.get("editorial_review_limit") not in limits:
        st.session_state["editorial_review_limit"] = limits[0]
    limit = st.selectbox("Letture da mostrare", limits, key="editorial_review_limit",
                         format_func=lambda value: "Tutte le letture" if value == len(members) else
                         "Una selezione" if value == limits[0] else "Più letture")
    if limit < len(members):
        st.caption("Queste schede sono una selezione. Puoi aumentare le letture da mostrare per vedere gli altri contributi.")
    subset = type(catalog)(members, catalog.vectors, catalog.coverage)
    with st.container(horizontal=True):
        for position, chunk in enumerate(home_selection(subset, limit=limit)):
            passage_card(chunk, context=context, editions=metadata, key=f"review_{index}_{position}")
