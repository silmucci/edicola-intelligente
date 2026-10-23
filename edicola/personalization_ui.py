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
                             save_passage, save_profile, set_feedback)
from edicola.rag import RagError
from edicola.pdf_viewer import source_button
from edicola.settings import setting


def show_product(result, archive=None):
    st.subheader(result.title)
    if result.from_cache:
        st.caption("Risultato già disponibile in cache: nessuna nuova generazione.")
    if result.coverage.get("partial"):
        st.warning("Archivio parzialmente indicizzato: questo briefing copre soltanto i contenuti disponibili.")
    if result.message:
        st.info(result.message)
    for section in result.sections:
        st.text(section["heading"])
        st.text(section["text"])
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
    st.header("Il mio profilo")
    if setting("EDICOLA_CLOUD_DEMO", "0") == "1":
        st.warning("Profilo demo pubblico e condiviso: tutti i visitatori possono leggere, modificare o cancellare "
                   "le preferenze e lo storico. Nessuna autenticazione o riservatezza; non inserire dati personali. "
                   "I dati locali possono andare persi al riavvio.")
    else:
        st.caption("Profilo demo locale: nessuna autenticazione. Chi usa questa installazione può accedere a questi dati; non è un account riservato.")
    if st.session_state.pop("personal_reset", False):
        for key in list(st.session_state):
            if key.startswith("personal_"):
                del st.session_state[key]
    profile = load_profile(root)
    st.caption(f"Identificativo: {profile.user_id}. Nessun tracciamento implicito delle letture.")
    with st.form("personal_preferences"):
        interests = st.text_area("Argomenti di interesse (uno per riga, massimo 10)",
                                 value="\n".join(profile.interests), key="personal_interests")
        minutes = st.selectbox("Tempo disponibile (minuti)", [2, 5, 10],
                               index=[2, 5, 10].index(profile.minutes), key="personal_minutes")
        preferred = st.selectbox("Formato preferito", ["testo", "visuale", "audio"],
                                index=["testo", "visuale", "audio"].index(profile.format), key="personal_format")
        save = st.form_submit_button("Salva preferenze")
    if save:
        profile.interests = list(dict.fromkeys(t.strip() for t in interests.splitlines() if t.strip()))
        profile.minutes, profile.format = minutes, preferred
        profile.feedback = {t: v for t, v in profile.feedback.items() if t in profile.interests}
        try:
            save_profile(root, profile)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
            return
    if st.button("Cancella preferenze e storico demo", key="personal_delete"):
        delete_profile(root, profile.user_id)
        st.session_state["personal_reset"] = True
        st.rerun()
    st.caption("La cancellazione rimuove anche passaggi salvati, briefing personali e relativi audio. I prodotti editoriali generali restano disponibili.")
    if profile.interests:
        with st.form("personal_feedback"):
            topic = st.selectbox("Argomento su cui dare feedback", profile.interests, key="personal_feedback_topic")
            opinion = st.selectbox("Preferenza volontaria", ["Gradito (+1)", "Non pertinente (escludi)", "Neutro"], key="personal_opinion")
            if st.form_submit_button("Aggiorna gradimento"):
                set_feedback(root, profile.user_id, topic, {"Gradito (+1)": 1, "Non pertinente (escludi)": -1, "Neutro": 0}[opinion])
                st.rerun()
        if profile.feedback:
            st.caption("Feedback attivo: " + "; ".join(f"{t}: {'gradito, peso doppio' if v == 1 else 'escluso'}" for t, v in profile.feedback.items()))

    st.subheader("Consigliati per te")
    st.caption("Selezione locale per parole degli interessi (almeno il 60%), deduplicazione e rotazione tra edizioni. Nessuna chiamata Gemini. Un passaggio può contenere più notizie.")
    catalog = None
    recommendations = []
    if profile.interests:
        try:
            catalog = read_catalog(root)
            recommendations = recommend(catalog, profile)
        except Exception:
            st.info("Catalogo indicizzato non disponibile: nessuna indicizzazione o chiamata esterna avviata.")
        if catalog and catalog.coverage.get("partial"):
            st.warning(f"Archivio parziale: {catalog.coverage['indexed']} chunk indicizzati su {catalog.coverage['total']}.")
    if not recommendations:
        st.info("Inserisci o modifica gli interessi: nessun passaggio pertinente disponibile per le preferenze attive.")
    if profile.format == "visuale" and recommendations:
        counts = Counter(t for r in recommendations for t in r.topics)
        st.bar_chart({"Passaggi pertinenti": counts})
        st.caption("Distribuzione delle corrispondenze agli interessi: non rappresenta relazioni causali.")
    for item in recommendations:
        chunk = item.chunk
        with st.expander(f"{chunk.metadata['filename']} — pagina {chunk.metadata['page']}"):
            st.caption(item.reason + f". Punteggio locale: {item.score:g}; alternanza tra edizioni.")
            st.text(chunk.text)
            source_button(chunk.metadata["filename"], chunk.metadata["page"], context=archive, chunk_id=chunk.id, key=f"personal_recommended_pdf_{chunk.id}")
            if chunk.id not in profile.saved:
                if st.button("Salva passaggio", key=f"personal_save_{chunk.id}"):
                    save_passage(root, profile.user_id, chunk)
                    st.rerun()
    with st.expander(f"Passaggi salvati ({len(profile.saved)})"):
        for identity, item in profile.saved.items():
            st.text(f"{item['metadata']['filename']} — pagina {item['metadata']['page']}")
            st.text(item["text"])
            source_button(item["metadata"]["filename"], item["metadata"]["page"], context=archive, chunk_id=identity, key=f"personal_saved_pdf_{identity}")
            st.caption("Copia locale salvata; potrebbe non appartenere più all'indice corrente.")
            if st.button("Rimuovi dai salvati", key=f"personal_remove_{identity}"):
                remove_passage(root, profile.user_id, identity)
                st.rerun()
    with st.form("personal_briefing_form"):
        authorized = st.checkbox("Autorizzo l'invio a Gemini dei passaggi consigliati e del tempo di lettura per il mio briefing", key="personal_authorized")
        submitted = st.form_submit_button("Genera il mio briefing")
    if submitted:
        if not authorized:
            st.warning("Autorizza l'invio prima di generare il briefing personale.")
        else:
            try:
                with st.spinner("Generazione del briefing personale con fonti validate…"):
                    identity, result = generate_personal_briefing(root, profile, authorize_external=True, catalog=catalog)
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
                                format_func=lambda k: next(p.result.title + " — " + p.created_at + " · " + k[:6] for p in products if p.key == k),
                                key="personal_product")
        product = next(p for p in products if p.key == selected)
        st.caption("Briefing salvato: riflette le preferenze e le fonti al momento della generazione. Per applicare le modifiche usa Genera il mio briefing.")
        if profile.format == "audio":
            with st.expander("Leggi il briefing personale (preferenza audio)"):
                show_product(product.result, archive)
        else:
            show_product(product.result, archive)
        st.caption("Per il formato audio puoi ascoltare un podcast già salvato o generarlo esplicitamente. Il TTS esistente legge un estratto di circa 1–2 minuti anche per briefing lunghi.")
        with st.form("personal_audio_form"):
            voice = st.selectbox("Voce del podcast personale", VOICES, key="personal_voice")
            audio_authorized = st.checkbox("Autorizzo l'invio del copione a Gemini TTS", key="personal_audio_authorized")
            audio_submit = st.form_submit_button("Genera podcast del mio briefing")
        if audio_submit:
            if not audio_authorized:
                st.warning("Autorizza l'invio del copione prima di generare l'audio.")
            else:
                try:
                    api_key(root)  # Stesso .env principale, senza copiarne le credenziali.
                    with st.spinner("Generazione podcast personale…"):
                        generate_podcast(selected, voice=voice, authorize_external=True, root=scope)
                except PodcastError as exc:
                    st.error(str(exc))
        existing = cached_audio(scope, selected, voice)
        if existing:
            data, manifest = existing
            st.caption(f"Podcast già disponibile — voce {manifest['voice']}, modello {manifest['model']}.")
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
        st.caption("I briefing e gli audio generali già disponibili restano nella sezione Prodotti editoriali. Nessun nuovo contenuto viene generato automaticamente.")
