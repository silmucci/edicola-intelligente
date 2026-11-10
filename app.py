"""Edicola Digitale Intelligente: archivio originale e prodotti editoriali."""

import logging
import sqlite3
from pathlib import Path

import streamlit as st

# Chroma richiede SQLite recente anche quando non vengono generate risposte.
if sqlite3.sqlite_version_info < (3, 35, 0):
    st.error("L’Edicola non è disponibile in questo momento. Riprova più tardi.")
    st.stop()

from edicola.ingestion import ingest_directory
from edicola.pdf_intake import process_inbox
from edicola.edition_dates import sync_filename_dates
from edicola.vector_reuse import reuse_unchanged_vectors
from edicola.chunking import prepare_documents
from edicola.pdf_viewer import archive_context, render_archive
from edicola.archive_ui import diagnostics_enabled
from edicola.reading_ui import render_chat, render_editorial, render_visuals
from edicola.podcast_ui import render_podcast_ui
from edicola.personalization_ui import render_personalization_ui
from edicola.cloud import prepare_cloud
from edicola.settings import setting
from edicola.experience_ui import render_home
from edicola.identity import synchronize_identity
from edicola.header_ui import render_header
from edicola.product_navigation import render_navigation, active_product

ROOT = Path(__file__).resolve().parent
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("edicola").setLevel(logging.INFO)

st.set_page_config(page_title="Edicola Digitale Intelligente", layout="wide", page_icon="📰")
synchronize_identity()
if setting("EDICOLA_CLOUD_DEMO", "0") == "1":
    try:
        with st.spinner("Apro l’Edicola…"):
            ROOT = prepare_cloud(ROOT)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        st.error("L’archivio non è disponibile in questo momento. Riprova più tardi.")
        st.stop()

# La versione pubblicata usa uno snapshot immutabile: la inbox è solo locale.
# Una copia PDF depositata in data/inbox viene preparata senza Gemini al reload.
intake_report = {"added": []}
if setting("EDICOLA_CLOUD_DEMO", "0") != "1":
    try:
        intake_report = process_inbox(ROOT)
        if intake_report["added"]:
            logging.getLogger("edicola").info(
                "Nuove edizioni locali preparate: %d", len(intake_report["added"]))
    except (OSError, ValueError, RuntimeError):
        logging.getLogger("edicola").warning("Inbox PDF non disponibile; archivio precedente conservato.")

try:
    with st.spinner("Apro le edizioni disponibili…"):
        documents = ingest_directory(ROOT / "data/incoming", ROOT / "data/archive.sqlite3")
        prepared = prepare_documents(documents, ROOT / "data/archive.sqlite3")
except (OSError, RuntimeError):
    st.error("L’archivio non è disponibile in questo momento. Riprova più tardi.")
    st.stop()

# Completa le date dei quotidiani locali usando il nome del PDF.
# Aggiorna anche le edizioni già caricate, senza toccare lo snapshot cloud.
if setting("EDICOLA_CLOUD_DEMO", "0") != "1":
    try:
        updated_dates = sync_filename_dates(ROOT, documents)
        if updated_dates:
            logging.getLogger("edicola").info("Date edizioni aggiunte: %d", len(updated_dates))
    except (OSError, RuntimeError, ValueError):
        logging.getLogger("edicola").warning("Date edizioni non aggiornate; archivio conservato.")

# Stessa pagina, testo e prompt di embedding: riutilizzare il vettore
# precedente, ma solo per edizioni esplicitamente collegate dalla inbox.
if intake_report["added"]:
    try:
        reused = reuse_unchanged_vectors(ROOT)
        if reused:
            logging.getLogger("edicola").info("Embedding riutilizzati localmente: %d", reused)
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        logging.getLogger("edicola").warning("Riuso vettori differito; vecchio indice preservato.")

if diagnostics_enabled(ROOT):
    with st.expander("Dati dell'archivio · sviluppo"):
        left, middle, right = st.columns(3)
        left.metric("Quotidiani acquisiti", sum(d.status in {"ok", "partial", "no_text"} for d in documents))
        middle.metric("PDF disponibili", len(documents))
        right.metric("Pagine complessive", sum(d.total_pages for d in documents))
context = archive_context(ROOT, documents, prepared)
render_header(ROOT, context)
section = render_navigation()
product = active_product(section)
# Si monta solo la destinazione scelta. Risultati RAM e input conservati dalla
# navigazione; i pulsanti di generazione non vengono ripristinati.
if product["id"] == "home":
    render_home(context.root, context)
elif product["id"] == "archive":
    render_archive(context, prepared)
elif product["id"] == "chat":
    with st.container(width=960):
        render_chat(ROOT, context)
elif product["id"] == "briefing":
    with st.container(width=900):
        render_editorial(ROOT, context)
elif product["id"] in {"timeline", "map"}:
    render_visuals(ROOT, context, kind=product["kind"])
elif product["id"] == "podcast":
    with st.container(width=900):
        render_podcast_ui(ROOT, archive=context)
elif product["id"] == "profile":
    render_personalization_ui(ROOT, archive=context)
