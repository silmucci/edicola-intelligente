"""Area personale persistente: usa il CRUD server-side, mai il vecchio profilo demo."""

import json
from collections import Counter

import streamlit as st

from edicola.archive_ui import edition_metadata
from edicola.editorial_selection import read_catalog
from edicola.embeddings import api_key
from edicola.identity import current_identity, login_controls, synchronize_identity
from edicola.personal_audio import audio_scope, prepare_audio, remove_audio
from edicola.personal_store import PersonalStoreError, PostgresPersonalStore
from edicola.personalization import generate_personal_briefing, recommend
from edicola.pdf_viewer import source_button
from edicola.podcast import VOICES, generate_podcast
from edicola.podcast_text import PodcastError
from edicola.rag import RagError
from edicola.settings import setting
from edicola.private_media import private_download
from edicola.consent_ui import authorize_action, privacy_controls
from edicola.consent import perform
from edicola.api_guard import PermissionDenied
from edicola.design import friendly_error, section_intro


def personal_context():
    identity = current_identity()
    if identity is None:
        raise PersonalStoreError("Accedi con Google per utilizzare il tuo profilo personale.")
    store = PostgresPersonalStore(identity)
    return store, store.load_profile()


def privacy_notice():
    with st.expander("Privacy e dati personali"):
        st.markdown("Conserviamo un identificativo pseudonimo derivato dall’identità Google verificata, "
                    "interessi dichiarati, tempo/formato, feedback, riferimenti alle letture salvate e briefing personali. "
                    "Solo se attivi il salvataggio conserviamo anche conversazioni, messaggi e passaggi citati. "
                    "Non conserviamo email, nome, password o token Google nel database personale. "
                    "I dati restano fino alla cancellazione richiesta da te; backup e log del fornitore seguono "
                    "i suoi tempi di conservazione. Puoi esportare o cancellare i tuoi dati qui sotto.")
        st.caption("Gemini riceve contenuti soltanto dopo il consenso e l’invio espliciti. "
                   "Gli audio sono file temporanei sul server, non uno storage persistente. "
                   "L’accesso Google non richiede il consenso alle funzionalità AI. "
                   "Il gestore deve pubblicare la propria informativa completa con contatti, finalità e fornitori.")
        st.caption("Contatti del gestore: " + setting("EDICOLA_PRIVACY_CONTACT", "da configurare prima della pubblicazione"))
        st.caption("Il tuo spazio personale conserva preferenze e prodotti riservati al tuo account. Approfondimenti e Podcast generali restano condivisi.")


