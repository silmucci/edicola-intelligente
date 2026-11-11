"""Area personale persistente: usa il CRUD server-side, mai il vecchio profilo demo."""

import json

import streamlit as st

from edicola.embeddings import api_key
from edicola.identity import current_identity, synchronize_identity
from edicola.personal_audio import audio_scope, prepare_audio, remove_audio
from edicola.personal_store import PersonalStoreError, PostgresPersonalStore
from edicola.personalization import generate_personal_briefing
from edicola.editorial_selection import read_catalog
from edicola.pdf_viewer import source_button
from edicola.podcast import VOICES, generate_podcast
from edicola.podcast_text import PodcastError
from edicola.rag import RagError
from edicola.settings import setting
from edicola.private_media import private_download
from edicola.consent_ui import authorize_action, privacy_controls
from edicola.consent import perform
from edicola.api_guard import PermissionDenied
from edicola.design import friendly_error, section_intro, product_notice
from edicola.chat_sources import document_label, citation_text


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
                   "Per informazioni sul trattamento dei dati puoi contattare il gestore.")
        st.caption("Contatti del gestore: " + setting("EDICOLA_PRIVACY_CONTACT", "non disponibili"))
        st.caption("Il tuo spazio personale conserva preferenze e prodotti riservati al tuo account. Briefing e Podcast generali restano condivisi.")


def render_account_profile(root, archive=None):
    from edicola.experience_ui import INTERESTS
    synchronize_identity()
    section_intro("Il mio profilo", "Gestisci i tuoi interessi e le impostazioni personali.", "La tua edicola")
    if current_identity() is None:
        privacy_controls()
        privacy_notice()
        st.info("Accedi con Google dal menu Profilo in alto per salvare preferenze, letture e briefing. Puoi consultare l’Archivio senza registrarti.")
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
        if not profile.interests:
            st.subheader("Cominciamo dai tuoi interessi")
            st.caption("Scegli qualche tema e il tempo che hai: troverai qui letture dedicate ai tuoi interessi.")
        if st.session_state.get("personal_area") not in (None, "Preferenze", "Raccolta", "Privacy"):
            st.session_state.pop("personal_area", None)
        areas = st.tabs(["Preferenze", "Raccolta", "Privacy"],
                        default="Preferenze",
                        key="personal_area", on_change="rerun")
        with areas[2]:
            if st.session_state.get("personal_area") == "Privacy":
                privacy_controls()
            privacy_notice()
            with st.expander("Esporta i miei dati"):
                st.caption("Puoi ottenere una copia dei dati associati al tuo profilo.")
                if st.button("Prepara una copia", key="account_export_prepare"):
                    st.session_state["account_export"] = json.dumps(store.export_data(), ensure_ascii=False, indent=2)
                if "account_export" in st.session_state:
                    private_download(st.session_state["account_export"], label="Scarica i miei dati",
                                     filename="i-miei-dati-edicola.json", mime="application/json",
                                     key="account_export_download")
            with st.expander("Elimina i miei dati"):
                st.warning("Questa operazione elimina preferenze, letture salvate, briefing personali e cronologia chat.")
                confirmed = st.checkbox("Confermo di voler eliminare i miei dati", key="account_delete_confirm")
                if st.button("Elimina definitivamente", key="account_delete", disabled=not confirmed):
                    store.delete_all()
                    cleanup_failed = False
                    try:
                        remove_audio(root, store)
                    except (OSError, PersonalStoreError):
                        cleanup_failed = True
                    from edicola.identity import clear_private_state
                    clear_private_state()
                    if cleanup_failed:
                        st.session_state["account_warning"] = (
                            "Dati personali cancellati; alcuni audio temporanei non sono stati rimossi. Contatta il gestore."
                        )
                    else:
                        st.session_state["account_notice"] = "I tuoi dati personali sono stati cancellati."
                    st.rerun()
        with areas[0]:
            st.subheader("I miei interessi")
            st.caption("Scegli gli argomenti che ti interessano.")
            options = list(dict.fromkeys(profile.interests + INTERESTS))
            selected = st.pills("Argomenti", options, selection_mode="multi",
                                default=profile.interests, key="account_interest_chips",
                                label_visibility="collapsed")
            selected = list(selected or [])
            if selected != profile.interests:
                if len(selected) > 10:
                    st.warning("Puoi seguire fino a 10 argomenti.")
                else:
                    profile.interests = selected
                    profile.feedback = {k: v for k, v in profile.feedback.items() if k in selected}
                    store.save_preferences(profile)
                    st.session_state.pop("account_export", None)
                    st.toast("Interessi aggiornati")
                    st.rerun()
            with st.expander("Aggiungi un argomento"):
                topic = st.text_input("Nuovo argomento", max_chars=100,
                                      key="account_custom_interest", placeholder="Ad esempio: Cinema")
                if st.button("Aggiungi", key="account_add_interest", disabled=not topic.strip()):
                    new_topic = topic.strip()
                    if new_topic not in profile.interests and len(profile.interests) >= 10:
                        st.warning("Puoi seguire fino a 10 argomenti.")
                    elif new_topic not in profile.interests:
                        profile.interests = profile.interests + [new_topic]
                        store.save_preferences(profile)
                        st.session_state.pop("account_export", None)
                        st.session_state.pop("account_custom_interest", None)
                        st.toast("Interesse aggiunto")
                        st.rerun()
            st.divider()
            st.subheader("Preferenze di lettura")
            st.caption("Scegli quanto tempo dedicare alle notizie e come preferisci consultarle.")
            minutes = st.segmented_control("Tempo di lettura", [2, 5, 10],
                                           default=profile.minutes, format_func=lambda n: f"{n} min",
                                           key="account_reading_minutes")
            preferred = st.segmented_control("Formato preferito", ["testo", "visuale", "audio"],
                                             default=profile.format, key="account_reading_format")
            if minutes is not None and preferred is not None and (
                minutes != profile.minutes or preferred != profile.format
            ):
                profile.minutes, profile.format = minutes, preferred
                store.save_preferences(profile)
                st.session_state.pop("account_export", None)
                st.toast("Preferenze salvate")
                st.rerun()
        with areas[1]:
            # Streamlit monta anche schede non visibili: carica solo quella scelta.
            if st.session_state.get("personal_area") == "Raccolta":
                if archive is None:
                    st.caption("I collegamenti ai PDF sono disponibili quando l'archivio è aperto.")
                try:
                    catalog = read_catalog(root) if archive is not None else None
                except (OSError, ValueError, RuntimeError):
                    catalog = None
                render_account_readings(root, archive, store, profile, catalog)
    except PersonalStoreError:
        st.error("Il tuo spazio personale non è disponibile in questo momento. Riprova più tardi: nessun nuovo salvataggio è stato confermato.")
    except (PermissionDenied, RagError, PodcastError) as exc:
        st.error(friendly_error(exc))
    except ValueError as exc:
        st.error(friendly_error(exc))


