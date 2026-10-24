"""Pannello laterale nativo Streamlit, richiudibile anche su smartphone."""

from datetime import datetime
import streamlit as st

from edicola import chat_sessions as sessions
from edicola.personal_store import PersonalStoreError


def safe_action(callback, *args):
    try:
        callback(*args)
        st.session_state["rag_notice"] = "Modifica salvata."
    except (PersonalStoreError, ValueError):
        st.session_state["rag_navigation_error"] = "La modifica non è stata completata. Riprova più tardi."


def render_navigation():
    backend = sessions.store()
    enabled = backend.history_enabled() if backend else False
    saved = backend.list_chats() if backend else []
    chat = sessions.active()
    # Niente dati personali globali; elenco di soli metadati, messaggi caricati su apertura.
    entries = {item["id"]: item for item in saved}
    entries.update(st.session_state["rag_chats"])
    ordered = sorted(entries, key=lambda cid: entries[cid]["updated_at"], reverse=True)
    if st.session_state.get("nav_section", "Chat AI") != "Chat AI":
        return chat
    with st.sidebar:
        st.subheader("Le tue conversazioni")
        st.button("Nuova chat", key="rag_new_chat", type="primary", on_click=safe_action, args=(sessions.start_new, backend))
        st.session_state["rag_chat_selector"] = chat["id"]
        def select():
            safe_action(sessions.switch, st.session_state["rag_chat_selector"], sessions.store())
        st.selectbox("Conversazioni", ordered, key="rag_chat_selector", label_visibility="collapsed",
                     format_func=lambda cid: entries[cid]["title"] + ("" if entries[cid]["saved"] else " · temporanea"), on_change=select)
        with st.expander("Gestisci questa chat"):
            if st.session_state.get("rag_controls_for") != chat["id"] or "rag_rename_input" not in st.session_state:
                st.session_state["rag_rename_input"] = chat["title"]
                st.session_state["rag_delete_confirm"] = False
                st.session_state["rag_controls_for"] = chat["id"]
            title = st.text_input("Titolo", key="rag_rename_input", max_chars=80)
            def rename():
                safe_action(sessions.rename, st.session_state["rag_active_id"], st.session_state["rag_rename_input"], sessions.store())
            st.button("Rinomina", key="rag_rename", on_click=rename)
            created = datetime.fromisoformat(chat["created_at"]).strftime("%d/%m/%Y")
            updated = datetime.fromisoformat(chat["updated_at"]).strftime("%d/%m/%Y")
            st.caption(f"Creata il {created} · aggiornata il {updated}")
            confirmed = st.checkbox("Confermo di eliminare questa chat", key="rag_delete_confirm")
            st.button("Elimina chat", key="rag_delete", disabled=not confirmed,
                      on_click=safe_action, args=(sessions.delete, chat["id"], backend))
        with st.expander("Cronologia e privacy"):
            if backend:
                st.session_state["rag_save_history"] = enabled
                def change():
                    safe_action(sessions.set_saving, st.session_state["rag_save_history"])
                st.toggle("Salva le nuove chat nel mio account", key="rag_save_history", on_change=change)
                st.caption("Scelta distinta dall’AI. Disattivare blocca nuovi salvataggi; le vecchie chat non vengono eliminate. Le chat temporanee non vengono importate automaticamente.")
            else:
                st.caption("Ospite: le conversazioni durano solo per questa sessione. Accedi per scegliere il salvataggio nel tuo account; nessuna importazione automatica.")
            confirmed_all = st.checkbox("Confermo la cancellazione di tutta la cronologia", key="rag_delete_all_confirm")
            st.button("Cancella tutta la cronologia", key="rag_delete_all", disabled=not confirmed_all,
                      on_click=safe_action, args=(sessions.delete_all, backend))
        if st.session_state.pop("rag_notice", None):
            st.caption("Modifica completata.")
        error = st.session_state.pop("rag_navigation_error", None)
        if error:
            st.error(error)
    return chat
