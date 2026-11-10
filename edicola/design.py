"""Elementi editoriali nativi: tema locale, niente CDN o selettori DOM fragili."""

import html
import re
import streamlit as st

from edicola.design_tokens import page_css


def section_intro(title, description, label=None):
    # Tutte le variabili, incluse quelle future, restano testo escapato.
    eyebrow = f'<div class="eyebrow">{html.escape(label)}</div>' if label else ''
    st.html(f'<style>{page_css()}</style><section class="edi-section">{eyebrow}'
            f'<h2>{html.escape(title)}</h2><p>{html.escape(description)}</p></section>')


def empty_state(title, description):
    with st.container(border=True):
        st.text(title)
        st.caption(description)


def reading_title(product):
    """Etichetta cliente dei risultati storici, senza riscrivere i dati salvati."""
    if product.kind == "dossier":
        return re.sub(r"^\s*dossier(?:\s+tematico)?\b\s*[:–—-]?\s*", "Approfondimento: ", product.title, count=1, flags=re.I)
    return product.title


def friendly_error(error):
    text = str(error).lower()
    if "503" in text or "500" in text:
        return "Il servizio AI è momentaneamente occupato. Riprova tra poco."
    if "429" in text or "quota" in text:
        return "Il servizio AI ha raggiunto il limite di utilizzo. Riprova più tardi."
    if "autorizza" in text or "revocata" in text:
        return "Questa operazione richiede la tua autorizzazione. Puoi gestirla nel profilo."
    return "Non siamo riusciti a completare l’operazione. Riprova tra poco; le letture già disponibili restano consultabili."


def product_notice(product):
    """Messaggi per la lettura; cause tecniche conservate nei risultati originali."""
    status = product.diagnostics.get("status", "")
    if status in {"empty_index", "selection_empty", "model_abstention"} or not product.sources and not status:
        return "Non ci sono contenuti sufficienti per questa lettura tra le fonti disponibili."
    if status == "partial_validation" and product.sufficient:
        return ""
    if not product.sufficient:
        return "Non è stato possibile preparare questa lettura. Le edizioni originali restano consultabili."
    return "Questa lettura è disponibile solo in parte. Puoi approfondire nelle fonti originali."
