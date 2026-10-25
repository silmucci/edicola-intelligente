"""Interfaccia del profilo demo; generazioni remote soltanto da form autorizzati."""

import hashlib
import json
from collections import Counter

import streamlit as st

from edicola.editorial_selection import read_catalog
from edicola.embeddings import api_key
from edicola.personalization import generate_personal_briefing, recommend
from edicola.podcast import VOICES, generate_podcast, wav_duration
from edicola.podcast_text import PodcastError, list_products
from edicola.profiles import (delete_profile, load_profile, personal_root, remove_passage,
                             save_profile, set_feedback)
from edicola.rag import RagError
from edicola.pdf_viewer import source_button
from edicola.settings import setting
from edicola.archive_ui import edition_metadata
from edicola.experience_ui import INTERESTS, account_controls, excerpt, passage_card, readable
from edicola.identity import local_demo
from edicola.consent_ui import authorize_action, privacy_controls
from edicola.consent import perform
from edicola.api_guard import PermissionDenied


def show_product(result, archive=None):
    st.subheader(result.title)
    if result.from_cache:
        st.caption("Risultato già disponibile in cache: nessuna nuova generazione.")
    if result.coverage.get("partial"):
        st.warning("Archivio parzialmente indicizzato: questo briefing copre soltanto i contenuti disponibili.")
    if result.message:
        st.info(result.message)
    for section in result.sections:
        with st.container(border=True):
            st.subheader(section["heading"])
            st.markdown(readable(section["text"]))
    with st.expander("Fonti del briefing personale"):
        for source in result.sources:
            if source.id in result.used_source_ids:
                st.text(f"[{source.id}] {source.filename} — pagina {source.page}")
                st.text(source.text)
                source_button(source.filename, source.page, context=archive, chunk_id=source.chunk_id, key=f"personal_brief_pdf_{source.id}")


