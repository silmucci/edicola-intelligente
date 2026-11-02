"""Podcast solo da prodotti già salvati e dopo invio autorizzato."""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from edicola.podcast import VOICES, MODEL, generate_podcast
from edicola.podcast_text import PodcastError, list_products, prepare_script
from edicola.pdf_viewer import source_button
from edicola.archive_ui import diagnostics_enabled
from edicola.consent_ui import authorize_action
from edicola.consent import perform
from edicola.api_guard import PermissionDenied
from edicola.personal_store import PersonalStoreError
from edicola.design import friendly_error, section_intro, reading_title
from edicola.chat_sources import citation_text, document_label, render_contributions


def render_podcast_ui(root: Path, archive=None):
    section_intro("Podcast", "Le notizie da ascoltare, in italiano. Un audio breve dalle letture già disponibili.", "La biblioteca audio")
    try:
        products = list_products(root)
    except PodcastError as exc:
        st.info("Questa lettura non è disponibile per l’ascolto in questo momento.")
        return
    if not products:
        st.info("La tua biblioteca audio è ancora vuota. Prepara un briefing, poi trasformalo in un ascolto.")
        return
    topic = st.text_input("Cerca un episodio per argomento", key="podcast_topic", max_chars=500)
    if topic.strip():
        terms = topic.casefold().split()
        products = [p for p in products if all(term in (p.result.title + " " + " ".join(
            section["text"] for section in p.result.sections)).casefold() for term in terms)]
    if not products:
        st.info("Non ci sono letture disponibili su questo tema. Prepara un briefing e torna qui per ascoltarlo.")
        return
    load_dotenv(root / ".env", override=False)
    available = {p.key: p for p in products}
    if st.session_state.get("podcast_product") not in available:
        st.session_state.pop("podcast_product", None)
    selected = st.selectbox("Lettura da ascoltare", list(available), key="podcast_product",
        format_func=lambda key: citation_text(reading_title(available[key].result), available[key].result.used_source_ids) + " · " + available[key].created_at)
    product = available[selected]
    from edicola.corpus_cache import render_history_notice
    render_history_notice(product.result.coverage, archive)
    try:
        script = prepare_script(product)
    except PodcastError as exc:
        st.info("Questa lettura non è disponibile per l’ascolto in questo momento.")
        return
    default = os.getenv("GEMINI_TTS_VOICE", "Kore").strip()
    if default not in VOICES:
        st.info("Scegli una voce per il tuo ascolto.")
    with st.expander("Voce e opzioni di ascolto"):
        voice = st.selectbox("Voce del podcast", VOICES, index=VOICES.index(default) if default in VOICES else 0, key="podcast_voice")
    st.caption(f"Durata stimata: {len(script.text.split()) / 130:.1f} minuti.")
    if script.excerpt:
        st.info("Questo ascolto riprende alcune sezioni della lettura. Il testo completo resta consultabile.")
    if script.coverage.get("partial"):
        st.warning("Copertura parziale: il podcast riprende solo i contenuti della lettura scelta.")
    from types import SimpleNamespace
    render_contributions([SimpleNamespace(**source) for source in script.sources],
                         [source["id"] for source in script.sources], root)
    with st.expander("Testo da leggere e fonti"):
        st.caption("Il testo letto riprende la lettura scelta. Le fonti sono disponibili qui sotto.")
        st.text(script.text)
        for source in script.sources:
            st.text(document_label(archive, source["filename"], source["page"]))
            if diagnostics_enabled(root):
                st.caption(f"Chunk originale: {source['chunk_id']}")
            source_button(source["filename"], source["page"], context=archive, chunk_id=source["chunk_id"], key=f"podcast_pdf_{source['id']}")
    from edicola.personalization_ui import cached_audio
    existing = cached_audio(root, selected, voice, script=script)
    st.caption("Pronto da ascoltare" if existing else "Da creare · circa 1–2 minuti di ascolto")
    submitted = st.button("Genera podcast", type="primary", key="podcast_submit", disabled=existing is not None)
    signature = (selected, voice, script.text, os.getenv("GEMINI_TTS_MODEL", MODEL).strip() or MODEL)
    if authorize_action("audio", "podcast", submitted, signature):
        st.session_state.pop("podcast_result", None)
        st.session_state.pop("podcast_result_selection", None)
        try:
            with st.spinner("Preparo il tuo ascolto…"):
                st.session_state["podcast_result"] = perform("audio", generate_podcast, selected, voice=voice, authorize_external=True, root=root)
                st.session_state["podcast_result_selection"] = signature
        except (PodcastError, PermissionDenied, PersonalStoreError) as exc:
            st.error(friendly_error(exc))
    if existing:
        data, manifest = existing
        st.caption(f"Audio già disponibile · voce {manifest['voice']}")
        st.audio(data, format="audio/wav")
        st.download_button("Scarica WAV", data, file_name="podcast-edicola.wav", mime="audio/wav", key="podcast_download", on_click="ignore")
    elif st.session_state.get("podcast_result_selection") == signature:
        result = st.session_state["podcast_result"]
        st.caption(f"Audio {'già disponibile' if result.from_cache else 'pronto'} · {result.seconds:.1f} secondi · voce {result.voice}")
        try:
            data = result.audio_path.read_bytes()
        except OSError:
            st.error("Questo audio non è disponibile in questo momento. Puoi provare a generarlo di nuovo.")
            return
        st.audio(data, format="audio/wav")
        st.download_button("Scarica WAV", data, file_name="podcast-edicola.wav",
                           mime="audio/wav", key="podcast_download", on_click="ignore")
