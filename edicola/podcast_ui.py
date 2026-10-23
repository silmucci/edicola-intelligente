"""Podcast solo da prodotti già salvati e dopo invio autorizzato."""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from edicola.podcast import VOICES, generate_podcast
from edicola.podcast_text import PodcastError, list_products, prepare_script
from edicola.pdf_viewer import source_button
from edicola.archive_ui import diagnostics_enabled


def render_podcast_ui(root: Path, archive=None):
    st.subheader("Podcast editoriali")
    st.caption("Le notizie da ascoltare, in italiano. Crea un audio breve da un briefing o dossier già disponibile, senza cambiare le fonti.")
    try:
        products = list_products(root)
    except PodcastError as exc:
        st.info(str(exc))
        return
    if not products:
        st.info("La tua biblioteca audio è ancora vuota. Crea prima un dossier o un briefing in Approfondimenti, poi trasformalo in un ascolto.")
        return
    load_dotenv(root / ".env", override=False)
    available = {p.key: p for p in products}
    selected = st.selectbox("Briefing o dossier già generato", list(available), key="podcast_product",
        format_func=lambda key: f"{available[key].result.kind.capitalize()} — {available[key].result.title} — {available[key].created_at}")
    product = available[selected]
    try:
        script = prepare_script(product)
    except PodcastError as exc:
        st.info(str(exc))
        return
    default = os.getenv("GEMINI_TTS_VOICE", "Kore").strip()
    if default not in VOICES:
        st.info("La voce configurata non è tra quelle disponibili nel prototipo: selezionare una voce dall'elenco.")
    voice = st.selectbox("Voce del podcast", VOICES, index=VOICES.index(default) if default in VOICES else 0, key="podcast_voice")
    st.caption(f"{len(script.text.split())} parole · durata stimata {len(script.text.split()) / 130:.1f} minuti; la durata effettiva può variare.")
    if script.excerpt:
        st.info(f"Estratto: {script.selected_sections} sezioni complete su {script.total_sections}; nessuna frase è stata tagliata.")
    if script.coverage.get("partial"):
        st.warning("Archivio parzialmente indicizzato: anche il podcast copre soltanto i contenuti del prodotto disponibile.")
    with st.expander("Testo da leggere e fonti"):
        st.text(script.text)
        for source in script.sources:
            st.text(f"[{source['id']}] {source['filename']} — pagina {source['page']}")
            if diagnostics_enabled(root):
                st.caption(f"Chunk originale: {source['chunk_id']}")
            source_button(source["filename"], source["page"], context=archive, chunk_id=source["chunk_id"], key=f"podcast_pdf_{source['id']}")
    with st.form("podcast_generation"):
        authorized = st.checkbox("Autorizzo l'invio a Gemini TTS del copione visualizzato per generare l'audio.", key="podcast_authorized")
        submitted = st.form_submit_button("Genera podcast", type="primary")
    signature = (selected, voice, script.text)
    if submitted:
        st.session_state.pop("podcast_result", None)
        st.session_state.pop("podcast_result_selection", None)
        if not authorized:
            st.warning("Autorizzare l'invio del copione prima della generazione audio.")
        else:
            try:
                with st.spinner("Generazione del podcast o recupero dell'audio dalla cache…"):
                    st.session_state["podcast_result"] = generate_podcast(selected, voice=voice, authorize_external=True, root=root)
                    st.session_state["podcast_result_selection"] = signature
            except PodcastError as exc:
                st.error(str(exc))
    if st.session_state.get("podcast_result_selection") == signature:
        result = st.session_state["podcast_result"]
        st.caption(f"Audio {'già disponibile' if result.from_cache else 'pronto'} · {result.seconds:.1f} secondi · voce {result.voice}")
        try:
            data = result.audio_path.read_bytes()
        except OSError:
            st.error("File audio locale non disponibile; premere Genera podcast per recuperarlo.")
            return
        st.audio(data, format="audio/wav")
        st.download_button("Scarica WAV", data, file_name="podcast-edicola.wav",
                           mime="audio/wav", key="podcast_download", on_click="ignore")
