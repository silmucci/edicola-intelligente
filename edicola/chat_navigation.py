"""Navigazione compatta della chat: cronologia persistente solo su scelta esplicita."""

import streamlit as st

from edicola import chat_sessions as sessions
from edicola.personal_store import PersonalStoreError


def safe_action(callback, *args):
    try:
        callback(*args)
        st.session_state["rag_notice"] = "Modifica salvata."
    except (PersonalStoreError, ValueError):
        st.session_state["rag_navigation_error"] = "Operazione non completata. Riprova."


def _open_chat(chat_id):
    safe_action(sessions.switch, chat_id, sessions.store())


def _rename_current():
    safe_action(sessions.rename, st.session_state["rag_active_id"],
                st.session_state["rag_rename_input"], sessions.store())


def _change_history():
    safe_action(sessions.set_saving, st.session_state["rag_save_history"])


def _conversation_button(item, chat_id, active_id):
    title = item.get("title") or "Nuova chat"
    temporary = not item.get("saved", False)
    label = title + (" · temporanea" if temporary else "")
    st.button(label, key=f"rag_select_{chat_id}", use_container_width=True,
              type="primary" if chat_id == active_id else "secondary",
              on_click=_open_chat, args=(chat_id,))


def render_navigation():
    if st.session_state.get("nav_section", "Chat AI") != "Chat AI":
        return sessions.active()

    backend = sessions.store()
    enabled = backend.history_enabled() if backend else False
    saved = backend.list_chats() if backend else []

    # Alla riapertura dell'app recupera la conversazione più recente dal proprio account.
    # Non crea nuovi messaggi né abilita il salvataggio senza consenso.
    if saved and not st.session_state.get("rag_active_id"):
        sessions.switch(saved[0]["id"], backend)
    chat = sessions.active()

    entries = {item["id"]: item for item in saved}
    entries.update(st.session_state.get("rag_chats", {}))
    ordered = sorted(entries, key=lambda cid: entries[cid]["updated_at"], reverse=True)

    with st.sidebar:
        st.subheader("Le tue chat")
        st.button("Nuova chat", key="rag_new_chat", type="primary",
                  icon=":material/add:", use_container_width=True,
                  on_click=safe_action, args=(sessions.start_new, backend))

        if backend:
            st.toggle("Salva le chat nel mio account", value=enabled,
                      key="rag_save_history", on_change=_change_history,
                      help="Le nuove conversazioni saranno disponibili anche dopo aver chiuso l'app.")
        else:
            st.caption("Accedi con Google per conservare le conversazioni.")

        # I nomi delle chat sono pulsanti, senza selettori o riquadri aggiuntivi.
        if ordered:
            st.caption("Conversazioni")
            for chat_id in ordered[:10]:
                _conversation_button(entries[chat_id], chat_id, chat["id"])
            if len(ordered) > 10:
                with st.expander("Altre conversazioni"):
                    for chat_id in ordered[10:]:
                        _conversation_button(entries[chat_id], chat_id, chat["id"])

        with st.popover("Opzioni chat", icon=":material/more_horiz:", use_container_width=True):
            if st.session_state.get("rag_controls_for") != chat["id"]:
                st.session_state["rag_rename_input"] = chat["title"]
                st.session_state["rag_delete_confirm"] = False
                st.session_state["rag_controls_for"] = chat["id"]
            st.text_input("Nome conversazione", key="rag_rename_input", max_chars=80)
            st.button("Rinomina", key="rag_rename", on_click=_rename_current)
            confirmed = st.checkbox("Confermo di eliminare questa chat", key="rag_delete_confirm")
            st.button("Elimina chat", key="rag_delete", disabled=not confirmed,
                      on_click=safe_action, args=(sessions.delete, chat["id"], backend))
            with st.expander("Elimina tutte le conversazioni"):
                confirmed_all = st.checkbox("Confermo l'eliminazione di tutta la cronologia",
                                            key="rag_delete_all_confirm")
                st.button("Elimina tutta la cronologia", key="rag_delete_all",
                          disabled=not confirmed_all,
                          on_click=safe_action, args=(sessions.delete_all, backend))

        failed_saves = [
            turn for item in st.session_state.get("rag_chats", {}).values()
            if item.get("saved")
            for turn in item.get("turns", []) if turn.get("save_error")
        ]
        if failed_saves and backend:
            st.warning("Alcuni messaggi non sono stati salvati.")
            if st.button("Riprova salvataggio", key="rag_retry_all"):
                report = sessions.retry_unsaved()
                st.session_state["rag_notice"] = (
                    "Messaggi salvati." if not report["remaining"] else
                    "Alcuni messaggi devono ancora essere salvati."
                )
                st.rerun()
        notice = st.session_state.pop("rag_notice", None)
        if notice:
            st.toast(notice)
        error = st.session_state.pop("rag_navigation_error", None)
        if error:
            st.error(error)
    return chat
