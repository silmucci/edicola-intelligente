"""Destinazioni reali delle card; nessuna generazione associata alla navigazione."""

import streamlit as st

PRODUCTS = [
    dict(title="Rassegna stampa", description="Le edizioni e le letture dell’archivio.", section="Home", icon="paper"),
    dict(title="Chat AI", description="Fai una domanda, ritrova le fonti.", section="Chat AI", icon="chat"),
    dict(title="Dossier", description="Approfondisci un argomento tra le fonti.", section="Approfondimenti", kind="Dossier", icon="document"),
    dict(title="Timeline", description="Gli eventi e le date documentate.", section="Timeline e Mappe", kind="Timeline", icon="clock"),
    dict(title="Mappe concettuali", description="Esplora i collegamenti verificati.", section="Timeline e Mappe", kind="Mappa", icon="map"),
    dict(title="Podcast", description="Ascolta briefing e dossier disponibili.", section="Podcast", icon="audio"),
    dict(title="Il mio profilo", description="Interessi, letture e privacy.", section="Personalizzazione", icon="person"),
    dict(title="Archivio PDF", description="Sfoglia i quotidiani originali.", section="Archivio", icon="archive"),
    dict(title="Briefing", description="Una sintesi delle notizie disponibili.", section="Approfondimenti", kind="Briefing", icon="list"),
]


def open_product(index):
    if type(index) is not int or not 0 <= index < len(PRODUCTS):
        return False
    product = PRODUCTS[index]
    st.session_state["nav_section"] = product["section"]
    if product["section"] == "Approfondimenti":
        st.session_state["editorial_kind"] = product["kind"]
    elif product["section"] == "Timeline e Mappe":
        st.session_state["knowledge_kind"] = product["kind"]
    return True
