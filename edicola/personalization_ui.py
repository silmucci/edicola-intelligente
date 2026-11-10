"""Interfaccia del profilo demo; generazioni remote soltanto da form autorizzati."""

import hashlib
import json
from dataclasses import asdict
import os

import streamlit as st

from edicola.editorial_selection import read_catalog
from edicola.embeddings import api_key
from edicola.personalization import generate_personal_briefing, recommend
from edicola.podcast import VOICES, MODEL, VERSION, STYLE, generate_podcast, wav_duration
from edicola.podcast_text import PodcastError, list_products
from edicola.profiles import (delete_profile, load_profile, personal_root, remove_passage,
                             save_profile, set_feedback)
from edicola.rag import RagError
from edicola.pdf_viewer import source_button
from edicola.settings import setting
from edicola.archive_ui import edition_metadata
from edicola.experience_ui import INTERESTS, excerpt, passage_card, readable
from edicola.identity import local_demo
from edicola.consent_ui import authorize_action, privacy_controls
from edicola.consent import perform
from edicola.api_guard import PermissionDenied
from edicola.design import friendly_error, product_notice, reading_title
from edicola.chat_sources import citation_text, render_sources, document_label, render_context_limit


def show_product(result, archive=None):
    st.subheader(readable(citation_text(reading_title(result), result.used_source_ids)))
    if result.from_cache:
        st.caption("Lettura già disponibile.")
    render_context_limit(result.coverage)
    if result.message:
        st.info(product_notice(result))
    for section in result.sections:
        with st.container(border=True):
            st.subheader(readable(citation_text(section["heading"], result.used_source_ids)))
            st.markdown(readable(citation_text(section["text"], result.used_source_ids)))
    from pathlib import Path
    from edicola.reading_ui import chat_markdown
    root = archive.root if archive else Path(__file__).resolve().parents[1]
    render_sources(result, index=0, last=True, root=root, context=archive,
                   formatter=chat_markdown, namespace="personal_brief")