def render_account_readings(root, archive, store, profile, catalog):
    """Letture e briefing personali disponibili nella Raccolta del Profilo."""
    from edicola.experience_ui import excerpt, readable
    from edicola.personalization_ui import cached_audio, show_product
    try:
        with st.expander(f"Le mie letture salvate ({len(profile.saved)})"):
            current = {c.id: c for c in catalog.chunks} if catalog else {}
            for key, item in profile.saved.items():
                ref = item["metadata"]
                with st.container(border=True):
                    st.text(document_label(archive, ref["filename"], ref["page"]))
                    chunk = current.get(key)
                    if chunk and chunk.metadata.get("pdf_sha256") == ref.get("pdf_sha256"):
                        st.markdown(readable("«" + excerpt(chunk.text, 230) + "»"))
                        source_button(ref["filename"], ref["page"], context=archive, chunk_id=key, key=f"personal_saved_pdf_{key}")
                    else:
                        st.caption("Il riferimento è conservato nel tuo account; questa versione del passaggio non è disponibile nell’archivio attuale.")
                    if st.button("Rimuovi dai salvati", key=f"personal_remove_{key}"):
                        store.remove_passage(key)
                        st.session_state.pop("account_export", None)
                        st.session_state["account_notice"] = "Lettura rimossa dai salvati."
                        st.rerun()
        st.subheader("Il mio briefing")
        generate = st.button("Genera il mio briefing", key="personal_briefing_submit", type="primary", disabled=not profile.interests)
        if authorize_action("personal_text", "personal_briefing", generate, [profile.interests, profile.minutes, profile.feedback]):
            with st.spinner("Preparazione e salvataggio del briefing personale…"):
                key, result = perform("personal_text", generate_personal_briefing, root, profile, authorize_external=True, catalog=catalog, store=store)
            if result.sufficient:
                st.session_state["personal_product"] = key
                st.success("Briefing disponibile nel tuo account.")
            else:
                st.info(product_notice(result))
        products = store.list_products()
        if not products:
            st.info("Non hai ancora briefing salvati. La generazione richiede il tuo consenso esplicito.")
            return
        available = {p.key: p for p in products}
        if st.session_state.get("personal_product") not in available:
            st.session_state.pop("personal_product", None)
        selected = st.selectbox("I miei briefing già disponibili", list(available), key="personal_product",
                                format_func=lambda key: citation_text(available[key].result.title, available[key].result.used_source_ids) + " — " + available[key].created_at)
        product = available[selected]
        if profile.format == "audio":
            with st.expander("Leggi il briefing personale (preferenza audio)"):
                show_product(product.result, archive)
        else:
            show_product(product.result, archive)
        
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
                    st.text(document_label(archive, source["filename"], source["page"]))
                    source_button(source["filename"], source["page"], context=archive, chunk_id=source["chunk_id"], key=f"personal_audio_pdf_{source['id']}")
    except (PersonalStoreError, PermissionDenied, RagError, PodcastError, ValueError) as exc:
        st.error(friendly_error(exc))
