"""Aiuto per gli account personali non raggiungibili.

Il recupero richiede sempre un'azione esplicita: non degrada un account
autenticato a ospite silenziosamente e non considera salvati i dati in RAM.
"""

import streamlit as st

from edicola import identity


def offer_guest_access(*, key: str) -> None:
    """Permette di uscire volontariamente e usare le funzioni non personali.

    Non invia contenuti all'AI e non concede autorizzazioni in automatico.
    Le richieste dell'ospite mantengono il consueto consenso per sessione.
    """
    if not identity.native_logged_in():
        return
    st.caption(
        "Per usare Chat AI, briefing e podcast senza il salvataggio personale, "
        "puoi uscire dall'account. Le nuove conversazioni non saranno conservate "
        "dopo la sessione. Per salvarle serve ripristinare il database personale."
    )
    st.button("Continua senza account", key=key, on_click=identity.logout)
