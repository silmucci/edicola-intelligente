"""Consultazione della rassegna senza invii esterni."""

import streamlit as st
from collections import Counter, defaultdict

from edicola.press_review import ReviewSelection, filter_catalog, ranked_chunks, article_groups
from edicola.editorial_selection import read_catalog
from edicola.for_you import article_preview
from edicola.consent_ui import cancel_pending



def _readable_groups(groups, metadata, query):
    """Rassegna generale: edizioni recenti alternate, non blocchi per PDF.

    Una ricerca esplicita conserva l'ordinamento per pertinenza già calcolato.
    Si usano esclusivamente le date curate, non quelle ricavate dai nomi file.
    """
    if query.strip():
        return groups
    by_edition = defaultdict(list)
    for members in groups:
        by_edition[members[0].metadata["filename"]].append(members)
    filenames = sorted(by_edition, key=lambda name: (
        metadata.get(name, {}).get("date") or "", name), reverse=True)
    ordered = []
    while any(by_edition.values()):
        for filename in filenames:
            if by_edition[filename]:
                ordered.append(by_edition[filename].pop(0))
    return ordered


def render_press_review(catalog, context, metadata):
    """Un invio locale esplicito, nessuna API durante digitazione o navigazione."""
    from edicola.experience_ui import readable
    from edicola.pdf_viewer import source_button
    # I filtri del Briefing restano intatti quando si consultano tutte le notizie.
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
    groups = _readable_groups(article_groups(ranked), metadata, query)
    if not groups:
        st.info("Non ci sono notizie corrispondenti. Prova un altro argomento.")
        return
    limit = len(groups) if st.session_state.get("editorial_press_more") else 12
    for index, members in enumerate(groups[:limit]):
        # Stesso criterio di Per te: non inventare titoli e non iniziare
        # un'anteprima a metà parola quando il chunk è una continuazione.
        candidates = [item for member in members
                      if (item := article_preview(member)) is not None]
        display = next((item for item in candidates if item.verified_title),
                       candidates[0] if candidates else None)
        chunk = display.chunk if display else members[0]
        info = metadata.get(chunk.metadata["filename"], {})
        with st.container(border=True):
            st.caption((info.get("title") or "Documento dell’archivio") + " · "
                       + (info.get("date") or "Data non disponibile")
                       + " · pagina " + str(chunk.metadata["page"])
                       + (" · Estratto originale" if display and not display.verified_title else ""))
            st.markdown("#### " + readable(display.title if display else "Dall'edizione originale"))
            if display and display.preview:
                st.markdown(readable(display.preview))
            elif not display:
                st.caption("Leggi il passaggio completo direttamente nella fonte originale.")
            source_button(chunk.metadata["filename"], chunk.metadata["page"], context=context, chunk_id=chunk.id,
                          key=f"press_article_{index}", label="Leggi nel PDF")
            with st.popover("Testo originale", key=f"press_original_{index}"):
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
    keyword = st.text_input("Tema o parole chiave", key="editorial_review_keyword", max_chars=500,
                            on_change=cancel_pending)
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
        format_func=labels.__getitem__, on_change=cancel_pending)
    scopes = sorted({item.get("scope") for item in files.values()} & {"nazionale", "internazionale"})
    options = [""] + scopes
    if st.session_state.get("editorial_review_scope", "") not in options:
        st.session_state["editorial_review_scope"] = ""
    scope = st.selectbox("Ambito delle edizioni", options, key="editorial_review_scope",
                         format_func=lambda value: value.capitalize() if value else "Tutti gli ambiti",
                         on_change=cancel_pending)
    # Vecchie bozze non devono mantenere filtri che non sono più visibili.
    for key in ("editorial_review_from", "editorial_review_to"):
        st.session_state.pop(key, None)
    latest = st.selectbox("Copertura delle edizioni", [False, True], key="editorial_review_latest",
                          format_func=lambda value: "Solo le più recenti della selezione" if value else "Tutte le edizioni selezionate",
                          on_change=cancel_pending)
    selection = ReviewSelection(keyword=keyword.strip(), filenames=tuple(sorted(selected)), scope=scope, latest=latest)
    filtered = filter_catalog(catalog, selection)
    return filtered, selection