def cached_audio(scope, product_key, voice=None, *, script=None):
    """Solo lettura locale dei manifest del modulo TTS esistente, con verifica WAV."""
    directory = scope / "data/podcast_cache"
    for path in sorted(directory.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if item["product_key"] != product_key or (voice is not None and item["voice"] != voice):
                continue
            if script is not None:
                model = os.getenv("GEMINI_TTS_MODEL", MODEL).strip() or MODEL
                identity = hashlib.sha256(json.dumps([VERSION, script.text, model, item["voice"], STYLE], ensure_ascii=False).encode()).hexdigest()
                if (item.get("script") != asdict(script) or item.get("model") != model
                        or item.get("version") != VERSION or item.get("audio_file") != identity + ".wav"):
                    continue
            filename = item["audio_file"]
            audio = directory / filename
            if audio.resolve().parent != directory.resolve() or audio.suffix != ".wav":
                continue
            data = audio.read_bytes()
            wav_duration(data)
            if hashlib.sha256(data).hexdigest() == item["audio_sha256"]:
                return data, item
        except (OSError, ValueError, KeyError, TypeError, PodcastError):
            continue
    return None


def render_personalization_ui(root, archive=None):
    if not local_demo():
        from edicola.account_ui import render_account_profile
        render_account_profile(root, archive)
        return
    from edicola.design import section_intro
    section_intro("Il mio profilo", "Interessi, letture e preferenze.", "La tua edicola")
    if setting("EDICOLA_CLOUD_DEMO", "0") == "1":
        st.warning("Profilo demo pubblico e condiviso: tutti i visitatori possono leggere, modificare o cancellare "
                   "le preferenze e lo storico. Nessuno spazio personale riservato; non inserire dati personali. "
                   "I dati locali possono andare persi al riavvio.")
    else:
        st.caption("Profilo condiviso: chi usa questa installazione può accedere a questi dati; non è un account riservato.")
    if st.session_state.pop("personal_reset", False):
        for key in list(st.session_state):
            if key.startswith("personal_"):
                del st.session_state[key]
    profile = load_profile(root)
    notice = st.session_state.pop("personal_notice", None)
    if notice:
        st.success(notice)
        st.toast(notice)
    tabs = st.tabs(["Preferenze", "Privacy"])
    with tabs[0]:
        with st.expander("Preferenze e impostazioni", expanded=not profile.interests):
            with st.form("personal_preferences"):
                interests = st.multiselect("Argomenti di interesse", list(dict.fromkeys(profile.interests + INTERESTS)),
                                          default=profile.interests, key="personal_interests", max_selections=10,
                                          accept_new_options=True, placeholder="Scegli o scrivi un interesse")
                st.caption("Le proposte sono categorie di interesse, non indicano notizie necessariamente presenti nell’archivio.")
                minutes = st.selectbox("Tempo disponibile (minuti)", [2, 5, 10],
                                       index=[2, 5, 10].index(profile.minutes), key="personal_minutes")
                preferred = st.selectbox("Formato preferito", ["testo", "visuale", "audio"],
                                        index=["testo", "visuale", "audio"].index(profile.format), key="personal_format")
                save = st.form_submit_button("Salva preferenze", type="primary")
            if save:
                profile.interests = list(dict.fromkeys(t.strip() for t in interests if t.strip()))
                profile.minutes, profile.format = minutes, preferred
                profile.feedback = {t: v for t, v in profile.feedback.items() if t in profile.interests}
                try:
                    save_profile(root, profile)
                    st.session_state["personal_notice"] = "Preferenze salvate. I consigli riflettono le tue scelte."
                    st.rerun()
                except ValueError as exc:
                    st.error(friendly_error(exc))
                    return
    with tabs[1]:
        privacy_controls(key="demo_privacy")
        with st.expander("Cancella i dati del profilo demo"):
                st.caption("La cancellazione rimuove preferenze, letture salvate, briefing personali e relativi audio. I prodotti editoriali generali restano disponibili.")
                if st.button("Cancella preferenze e storico demo", key="personal_delete"):
                    delete_profile(root, profile.user_id)
                    st.session_state["personal_reset"] = True
                    st.session_state["profile_deleted_notice"] = True
                    st.rerun()
    if st.session_state.pop("profile_deleted_notice", False):
        st.success("Preferenze e storico demo cancellati.")



def render_demo_readings(root, archive, profile, catalog):
    """Salvati e briefing demo visualizzati dalla card Per te."""
    with st.expander(f"Le mie letture salvate ({len(profile.saved)})"):
        if not profile.saved:
            st.info("Ritrova qui le letture che vuoi conservare. Usa Salva lettura nelle schede consigliate.")
        for identity, item in profile.saved.items():
            with st.container(border=True):
                st.text(document_label(archive, item["metadata"]["filename"], item["metadata"]["page"]))
                st.markdown(readable("«" + excerpt(item["text"], 230) + "»"))
                with st.expander("Leggi il passaggio salvato"):
                    st.text(item["text"])
                    st.caption("Copia salvata; questa lettura potrebbe non essere più disponibile nell’archivio attuale. Può comprendere più notizie.")
                source_button(item["metadata"]["filename"], item["metadata"]["page"], context=archive, chunk_id=identity, key=f"personal_saved_pdf_{identity}")
                if st.button("Rimuovi dai salvati", key=f"personal_remove_{identity}"):
                    remove_passage(root, profile.user_id, identity)
                    st.session_state["personal_notice"] = "Lettura rimossa dai salvati."
                    st.rerun()
    st.subheader("Il mio briefing")
    submitted = st.button("Genera il mio briefing", key="personal_briefing_submit", type="primary")
    if authorize_action("personal_text", "personal_briefing", submitted, [profile.interests, profile.minutes, profile.feedback]):
        try:
            with st.spinner("Preparo il tuo briefing…"):
                identity, result = perform("personal_text", generate_personal_briefing, root, profile, authorize_external=True, catalog=catalog)
            if not result.sufficient:
                st.warning(product_notice(result))
            else:
                st.session_state["personal_product"] = identity
        except RagError as exc:
            st.error(friendly_error(exc))
        except Exception:
            st.error("Il tuo briefing non è disponibile in questo momento. Le letture salvate restano consultabili.")

    scope = personal_root(root, profile.user_id)
    products = list_products(scope)
    if products:
        keys = [p.key for p in products]
        selected = st.selectbox("I miei briefing già disponibili", keys,
                                format_func=lambda k: next(citation_text(reading_title(p.result), p.result.used_source_ids) + " — " + p.created_at for p in products if p.key == k),
                                key="personal_product")
        product = next(p for p in products if p.key == selected)
        if profile.format == "audio":
            with st.expander("Leggi il briefing personale (preferenza audio)"):
                show_product(product.result, archive)
        else:
            show_product(product.result, archive)
        st.caption("Puoi ascoltare un podcast già salvato o crearne uno. L’audio legge un estratto di circa 1–2 minuti anche per briefing lunghi.")
        with st.expander("Ascolta questo briefing"):
            voice = st.selectbox("Voce del podcast personale", VOICES, key="personal_voice")
            audio_submit = st.button("Genera podcast del mio briefing", key="personal_audio_submit")
        if authorize_action("audio", "personal_audio", audio_submit, [selected, voice]):
            try:
                api_key(root)  # Stesso .env principale, senza copiarne le credenziali.
                with st.spinner("Generazione podcast personale…"):
                    perform("audio", generate_podcast, selected, voice=voice, authorize_external=True, root=scope)
            except (PodcastError, PermissionDenied) as exc:
                st.error(friendly_error(exc))
        existing = cached_audio(scope, selected, voice)
        if existing:
            data, manifest = existing
            st.caption(f"Podcast già disponibile — voce {manifest['voice']}.")
            if manifest["script"]["selected_sections"] < manifest["script"]["total_sections"]:
                st.info("L'audio legge un estratto del briefing, composto da sezioni complete.")
            st.audio(data, format="audio/wav")
            st.download_button("Scarica podcast personale WAV", data, file_name="briefing-personale.wav", mime="audio/wav", key="personal_download")
            with st.expander("Testo letto e fonti del podcast personale"):
                st.text(manifest["script"]["text"])
                for source in manifest["script"]["sources"]:
                    st.text(document_label(archive, source["filename"], source["page"]))
                    source_button(source["filename"], source["page"], context=archive, chunk_id=source["chunk_id"], key=f"personal_audio_pdf_{source['id']}")
    else:
        st.info("Il tuo primo briefing ti aspetta: scegli gli interessi e autorizza la generazione. Puoi esplorare anche Briefing e Podcast.")
