"""Edicola Digitale Intelligente: archivio originale e prodotti editoriali."""

import logging
import sqlite3
from pathlib import Path

import streamlit as st

# Chroma richiede SQLite recente anche quando non vengono generate risposte.
if sqlite3.sqlite_version_info < (3, 35, 0):
    st.error("SQLite >= 3.35 richiesto da ChromaDB. Verificare il runtime Python del deployment.")
    st.stop()

from edicola.ingestion import ingest_directory
from edicola.chunking import prepare_documents
from edicola.pdf_viewer import archive_context, render_archive
from edicola.archive_ui import diagnostics_enabled
from edicola.reading_ui import render_chat, render_editorial, render_visuals
from edicola.podcast_ui import render_podcast_ui
from edicola.personalization_ui import render_personalization_ui
from edicola.cloud import prepare_cloud
from edicola.settings import setting

ROOT = Path(__file__).resolve().parent
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("edicola").setLevel(logging.INFO)

st.set_page_config(page_title="Edicola Digitale Intelligente", layout="wide", page_icon="📰")
st.title("Edicola Digitale Intelligente")
st.caption("I quotidiani originali, le fonti e gli strumenti per approfondire le notizie.")

if setting("EDICOLA_CLOUD_DEMO", "0") == "1":
    st.info("Demo pubblica: nessuna autenticazione. Il profilo è condiviso, non è un account personale. "
            "Non inserire dati personali. Preferenze e nuovi risultati possono andare persi al riavvio.")
    try:
        with st.spinner("Verifica dello snapshot dimostrativo…"):
            ROOT = prepare_cloud(ROOT)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        st.error("Snapshot cloud assente o incompatibile. Il gestore deve verificare DEPLOYMENT.md. "
                 "Nessuna estrazione o indicizzazione avviata.")
        st.stop()

try:
    with st.spinner("Controllo dell'archivio locale…"):
        documents = ingest_directory(ROOT / "data/incoming", ROOT / "data/archive.sqlite3")
        prepared = prepare_documents(documents, ROOT / "data/archive.sqlite3")
except (OSError, RuntimeError):
    st.error("Archivio locale non disponibile. Verifica la cartella dei quotidiani e riprova.")
    st.stop()

if diagnostics_enabled(ROOT):
    with st.expander("Dati dell'archivio · sviluppo"):
        left, middle, right = st.columns(3)
        left.metric("Quotidiani acquisiti", sum(d.status in {"ok", "partial", "no_text"} for d in documents))
        middle.metric("PDF disponibili", len(documents))
        right.metric("Pagine complessive", sum(d.total_pages for d in documents))
context = archive_context(ROOT, documents, prepared)
sections = ["Archivio", "Chat AI", "Approfondimenti", "Timeline e Mappe", "Podcast", "Personalizzazione"]
if st.session_state.get("nav_section") not in sections:
    st.session_state["nav_section"] = "Archivio"
# Tutti i form restano montati: cambiare scheda non cancella input o consensi.
# Nessuna generazione è associata al cambio scheda o all'apertura delle fonti.
tabs = st.tabs(sections, key="nav_section", on_change="rerun")
with tabs[0]:
    render_archive(context, prepared)
with tabs[1]:
    render_chat(ROOT, context)
with tabs[2]:
    render_editorial(ROOT, context)
with tabs[3]:
    render_visuals(ROOT, context)
with tabs[4]:
    st.header("Podcast")
    render_podcast_ui(ROOT, archive=context)
with tabs[5]:
    render_personalization_ui(ROOT, archive=context)
