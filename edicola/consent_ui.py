"""Dialogo al primo invio e centro privacy, con ripresa di una sola azione."""

import hashlib
import json

import streamlit as st

from edicola import consent
from edicola.api_guard import PermissionDenied
from edicola.personal_store import PersonalStoreError


def cancel_pending():
    st.session_state.pop("consent_pending", None)


@st.dialog("Prima di continuare", on_dismiss=cancel_pending)
def consent_dialog(purpose):
    version, title, description = consent.PURPOSES[purpose]
    st.subheader(title)
    st.write(description)
    st.caption("Il servizio esterno è Google Gemini. Evita dati riservati nelle richieste. "
               "Puoi rifiutare e continuare a consultare l’Archivio, oppure revocare la scelta in Privacy e autorizzazioni.")
    st.caption("La scelta viene salvata nel tuo account." if consent.actor() != "guest" else
               "Come ospite, la scelta dura soltanto per questa sessione.")
    st.caption("L’autorizzazione non avvia attività in background: ogni generazione richiede sempre il tuo invio.")
    with st.container(horizontal=True):
        accept = st.button("Autorizza e continua", key="consent_accept", type="primary")
        refuse = st.button("Non ora", key="consent_refuse")
    if accept or refuse:
        try:
            pending = st.session_state.get("consent_pending", {})
            if (pending.get("owner") != consent.actor() or pending.get("version") != version
                    or pending.get("purpose") != purpose):
                cancel_pending()
                st.rerun()
            consent.choose(purpose, accept)
            if not accept or not pending.get("action"):
                cancel_pending()
            else:
                st.session_state["consent_pending"] = {**pending, "confirmed": True}
            st.rerun()
        except PersonalStoreError:
            cancel_pending()
            st.error("Non possiamo salvare l’autorizzazione in questo momento. Nessun contenuto è stato inviato; riprova più tardi.")


def authorize_action(purpose, action, submitted, payload=None):
    """L'accettazione riprende l'invio originale, mai un'altra bozza/identità."""
    version = consent.PURPOSES[purpose][0]
    token = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    signature = {"purpose": purpose, "action": action, "owner": consent.actor(), "version": version, "token": token}
    pending = st.session_state.get("consent_pending", {})
    matching = all(pending.get(k) == v for k, v in signature.items())
    if not matching and pending.get("action") == action and not submitted:
        cancel_pending()
    if not submitted and not matching:
        return False
    if submitted:
        st.session_state["consent_pending"] = signature
    try:
        if consent.allowed(purpose):
            cancel_pending()  # Consuma PRIMA dell'operazione: nessun retry al rerun.
            return True
        st.info("Scegli come usare l’AI nella finestra di autorizzazione.")
        consent_dialog(purpose)
    except PersonalStoreError:
        cancel_pending()
        st.error("Le autorizzazioni del tuo account non sono disponibili. Riprova più tardi; nessun contenuto è stato inviato.")
    return False


def privacy_controls(key="profile_privacy"):
    with st.expander("Privacy e autorizzazioni"):
        st.caption("Le finalità sono indipendenti. Revocare blocca i nuovi invii, ma non ritira quelli già ricevuti da Gemini.")
        for purpose, (_, title, description) in consent.PURPOSES.items():
            st.markdown("**" + title + "**")
            st.caption(description)
            try:
                value = consent.decision(purpose)
                st.caption("Autorizzato" if value is True else "Non autorizzato" if value is False else "Scelta non ancora espressa")
                if value is True:
                    if st.button("Revoca", key=f"{key}_{purpose}_revoke"):
                        consent.choose(purpose, False)
                        cancel_pending()
                        st.session_state.pop("account_export", None)
                        st.rerun()
                elif st.button("Rivedi autorizzazione", key=f"{key}_{purpose}_review"):
                    # Non è una richiesta di generazione: dopo la scelta nessuna azione riparte.
                    st.session_state["consent_pending"] = {"owner": consent.actor(), "version": consent.PURPOSES[purpose][0], "purpose": purpose, "review": True}
                pending = st.session_state.get("consent_pending", {})
                if pending.get("review") and pending.get("purpose") == purpose and pending.get("owner") == consent.actor():
                    consent_dialog(purpose)
            except PersonalStoreError:
                st.info("Impostazioni AI non disponibili. Il gestore deve completare la configurazione; gli invii restano bloccati.")