def render_account_profile(root, archive=None):
    from edicola.experience_ui import INTERESTS, excerpt, passage_card, readable
    from edicola.personalization_ui import cached_audio, show_product
    synchronize_identity()
    section_intro("Il mio profilo", "Il tuo tempo, i tuoi interessi, le tue letture. Preferenze e privacy in un unico spazio.", "La tua edicola")
    login_controls()
    if current_identity() is None:
        privacy_controls()
        privacy_notice()
        st.info("Accedi per salvare preferenze, letture e briefing sul tuo account. Puoi consultare l’Archivio senza registrarti.")
        return
    try:
        store, profile = personal_context()
        notice = st.session_state.pop("account_notice", None)
        if notice:
            st.success(notice)
            st.toast(notice)
        warning = st.session_state.pop("account_warning", None)
        if warning:
            st.warning(warning)
        st.caption(f"Il tuo spazio · {profile.minutes} minuti · formato {profile.format}. Preferenze, salvati e briefing ti seguono anche su un altro dispositivo.")
        if not profile.interests:
            st.subheader("Cominciamo dai tuoi interessi")
            st.caption("Scegli qualche tema e il tempo che hai: troverai qui una selezione locale, senza invii automatici all’AI.")
        areas = st.tabs(["Per te", "Raccolta", "I miei briefing", "Preferenze", "Privacy"],
                        default="Preferenze" if not profile.interests else "Per te",
                        key="personal_area", on_change="rerun")
        with areas[4]:
            if st.session_state.get("personal_area") == "Privacy":
                privacy_controls()
            privacy_notice()
        with areas[3]:
            with st.expander("Preferenze e impostazioni", expanded=not profile.interests):
                with st.form("personal_preferences"):
                    interests = st.multiselect("Argomenti di interesse", list(dict.fromkeys(profile.interests + INTERESTS)),
                                              default=profile.interests, key="personal_interests", max_selections=10,
                                              accept_new_options=True, placeholder="Scegli o scrivi un interesse")
                    minutes = st.selectbox("Tempo disponibile (minuti)", [2, 5, 10], index=[2, 5, 10].index(profile.minutes), key="personal_minutes")
                    preferred = st.selectbox("Formato preferito", ["testo", "visuale", "audio"],
                                            index=["testo", "visuale", "audio"].index(profile.format), key="personal_format")
                    save = st.form_submit_button("Salva preferenze", type="primary")
                if save:
                    profile.interests, profile.minutes, profile.format = interests, minutes, preferred
                    profile.feedback = {k: v for k, v in profile.feedback.items() if k in interests}
                    store.save_preferences(profile)
                    st.session_state.pop("account_export", None)
                    st.session_state["account_notice"] = "Preferenze salvate nel tuo account."
                    st.rerun()
                if profile.interests:
                    with st.form("personal_feedback"):
                        topic = st.selectbox("Argomento su cui dare feedback", profile.interests, key="personal_feedback_topic")
                        opinion = st.selectbox("Preferenza volontaria", ["Gradito (+1)", "Non pertinente (escludi)", "Neutro"], key="personal_opinion")
                        if st.form_submit_button("Aggiorna gradimento"):
                            store.set_feedback(topic, {"Gradito (+1)": 1, "Non pertinente (escludi)": -1, "Neutro": 0}[opinion])
                            st.session_state.pop("account_export", None)
                            st.session_state["account_notice"] = "Gradimento aggiornato."
                            st.rerun()
                    if profile.feedback:
                        st.caption("Feedback attivo: " + "; ".join(f"{topic}: {'gradito' if value == 1 else 'escluso'}" for topic, value in profile.feedback.items()))
                if st.button("Prepara esportazione dei miei dati", key="account_export_prepare"):
                    st.session_state["account_export"] = json.dumps(store.export_data(), ensure_ascii=False, indent=2)
                if "account_export" in st.session_state:
                    private_download(st.session_state["account_export"], label="Scarica i miei dati JSON", filename="i-miei-dati-edicola.json", mime="application/json", key="account_export_download")
                with st.expander("Cancella i miei dati"):
                    confirmed = st.checkbox("Confermo la cancellazione di preferenze, salvati, briefing personali e cronologia chat", key="account_delete_confirm")
                    if st.button("Cancella tutti i miei dati", key="account_delete", disabled=not confirmed):
                        store.delete_all()
                        cleanup_failed = False
                        try:
                            remove_audio(root, store)
                        except (OSError, PersonalStoreError):
                            cleanup_failed = True
                        from edicola.identity import clear_private_state
                        clear_private_state()
                        if cleanup_failed:
                            st.session_state["account_warning"] = "Dati PostgreSQL cancellati; alcuni audio temporanei non sono stati rimossi. Contatta il gestore."
                        else:
                            st.session_state["account_notice"] = "I tuoi dati personali sono stati cancellati."
                        st.rerun()
        try:
            catalog = read_catalog(root)
        except Exception:
            catalog = None
            st.info("Le letture consigliate non sono disponibili in questo momento.")
        with areas[0]:
            st.subheader("Consigliati per te")
            recommendations = recommend(catalog, profile) if catalog else []
            if catalog and catalog.coverage.get("partial"):
                st.caption("La selezione copre soltanto i contenuti attualmente disponibili alla ricerca.")
            if not recommendations:
                st.info("Scegli o modifica gli interessi per trovare letture pertinenti nell’archivio disponibile.")
            metadata = edition_metadata(root, archive.documents) if archive else {}
            if profile.format == "visuale" and recommendations:
                with st.expander("I tuoi interessi nelle letture consigliate"):
                    st.bar_chart({"Passaggi pertinenti": Counter(topic for item in recommendations for topic in item.topics)})
            with st.container(horizontal=True, gap="medium"):
                for item in recommendations:
                    passage_card(item.chunk, context=archive, editions=metadata, key=f"personal_recommended_{item.chunk.id}",
                                 reason=item.reason, root=root, profile=profile, store=store)
        with areas[1]:
            with st.expander(f"Notizie salvate ({len(profile.saved)})"):
                current = {c.id: c for c in catalog.chunks} if catalog else {}
                if not profile.saved:
                    st.info("Usa Salva lettura per ritrovare qui i riferimenti ai quotidiani originali.")
                for key, item in profile.saved.items():
                    ref = item["metadata"]
                    with st.container(border=True):
                        st.text(f"{ref['filename']} — pagina {ref['page']}")
                        chunk = current.get(key)
                        if chunk and chunk.metadata.get("pdf_sha256") == ref.get("pdf_sha256"):
                            st.markdown(readable("«" + excerpt(chunk.text, 230) + "»"))
                            with st.expander("Leggi il passaggio salvato"):
                                st.text(chunk.text)
                            source_button(ref["filename"], ref["page"], context=archive, chunk_id=key, key=f"personal_saved_pdf_{key}")
                        else:
                            st.caption("Il riferimento è conservato nel tuo account; questa versione del passaggio non è disponibile nell’archivio attuale.")
                        if st.button("Rimuovi dai salvati", key=f"personal_remove_{key}"):
                            store.remove_passage(key)
                            st.session_state.pop("account_export", None)
                            st.session_state["account_notice"] = "Lettura rimossa dai salvati."
                            st.rerun()
        with areas[2]:
            st.subheader("Il mio briefing")
            generate = st.button("Genera il mio briefing", key="personal_briefing_submit", type="primary", disabled=not profile.interests)
            if authorize_action("personal_text", "personal_briefing", generate, [profile.interests, profile.minutes, profile.feedback]):
                with st.spinner("Preparazione e salvataggio del briefing personale…"):
                    key, result = perform("personal_text", generate_personal_briefing, root, profile, authorize_external=True, catalog=catalog, store=store)
                if result.sufficient:
                    st.session_state["personal_product"] = key
                    st.success("Briefing disponibile nel tuo account.")
                else:
                    st.info(result.message or "Fonti insufficienti per un briefing verificabile.")
            products = store.list_products()
            if not products:
                st.info("Non hai ancora briefing salvati. La generazione richiede il tuo consenso esplicito.")
                return
            available = {p.key: p for p in products}
            if st.session_state.get("personal_product") not in available:
                st.session_state.pop("personal_product", None)
            selected = st.selectbox("I miei briefing già disponibili", list(available), key="personal_product",
                                    format_func=lambda key: available[key].result.title + " — " + available[key].created_at)
            product = available[selected]
            if profile.format == "audio":
                with st.expander("Leggi il briefing personale (preferenza audio)"):
                    show_product(product.result, archive)
            else:
                show_product(product.result, archive)
            st.caption("Il testo e le fonti sono salvati nel tuo account. Gli audio sono temporanei e possono andare persi al riavvio.")
            with st.expander("Ascolta questo briefing"):
                voice = st.selectbox("Voce del podcast personale", VOICES, key="personal_voice")
                audio_submit = st.button("Genera podcast del mio briefing", key="personal_audio_submit")
            if authorize_action("audio", "personal_audio", audio_submit, [selected, voice]):
                api_key(root)
                with st.spinner("Generazione del podcast personale…"):
                    scope = prepare_audio(root, store, selected)
                    perform("audio", generate_podcast, selected, voice=voice, authorize_external=True, root=scope)
            existing = cached_audio(audio_scope(root, store), selected, voice)
            if existing:
                data, manifest = existing
                if manifest["script"]["selected_sections"] < manifest["script"]["total_sections"]:
                    st.info("L’audio legge un estratto del briefing, composto da sezioni complete.")
                private_download(data, label="Scarica podcast personale WAV", filename="briefing-personale.wav", mime="audio/wav", key="personal_download", play=True)
                with st.expander("Testo letto e fonti del podcast personale"):
                    st.text(manifest["script"]["text"])
                    for source in manifest["script"]["sources"]:
                        st.text(f"{source['filename']} — pagina {source['page']}")
                        source_button(source["filename"], source["page"], context=archive, chunk_id=source["chunk_id"], key=f"personal_audio_pdf_{source['id']}")
    except PersonalStoreError:
        st.error("Il tuo spazio personale non è disponibile in questo momento. Riprova più tardi: nessun nuovo salvataggio è stato confermato.")
    except (PermissionDenied, RagError, PodcastError) as exc:
        st.error(friendly_error(exc))
    except ValueError as exc:
        st.error(str(exc))