def cached_audio(scope, product_key, voice=None):
    """Solo lettura locale dei manifest del modulo TTS esistente, con verifica WAV."""
    directory = scope / "data/podcast_cache"
    for path in sorted(directory.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if item["product_key"] != product_key or (voice is not None and item["voice"] != voice):
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
    section_intro("Il mio profilo", "Interessi, letture e preferenze della demo locale.", "La tua edicola")
    privacy_controls(key="demo_privacy")
    if setting("EDICOLA_CLOUD_DEMO", "0") == "1":
        st.warning("Profilo demo pubblico e condiviso: tutti i visitatori possono leggere, modificare o cancellare "
                   "le preferenze e lo storico. Nessuno spazio personale riservato; non inserire dati personali. "
                   "I dati locali possono andare persi al riavvio.")
    else:
        st.caption("Sviluppo locale: profilo demo condiviso. Chi usa questa installazione può accedere a questi dati; non è un account riservato.")
    account_controls()
    if st.session_state.pop("personal_reset", False):
        for key in list(st.session_state):
            if key.startswith("personal_"):
                del st.session_state[key]
    profile = load_profile(root)
    notice = st.session_state.pop("personal_notice", None)
    if notice:
        st.success(notice)
        st.toast(notice)
    st.caption(f"{profile.minutes} minuti per informarti · formato {profile.format}. Nessun tracciamento implicito.")
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
                st.error(str(exc))
                return
        if profile.interests:
            with st.form("personal_feedback"):
                topic = st.selectbox("Argomento su cui dare feedback", profile.interests, key="personal_feedback_topic")
                opinion = st.selectbox("Preferenza volontaria", ["Gradito (+1)", "Non pertinente (escludi)", "Neutro"], key="personal_opinion")
                if st.form_submit_button("Aggiorna gradimento"):
                    set_feedback(root, profile.user_id, topic, {"Gradito (+1)": 1, "Non pertinente (escludi)": -1, "Neutro": 0}[opinion])
                    st.session_state["personal_notice"] = "Gradimento aggiornato. Puoi modificarlo in qualsiasi momento."
                    st.rerun()
            if profile.feedback:
                st.caption("Feedback attivo: " + "; ".join(f"{t}: {'gradito, peso doppio' if v == 1 else 'escluso'}" for t, v in profile.feedback.items()))
        with st.expander("Cancella i dati del profilo demo"):
            st.caption("La cancellazione rimuove preferenze, letture salvate, briefing personali e relativi audio. I prodotti editoriali generali restano disponibili.")
            if st.button("Cancella preferenze e storico demo", key="personal_delete"):
                delete_profile(root, profile.user_id)
                st.session_state["personal_reset"] = True
                st.session_state["profile_deleted_notice"] = True
                st.rerun()
    if st.session_state.pop("profile_deleted_notice", False):
        st.success("Preferenze e storico demo cancellati.")

    st.subheader("Consigliati per te")
    st.caption("Letture vicine ai tuoi interessi, alternate tra le edizioni disponibili. La selezione è locale e non invia dati a Gemini.")
    catalog = None
    recommendations = []
    if profile.interests:
        try:
            catalog = read_catalog(root)
            recommendations = recommend(catalog, profile)
        except Exception:
            st.info("I consigli non sono disponibili in questo momento. Puoi continuare a sfogliare l’Archivio.")
        if catalog and catalog.coverage.get("partial"):
            st.warning("Archivio parziale: i consigli coprono solo i contenuti disponibili alla ricerca.")
    if not recommendations:
        st.info("Non ci sono letture pertinenti per le preferenze attive. Scegli o modifica gli interessi in Preferenze e impostazioni.")
    if profile.format == "visuale" and recommendations:
        counts = Counter(t for r in recommendations for t in r.topics)
        with st.expander("I tuoi interessi nelle letture consigliate"):
            st.bar_chart({"Passaggi pertinenti": counts})
            st.caption("Distribuzione delle corrispondenze agli interessi: non rappresenta relazioni causali.")
    metadata = edition_metadata(root, archive.documents) if archive is not None else {}
    with st.container(horizontal=True, gap="medium"):
        for item in recommendations:
            passage_card(item.chunk, context=archive, editions=metadata, key=f"personal_recommended_{item.chunk.id}",
                         reason=item.reason, root=root, profile=profile)
    with st.expander(f"Notizie salvate ({len(profile.saved)})"):
        if not profile.saved:
            st.info("Ritrova qui le letture che vuoi conservare. Usa Salva lettura nelle schede consigliate.")
        for identity, item in profile.saved.items():
            with st.container(border=True):
                st.text(f"{item['metadata']['filename']} — pagina {item['metadata']['page']}")
                st.markdown(readable("«" + excerpt(item["text"], 230) + "»"))
                with st.expander("Leggi il passaggio salvato"):
                    st.text(item["text"])
                    st.caption("Copia locale salvata; potrebbe non appartenere più all'indice corrente. Può comprendere più notizie.")
                source_button(item["metadata"]["filename"], item["metadata"]["page"], context=archive, chunk_id=identity, key=f"personal_saved_pdf_{identity}")
                if st.button("Rimuovi dai salvati", key=f"personal_remove_{identity}"):
                    remove_passage(root, profile.user_id, identity)
                    st.session_state["personal_notice"] = "Lettura rimossa dai salvati."
                    st.rerun()
    st.subheader("Il mio briefing")
    submitted = st.button("Genera il mio briefing", key="personal_briefing_submit", type="primary")
    if authorize_action("personal_text", "personal_briefing", submitted, [profile.interests, profile.minutes, profile.feedback]):
        try:
            with st.spinner("Generazione del briefing personale con fonti validate…"):
                identity, result = perform("personal_text", generate_personal_briefing, root, profile, authorize_external=True, catalog=catalog)
            if not result.sufficient:
                st.warning(result.message or "Informazioni insufficienti per un briefing verificabile.")
            else:
                st.session_state["personal_product"] = identity
        except RagError as exc:
            st.error(str(exc))
        except Exception:
            st.error("Briefing personale non disponibile: verificare configurazione, connessione e cache locale.")

    scope = personal_root(root, profile.user_id)
    products = list_products(scope)
    if products:
        keys = [p.key for p in products]
        selected = st.selectbox("I miei briefing già disponibili", keys,
                                format_func=lambda k: next(p.result.title + " — " + p.created_at for p in products if p.key == k),
                                key="personal_product")
        product = next(p for p in products if p.key == selected)
        st.caption("Briefing salvato: riflette le preferenze e le fonti al momento della generazione. Per applicare le modifiche usa Genera il mio briefing.")
        if profile.format == "audio":
            with st.expander("Leggi il briefing personale (preferenza audio)"):
                show_product(product.result, archive)
        else:
            show_product(product.result, archive)
        st.caption("Per il formato audio puoi ascoltare un podcast già salvato o generarlo esplicitamente. Il TTS esistente legge un estratto di circa 1–2 minuti anche per briefing lunghi.")
        with st.expander("Ascolta questo briefing"):
            voice = st.selectbox("Voce del podcast personale", VOICES, key="personal_voice")
            audio_submit = st.button("Genera podcast del mio briefing", key="personal_audio_submit")
        if authorize_action("audio", "personal_audio", audio_submit, [selected, voice]):
            try:
                api_key(root)  # Stesso .env principale, senza copiarne le credenziali.
                with st.spinner("Generazione podcast personale…"):
                    perform("audio", generate_podcast, selected, voice=voice, authorize_external=True, root=scope)
            except (PodcastError, PermissionDenied) as exc:
                st.error(str(exc))
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
                    st.text(f"{source['filename']} — pagina {source['page']}")
                    source_button(source["filename"], source["page"], context=archive, chunk_id=source["chunk_id"], key=f"personal_audio_pdf_{source['id']}")
    else:
        st.info("Il tuo primo briefing ti aspetta: scegli gli interessi e autorizza la generazione. Puoi esplorare anche Briefing, Dossier e Podcast.")
