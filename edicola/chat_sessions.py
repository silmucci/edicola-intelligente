"""Stato privato della chat: nessuna cache globale e nessuna chiamata Gemini."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st

from edicola import consent
from edicola.chat_data import MAX_LOCAL_CHATS, MAX_TURNS, title_from_question
from edicola.chat_store import ChatStore
from edicola.personal_store import PersonalStoreError


def store():
    person = consent.current_person()
    return ChatStore(person) if person else None


def now():
    return datetime.now(timezone.utc).isoformat()


def active():
    chats = st.session_state.setdefault("rag_chats", {})
    cid = st.session_state.get("rag_active_id")
    if cid not in chats:
        chat = new_local()
    else:
        chat = chats[cid]
    st.session_state["rag_history"] = chat["turns"]
    return chat


def new_local(*, turns=None, title="Nuova chat", draft=True):
    chats = st.session_state.setdefault("rag_chats", {})
    if sum(not c["saved"] for c in chats.values()) >= MAX_LOCAL_CHATS:
        raise PersonalStoreError("Hai molte chat temporanee aperte. Eliminane una prima di continuare.")
    stamp = now()
    chat = dict(id=str(uuid4()), title=title, created_at=stamp, updated_at=stamp,
                turns=deepcopy(turns or []), saved=False, draft=draft)
    chats[chat["id"]] = chat
    st.session_state["rag_active_id"] = chat["id"]
    st.session_state["rag_history"] = chat["turns"]
    return chat


def cancel_request():
    pending = st.session_state.pop("rag_pending", None)
    if pending and pending.get("owner") == consent.actor():
        for chat in st.session_state.get("rag_chats", {}).values():
            for turn in chat["turns"]:
                if turn["id"] == pending["id"] and turn.get("result") is None:
                    turn["error"] = "Richiesta annullata al cambio di conversazione."
                    save_completed(chat, turn)
    if st.session_state.get("consent_pending", {}).get("action") == "chat":
        st.session_state.pop("consent_pending", None)


def switch(chat_id, backend=None):
    cancel_request()
    chats = st.session_state.setdefault("rag_chats", {})
    # Anche per gli ID ricevuti dal widget è il DB, non il browser, a verificare l'owner.
    if chat_id not in chats:
        if backend is None:
            raise PersonalStoreError("Conversazione non disponibile.")
        loaded = backend.load_chat(chat_id)
        chats[chat_id] = loaded
    # Mantiene una sola chat salvata caricata; preserva soltanto salvataggi falliti.
    for cid in list(chats):
        if cid != chat_id and chats[cid]["saved"] and not any(t.get("save_error") for t in chats[cid]["turns"]):
            del chats[cid]
    st.session_state["rag_active_id"] = chat_id
    st.session_state["rag_history"] = chats[chat_id]["turns"]
    st.session_state.pop("rag_result", None)


def start_new(backend=None):
    cancel_request()
    if backend and backend.history_enabled():
        chat = backend.create_chat()
        st.session_state.pop("account_export", None)
        st.session_state.setdefault("rag_chats", {})[chat["id"]] = chat
        switch(chat["id"], backend)
    else:
        chat = new_local()
        switch(chat["id"], backend)


def prepare_send(question):
    chat = active()
    backend = store()
    enabled = backend.history_enabled() if backend else False
    if chat["saved"] and (not enabled or any(t.get("save_error") for t in chat["turns"])):
        # La parte già salvata resta intatta. Nessun messaggio aggiunto dopo la
        # disattivazione viene importato implicitamente riattivando l'opzione.
        chat = new_local(turns=chat["turns"], title=chat["title"], draft=False)
    if chat.get("draft") and not chat["turns"] and enabled:
        saved = backend.create_chat(title_from_question(question))
        st.session_state.pop("account_export", None)
        st.session_state["rag_chats"].pop(chat["id"], None)
        st.session_state["rag_chats"][saved["id"]] = saved
        switch(saved["id"], backend)
        chat = saved
    if len(chat["turns"]) >= MAX_TURNS:
        raise PersonalStoreError("Questa conversazione è completa. Avvia una nuova chat.")
    if not chat["turns"]:
        title = title_from_question(question)
        if chat["saved"] and chat["title"] == "Nuova chat":
            backend.rename_chat(chat["id"], title)
        if chat["title"] == "Nuova chat":
            chat["title"] = title
        chat["draft"] = False
    return chat


def save_completed(chat, turn):
    chat["updated_at"] = now()
    if not chat["saved"]:
        return
    try:
        backend = store()
        if backend is None:
            raise PersonalStoreError("Account non disponibile.")
        backend.append_turn(chat["id"], turn)
        turn.pop("save_error", None)
        st.session_state.pop("account_export", None)
    except (PersonalStoreError, ValueError):
        turn["save_error"] = True


def set_saving(enabled):
    backend = store()
    if backend is None:
        raise PersonalStoreError("Account non disponibile.")
    backend.set_history_enabled(enabled)
    st.session_state.pop("account_export", None)


def rename(chat_id, title, backend=None):
    title = ChatStore.checked_title(title)
    chat = st.session_state.get("rag_chats", {}).get(chat_id)
    if chat is None or chat["saved"]:
        if backend is None:
            raise PersonalStoreError("Conversazione non disponibile.")
        backend.rename_chat(chat_id, title)
        st.session_state.pop("account_export", None)
    if chat:
        chat["title"], chat["updated_at"] = title, now()


def delete(chat_id, backend=None):
    chat = st.session_state.get("rag_chats", {}).get(chat_id)
    if chat is None or chat["saved"]:
        if backend is None:
            raise PersonalStoreError("Conversazione non disponibile.")
        backend.delete_chat(chat_id)
    cancel_request()
    st.session_state.setdefault("rag_chats", {}).pop(chat_id, None)
    st.session_state.pop("account_export", None)
    if st.session_state.get("rag_active_id") == chat_id:
        st.session_state.pop("rag_active_id", None)


def delete_all(backend=None):
    if backend:
        backend.delete_history()
    cancel_request()
    for key in ("rag_chats", "rag_active_id", "rag_history", "rag_result", "account_export"):
        st.session_state.pop(key, None)
