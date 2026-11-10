"""Destinazioni reali delle card; nessuna generazione associata alla navigazione."""

import streamlit as st

PRODUCTS = [
    dict(id="archive", title="In edicola", description="Sfoglia i quotidiani e scopri le edizioni disponibili.", icon="archive"),
    dict(id="home", title="Rassegna stampa", description="Esplora le notizie dei quotidiani.", icon="paper"),
    dict(id="for_you", title="Per te", description="Letture selezionate in base ai tuoi interessi.", icon="person"),
    dict(id="chat", title="Chat AI", description="Fai domande e approfondisci le notizie.", icon="chat"),
    dict(id="briefing", title="Briefing", description="Leggi una sintesi organizzata per argomento.", kind="Briefing", icon="list"),
    dict(id="timeline", title="Timeline", description="Segui l'evoluzione degli eventi.", kind="Timeline", icon="clock"),
    dict(id="map", title="Mappe concettuali", description="Scopri collegamenti tra persone e argomenti.", kind="Mappa", icon="map"),
    dict(id="podcast", title="Podcast", description="Ascolta le notizie.", icon="audio"),
    dict(id="profile", title="Il mio profilo", description="Preferenze di lettura e privacy.", icon="person"),
]
# Alias derivato per i componenti esistenti: il nome ha un'unica definizione.
for product in PRODUCTS:
    product["section"] = product["title"]
SECTIONS = [product["title"] for product in PRODUCTS]
EDITORIAL_SECTIONS = [product["title"] for product in PRODUCTS if product["id"] != "profile"]
LEGACY_SECTIONS = {"Archivio PDF": "In edicola", "Dossier": "Briefing"}


def canonical_section(section):
    return LEGACY_SECTIONS.get(section, section)


def destination(identifier):
    return next(p["section"] for p in PRODUCTS if p["id"] == identifier or p["title"] == canonical_section(identifier))


def active_product(section):
    return next(p for p in PRODUCTS if p["title"] == canonical_section(section))


# Interrompe il cleanup dei soli input persistenti delle viste non montate.
# Mai pulsanti, consensi, conferme di cancellazione o richieste di generazione.
VIEW_INPUTS = ("editorial_press_draft", "editorial_saved_product", "editorial_review_keyword", "editorial_review_files", "editorial_review_scope",
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
    st.session_state["nav_section"] = canonical_section(st.session_state.get("nav_section"))
    if st.session_state.get("nav_section") not in SECTIONS:
        st.session_state["nav_section"] = SECTIONS[0]
    # Import locale: il componente riusa PRODUCTS e open_product di questo modulo.
    # Unico montaggio sotto l'intestazione, anche fuori dalla Rassegna.
    from edicola.editorial_components import render_products
    render_products()
    return st.session_state["nav_section"]


def select_editorial_section():
    selected = st.session_state.get("_editorial_navigation")
    if selected in EDITORIAL_SECTIONS:
        cancel_navigation_action()
        st.session_state["nav_section"] = selected


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
    index = next((i for i, p in enumerate(PRODUCTS) if p["id"] == identifier), None)
    return open_product(index) if index is not None else False
