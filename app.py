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
from edicola.experience_ui import render_home
from edicola.identity import synchronize_identity
from edicola.header_ui import render_header
from edicola.product_navigation import render_navigation, active_product, cancel_navigation_action

ROOT = Path(__file__).resolve().parent
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("edicola").setLevel(logging.INFO)

st.set_page_config(page_title="Edicola Digitale Intelligente", layout="wide", page_icon="📰")
synchronize_identity()
if setting("EDICOLA_CLOUD_DEMO", "0") == "1":
    with st.expander("Informazioni su questa edicola dimostrativa"):
        st.caption("Archivio pubblico · spazio personale con accesso Google. "
                   "Gli audio e i prodotti generali possono non essere disponibili dopo un riavvio; preferenze e briefing personali restano nel tuo account.")
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
elif product["id"] in {"briefing", "dossier"}:
    with st.container(width=900):
        if product["id"] == "briefing":
            mode = st.segmented_control("Prodotto editoriale", ["Briefing", "Infografica"], default="Briefing", key="editorial_workspace", on_change=cancel_navigation_action) or "Briefing"
            if mode == "Infografica":
                from edicola.infographic_ui import render_infographic
                render_infographic(ROOT, context)
            else:
                render_editorial(ROOT, context, kind="Briefing")
        else:
            render_editorial(ROOT, context, kind=product["kind"])
elif product["id"] in {"timeline", "map"}:
    render_visuals(ROOT, context, kind=product["kind"])
elif product["id"] == "podcast":
    with st.container(width=900):
        render_podcast_ui(ROOT, archive=context)
elif product["id"] == "profile":
    render_personalization_ui(ROOT, archive=context)
