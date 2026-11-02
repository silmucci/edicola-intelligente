"""Consultazione della rassegna senza invii esterni."""

import streamlit as st
from collections import Counter

from edicola.press_review import ReviewSelection, filter_catalog, review_groups
from edicola.editorial_selection import read_catalog


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
