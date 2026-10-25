"""Destinazioni reali delle card; nessuna generazione associata alla navigazione."""

import streamlit as st

PRODUCTS = [
    dict(id="home", title="Rassegna stampa", description="Le edizioni e le letture dell’archivio.", icon="paper"),
    dict(id="archive", title="Archivio PDF", description="Sfoglia i quotidiani originali.", icon="archive"),
    dict(id="chat", title="Chat AI", description="Fai una domanda, ritrova le fonti.", icon="chat"),
    dict(id="briefing", title="Briefing", description="Una sintesi delle notizie disponibili.", kind="Briefing", icon="list"),
    dict(id="dossier", title="Dossier", description="Approfondisci un argomento tra le fonti.", kind="Dossier", icon="document"),
    dict(id="timeline", title="Timeline", description="Gli eventi e le date documentate.", kind="Timeline", icon="clock"),
    dict(id="map", title="Mappe concettuali", description="Esplora i collegamenti verificati.", kind="Mappa", icon="map"),
    dict(id="podcast", title="Podcast", description="Ascolta briefing e dossier disponibili.", icon="audio"),
    dict(id="profile", title="Il mio profilo", description="Interessi, letture e privacy.", icon="person"),
]
# Alias derivato per i componenti esistenti: il nome ha un'unica definizione.
for product in PRODUCTS:
    product["section"] = product["title"]
SECTIONS = [product["title"] for product in PRODUCTS]


def destination(identifier):
    return next(p["section"] for p in PRODUCTS if p.get("id", p["section"]) == identifier)


def active_product(section):
    return next(p for p in PRODUCTS if p["title"] == section)


# Interrompe il cleanup dei soli input persistenti delle viste non montate.
# Mai pulsanti, consensi, conferme di cancellazione o richieste di generazione.
VIEW_INPUTS = ("editorial_topic", "knowledge_topic_timeline", "knowledge_topic_map", "knowledge_map_view",
               "home_edition_date", "archive_edition_date", "podcast_product", "podcast_voice",
               "personal_area", "personal_interests", "personal_minutes", "personal_format",
               "personal_feedback_topic", "personal_opinion", "personal_product", "personal_voice")


def render_navigation():
    for key in VIEW_INPUTS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    if st.session_state.get("nav_section") not in SECTIONS:
        st.session_state["nav_section"] = SECTIONS[0]
    # Pills native: testo leggibile e wrapping, senza nove tab compresse.
    return st.pills("Sezioni dell’Edicola", SECTIONS, key="nav_section",
                    selection_mode="single", label_visibility="collapsed", on_change=cancel_navigation_action) or SECTIONS[0]


def cancel_navigation_action():
    """Una navigazione non riprende un vecchio invio in attesa di consenso."""
    st.session_state.pop("consent_pending", None)
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
