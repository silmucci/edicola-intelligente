"""Scelte versionate per finalità: PostgreSQL per account, RAM per ospiti."""

import streamlit as st

from edicola import identity
from edicola.api_guard import permission_scope
from edicola.personal_store import PostgresPersonalStore

# Incrementare solo la versione della finalità il cui trattamento cambia.
PURPOSES = {
    "text": ("text-v2", "Lettura e approfondimenti AI",
             "Gemini riceve la domanda o il tema, i passaggi selezionati dei quotidiani e i riferimenti PDF/pagina. "
             "Li usa per cercare e preparare risposte, dossier, briefing, timeline e mappe. "
             "La ricerca può inviare la domanda per crearne l’embedding. Nella chat inviamo anche un breve contesto dei messaggi precedenti della stessa conversazione, per comprendere le domande successive; le risposte si basano sempre su nuove fonti recuperate. "
             "I prodotti generali sono condivisi nell’app. Il salvataggio delle chat nel tuo account è una scelta distinta, disattivata inizialmente."),
    "personal_text": ("personal-text-v1", "Il mio briefing AI",
             "Gemini riceve i passaggi selezionati localmente in base ai tuoi interessi e il tempo di lettura. "
             "Non inviamo l’identità Google, il profilo, la raccolta dei salvati o lo storico. "
             "I passaggi possono rivelare indirettamente i tuoi interessi. Il briefing resta nel tuo account."),
    "audio": ("audio-v1", "Podcast e lettura audio",
             "Gemini TTS riceve il copione visualizzato e la voce scelta per creare l’audio. "
             "Non inviamo l’identità Google o il tuo profilo. Gli audio personali sono temporanei; "
             "i podcast creati dalla biblioteca generale sono condivisi nell’app."),
}


def actor():
    person = current_person()
    return person.owner_id if person else "guest"


def current_person():
    return None if identity.local_demo() else identity.current_identity()


def decision(purpose):
    version = PURPOSES[purpose][0]
    person = current_person()
    if person:
        return PostgresPersonalStore(person).get_consent(purpose, version)
    return st.session_state.get("consent_choices", {}).get((purpose, version))


def choose(purpose, granted):
    if type(granted) is not bool:
        raise ValueError("Scegli se autorizzare questa finalità.")
    version = PURPOSES[purpose][0]
    person = current_person()
    if person:
        PostgresPersonalStore(person).set_consent(purpose, version, granted)
    else:
        choices = dict(st.session_state.get("consent_choices", {}))
        choices[(purpose, version)] = granted
        st.session_state["consent_choices"] = choices


def allowed(purpose):
    return decision(purpose) is True


def perform(purpose, callback, *args, **kwargs):
    owner = actor()
    # Rilegge la decisione prima di OGNI chiamata SDK, anche fra embedding e risposta
    # e prima di ogni retry. Un altro dispositivo può revocare la scelta persistente.
    with permission_scope(lambda: actor() == owner and allowed(purpose), purpose):
        return callback(*args, **kwargs)
