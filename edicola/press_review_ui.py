"""Consultazione della rassegna senza invii esterni."""

import streamlit as st

from edicola.press_review import ReviewSelection, filter_catalog, review_groups
from edicola.editorial_selection import read_catalog


def review_controls(root, catalog=None):
    try:
        catalog = catalog if catalog is not None else read_catalog(root)
    except Exception:
        st.info("La selezione della rassegna sarà disponibile quando l’archivio indicizzato sarà leggibile.")
        return None, ReviewSelection()
    keyword = st.text_input("Parole chiave della rassegna", key="editorial_review_keyword", max_chars=500)
    names = {chunk.metadata["filename"] for chunk in catalog.chunks}
    files = {item["pdf"]: item for item in catalog.coverage["files"] if item["pdf"] in names}
    # Una selezione obsoleta non deve causare errori dei widget.
    if "editorial_review_files" in st.session_state:
        st.session_state["editorial_review_files"] = [f for f in st.session_state["editorial_review_files"] if f in files]
    selected = st.multiselect("Fonti / edizioni", list(files), key="editorial_review_files",
        format_func=lambda name: " · ".join(filter(None, [files[name].get("publication") or "Edizione senza testata", files[name].get("date"), name])))
    scopes = sorted({item.get("scope") for item in files.values()} & {"nazionale", "internazionale"})
    options = [""] + scopes
    if st.session_state.get("editorial_review_scope", "") not in options:
        st.session_state["editorial_review_scope"] = ""
    scope = st.selectbox("Ambito verificato dell’edizione", options, key="editorial_review_scope",
                         format_func=lambda value: value.capitalize() if value else "Tutti gli ambiti")
    st.caption("L’ambito descrive l’edizione, non i singoli articoli. È disponibile solo se curato nei metadati; le edizioni prive di ambito non sono classificate.")
    dates = [""] + sorted({item.get("date") for item in files.values() if item.get("date")})
    for key in ("editorial_review_from", "editorial_review_to"):
        if st.session_state.get(key, "") not in dates:
            st.session_state[key] = ""
    start = st.selectbox("Edizioni dal", dates, key="editorial_review_from", format_func=lambda value: value or "Senza limite iniziale")
    end = st.selectbox("Edizioni fino al", dates, key="editorial_review_to", format_func=lambda value: value or "Senza limite finale")
    latest = st.selectbox("Copertura delle edizioni", [False, True], key="editorial_review_latest",
                          format_func=lambda value: "Solo l’ultima data disponibile nella selezione" if value else "Tutto l’intervallo selezionato")
    st.caption("Le date sono quelle curate delle edizioni, non le date degli eventi. Senza filtri si consulta l’intero archivio indicizzato.")
    if start and end and start > end:
        st.warning("La data iniziale è successiva a quella finale: nessun passaggio selezionato.")
    selection = ReviewSelection(keyword.strip(), tuple(sorted(selected)), scope, start, end, latest)
    filtered = filter_catalog(catalog, selection)
    st.caption(f"Selezione locale: {len(filtered.chunks)} passaggi da {filtered.coverage['selection']['editions']} edizioni. Le parole chiave devono essere tutte presenti nel passaggio.")
    return filtered, selection


def render_review_passages(catalog, context, metadata):
    from edicola.experience_ui import home_selection, passage_card
    if not catalog.chunks:
        st.info("Nessun passaggio indicizzato corrisponde ai filtri. Modifica la selezione.")
        return
    grouping = all(chunk.id in catalog.vectors for chunk in catalog.chunks)
    st.caption("Gruppi per affinità tematica dei passaggi indicizzati: ausilio di consultazione, senza titoli di articolo o classificazioni editoriali inventati." if grouping else "Passaggi disponibili; raggruppamento tematico non disponibile.")
    groups = review_groups(catalog) if grouping else [catalog.chunks]
    options = list(range(len(groups)))
    if st.session_state.get("editorial_review_group", 0) not in options:
        st.session_state["editorial_review_group"] = 0
    index = st.selectbox("Esplora i gruppi della selezione", options, key="editorial_review_group",
                         format_func=lambda i: f"Gruppo {i + 1} · {len(groups[i])} passaggi · Estratto: {groups[i][0].text[:80]}")
    members = groups[index]
    # Il campione visibile è dichiarato, il resto resta consultabile.
    limits = sorted({min(4, len(members)), min(12, len(members)), len(members)})
    if st.session_state.get("editorial_review_limit") not in limits:
        st.session_state["editorial_review_limit"] = limits[0]
    limit = st.selectbox("Passaggi da mostrare", limits, key="editorial_review_limit")
    subset = type(catalog)(members, catalog.vectors, catalog.coverage)
    with st.container(horizontal=True):
        for position, chunk in enumerate(home_selection(subset, limit=limit)):
            passage_card(chunk, context=context, editions=metadata, key=f"review_{index}_{position}")
