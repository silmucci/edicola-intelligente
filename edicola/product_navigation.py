"""Destinazioni reali delle card; nessuna generazione associata alla navigazione."""

import streamlit as st

PRODUCTS = [
    dict(id="archive", title="In edicola", description="Sfoglia i quotidiani originali.", icon="archive"),
    dict(id="for_you", title="Per te", description="Notizie consigliate e rassegna completa.", icon="paper"),
    dict(id="chat", title="Chat AI", description="Fai domande e approfondisci le notizie.", icon="chat"),
    dict(id="briefing", title="Briefing", description="Approfondimenti con fonti verificate.", kind="Briefing", icon="list"),
    dict(id="podcast", title="Podcast", description="Ascolta gli approfondimenti.", icon="audio"),
    dict(id="explore", title="Esplora", description="Eventi nel tempo e mappe di concetti.", icon="map"),
    dict(id="profile", title="Il mio profilo", description="Preferenze, raccolta e privacy.", icon="person"),
]
for product in PRODUCTS:
    product["section"] = product["title"]

SECTIONS = [product["title"] for product in PRODUCTS]
EDITORIAL_SECTIONS = [p["section"] for p in PRODUCTS if p["id"] != "profile"]
# Alias mantenuti per bozze, collegamenti e sessioni create prima del restyling.
LEGACY_SECTIONS = {
    "Archivio PDF": "In edicola", "Dossier": "Briefing",
    "Rassegna stampa": "Per te", "Timeline": "Esplora",
    "Mappe concettuali": "Esplora",
}
LEGACY_IDS = {"home": "for_you", "timeline": "explore", "map": "explore"}


def canonical_section(section):
    return LEGACY_SECTIONS.get(section, section)


def destination(identifier):
    """Risolve ID e nomi moderni o storici senza cambiare lo stato."""
    target = LEGACY_IDS.get(identifier, identifier)
    name = canonical_section(target)
    return next(p["section"] for p in PRODUCTS
                if p["id"] == target or p["title"] == name)


def active_product(section):
    return next(p for p in PRODUCTS if p["section"] == canonical_section(section))


def _legacy_mode(section):
    if section == "Rassegna stampa":
        st.session_state["for_you_mode"] = "Tutte le notizie"
    elif section in {"Timeline", "Mappe concettuali"}:
        st.session_state["knowledge_kind"] = "Timeline" if section == "Timeline" else "Mappa"


# Interrompe il cleanup dei soli input persistenti delle viste non montate.
# Mai pulsanti, consensi, conferme di cancellazione o richieste di generazione.
VIEW_INPUTS = ("for_you_mode", "for_you_topic", "knowledge_kind", "knowledge_topic",
               "editorial_press_draft", "editorial_saved_product", "editorial_review_keyword", "editorial_review_files", "editorial_review_scope",
               "editorial_review_latest",
               "editorial_review_group", "editorial_review_limit",
               "podcast_topic", "knowledge_map_focus",
               "knowledge_topic_timeline", "knowledge_topic_map", "knowledge_map_view",
               "home_edition_date", "archive_edition_date", "podcast_product", "podcast_voice", "podcast_episode_choice",
               "personal_area", "personal_interests", "personal_minutes", "personal_format",
               "personal_feedback_topic", "personal_opinion", "personal_product", "personal_voice")


def render_navigation():
    for key in VIEW_INPUTS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    requested = st.session_state.get("nav_section")
    _legacy_mode(requested)
    st.session_state["nav_section"] = canonical_section(requested)
    if st.session_state.get("nav_section") not in SECTIONS:
        st.session_state["nav_section"] = SECTIONS[0]
    # Import locale: il componente riusa PRODUCTS e open_product di questo modulo.
    # Unico montaggio sotto l'intestazione, anche fuori dalla Rassegna.
    from edicola.editorial_components import render_products
    render_products()
    return st.session_state["nav_section"]


def select_editorial_section():
    selected = st.session_state.get("_editorial_navigation")
    if canonical_section(selected) in EDITORIAL_SECTIONS:
        cancel_navigation_action()
        _legacy_mode(selected)
        st.session_state["nav_section"] = canonical_section(selected)


def cancel_navigation_action():
    """Una navigazione non riprende un vecchio invio in attesa di consenso."""
    st.session_state.pop("consent_pending", None)
    st.session_state["nav_section"] = canonical_section(st.session_state.get("nav_section"))
    if st.session_state.get("nav_section") not in SECTIONS:
        st.session_state["nav_section"] = SECTIONS[0]
    pending = st.session_state.get("rag_pending")
    if pending:
        pending["new"] = False


def open_product(index):
    if type(index) is not int or not 0 <= index < len(PRODUCTS):
        return False
    product = PRODUCTS[index]
    cancel_navigation_action()
    st.session_state["nav_section"] = product["section"]
    return True


def open_product_id(identifier):
    """Apre anche gli ID storici, scegliendo la sottovista giusta."""
    target = LEGACY_IDS.get(identifier, identifier)
    index = next((i for i, p in enumerate(PRODUCTS) if p["id"] == target), None)
    if index is None:
        return False
    if identifier == "home":
        st.session_state["for_you_mode"] = "Tutte le notizie"
    elif identifier in {"timeline", "map"}:
        st.session_state["knowledge_kind"] = "Timeline" if identifier == "timeline" else "Mappa"
    return open_product(index)
