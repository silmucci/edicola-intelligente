"""Podcast autonomi su invio esplicito; gli episodi storici restano ascoltabili."""
import os
from datetime import datetime, timezone
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

from edicola import consent
from edicola.api_guard import PermissionDenied
from edicola.consent_ui import authorize_action
from edicola.design import friendly_error, section_intro
from edicola.personal_store import PersonalStoreError
from edicola.account_recovery import offer_guest_access
from edicola.podcast import VOICES
from edicola.podcast_text import PodcastError
from edicola.standalone_podcast import generate_standalone_podcast, list_episodes, PodcastAudioError
from edicola.chat_sources import document_label
from edicola.article_evidence import article_reference
from edicola.pdf_viewer import source_button


def prepared_label(value):
    try:
        prepared = datetime.fromisoformat(value)
        if prepared.tzinfo is not None:
            return prepared.astimezone(timezone.utc).strftime("%d/%m/%Y, %H:%M UTC")
        return prepared.strftime("%d/%m/%Y, %H:%M")
    except (ValueError, TypeError):
        return "Data non disponibile"


def authorize_episode(action, submitted, payload):
    """Continua lo stesso invio attraverso i due consensi, consumati una volta."""
    pending = st.session_state.get("consent_pending", {})
    if not submitted and pending.get("action") != action:
        return False
    purpose = pending.get("purpose", "text") if not submitted else "text"
    if purpose not in {"text", "audio"}:
        return False
    if not authorize_action(purpose, action, submitted, payload):
        return False
    other = "audio" if purpose == "text" else "text"
    try:
        if consent.allowed(other):
            return True
    except PersonalStoreError:
        st.error("Le autorizzazioni dell'account non sono disponibili. Nessun contenuto è stato inviato.")
        offer_guest_access(key="podcast_guest_recovery")
        return False
    return authorize_action(other, action, True, payload)


def run_episode(root, voice, *, retry_key=None, topic=""):
    owner = consent.actor()
    try:
        with st.spinner("Preparo l’audio…" if retry_key else "Preparo il podcast dalle notizie disponibili…"):
            episode = generate_standalone_podcast(root=root, voice=voice, authorize_text=True, authorize_audio=True,
                text_check=lambda: consent.actor() == owner and consent.allowed("text"),
                audio_check=lambda: consent.actor() == owner and consent.allowed("audio"), retry_key=retry_key, topic=topic)
        st.session_state["podcast_episode"] = episode
        st.session_state["podcast_episode_choice"] = episode.key
        st.session_state.pop("podcast_failed_draft", None)
    except PodcastAudioError as exc:
        st.session_state["podcast_failed_draft"] = exc.draft
        st.error("Il copione è pronto, ma l’episodio non è stato completato. Puoi riprovare soltanto l’audio.")
    except PodcastError as exc:
        if "fonti" in str(exc).lower() or "affidabile" in str(exc).lower():
            st.info("Le fonti disponibili non sono sufficienti per preparare un episodio affidabile.")
        else:
            st.error(friendly_error(exc))
    except (PermissionDenied, PersonalStoreError) as exc:
        st.error(friendly_error(exc))


def render_podcast_ui(root: Path, archive=None):
    section_intro("Podcast", "Ascolta le notizie che ti interessano.")
    topic = st.text_input("Di cosa vuoi ascoltare le notizie?", key="podcast_topic", max_chars=500,
        placeholder="Es. sanità abruzzese, economia, tribunali, caro carburante...",
        help="Facoltativo: lascia vuoto per ascoltare una selezione generale delle notizie.")
    load_dotenv(root / ".env", override=False)
    default = os.getenv("GEMINI_TTS_VOICE", "Kore").strip()
    with st.popover("Voce", icon=":material/record_voice_over:"):
        voice = st.selectbox("Voce del podcast", VOICES, index=VOICES.index(default) if default in VOICES else 0, key="podcast_voice")
    submitted = st.button("Genera podcast", key="podcast_submit", type="primary")
    if authorize_episode("podcast_generate", submitted, {"voice": voice, "topic": topic}):
        run_episode(root, voice, topic=topic)
    draft = st.session_state.get("podcast_failed_draft")
    if draft:
        with st.expander("Copione pronto", expanded=True):
            st.text(draft.script.text)
            render_episode_sources(draft.script, draft.sources, root, archive, "podcast_draft",
                                   articles=draft.source_articles)
            retry = st.button("Riprova solo l’audio", key="podcast_retry")
            if authorize_episode("podcast_retry", retry, {"voice": voice, "draft": draft.key}):
                run_episode(root, voice, retry_key=draft.key)
    try:
        episodes = {e.key: e for e in list_episodes(root)}
    except (OSError, PodcastError):
        episodes = {}
        st.info("Gli episodi precedenti non sono disponibili in questo momento.")
    latest = st.session_state.get("podcast_episode")
    if latest:
        episodes[latest.key] = latest
    if not episodes:
        st.info("Genera un episodio per ascoltare le notizie disponibili nell’archivio.")
        return
    if st.session_state.get("podcast_episode_choice") not in episodes:
        st.session_state["podcast_episode_choice"] = next(iter(episodes))
    selected = st.selectbox("Episodi disponibili", list(episodes), key="podcast_episode_choice",
                            format_func=lambda key: episodes[key].title + " · " + prepared_label(episodes[key].created_at) + " · " + episodes[key].voice)
    episode = episodes[selected]
    st.text(episode.title)
    st.caption("Preparato: " + prepared_label(episode.created_at) + f" · {episode.seconds / 60:.1f} minuti · voce {episode.voice}")
    try:
        data = episode.audio_path.read_bytes()
        from edicola.podcast import wav_duration
        wav_duration(data)
        st.audio(data, format="audio/wav")
        st.download_button("Scarica l’audio", data, file_name="edicola-podcast.wav", mime="audio/wav", key="podcast_download")
    except (OSError, PodcastError):
        st.info("Questo audio non è disponibile in questo momento. Gli altri episodi restano consultabili.")
    with st.expander("Testo e fonti"):
        st.text(episode.script.text)
        render_episode_sources(episode.script, episode.sources, root, archive, "podcast_episode",
                               articles=episode.source_articles)


def render_episode_sources(script, sources, root, archive, key, *, articles=None):
    for source in script.sources:
        article = (articles or {}).get(source["id"])
        label = document_label(archive, source["filename"], source["page"])
        if article:
            label += " · " + article_reference(article)
        source_button(source["filename"], source["page"], context=archive, chunk_id=source["chunk_id"],
                      key=key + "_" + source["id"], label=label)
