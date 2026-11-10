"""Presentazione editoriale e homepage: sole letture locali, nessuna generazione."""

import html
import json
import re
import sqlite3
from collections import defaultdict, deque
from datetime import date

import streamlit as st

from edicola.archive_ui import edition_metadata
from edicola.editorial_selection import headline_priority, read_catalog
from edicola.pdf_viewer import source_button
from edicola.personalization import recommend
from edicola.profiles import load_profile, save_passage
from edicola import identity
from edicola.design import section_intro, empty_state
from edicola.editorial_components import render_highlights

from edicola.product_navigation import SECTIONS, cancel_navigation_action, canonical_section
INTERESTS = ["Ambiente", "Cultura", "Economia", "Politica", "Salute", "Scuola", "Sport", "Tecnologia", "Trasporti"]


def navigate(section):
    section = canonical_section(section)
    if section in SECTIONS:
        cancel_navigation_action()
        st.session_state["nav_section"] = section


def authenticated():
    return identity.native_logged_in() if identity.local_demo() else identity.current_identity() is not None


def logout():
    identity.logout()


def account_controls():
    if not identity.local_demo():
        identity.login_controls()
        return
    logged_in = authenticated()
    st.caption("Sessione autenticata. Il profilo del prototipo resta demo e condiviso." if logged_in else
               "Stai navigando come ospite. Il profilo disponibile è dimostrativo e condiviso.")
    st.button("Logout", key="account_logout", disabled=not logged_in, on_click=logout,
              help="Esci dalla sessione autenticata." if logged_in else "Nessuna sessione autenticata da chiudere.")


def excerpt(text, limit):
    """Sottostringa letterale, senza riscrivere o inventare un titolo d'articolo."""
    text = text.strip()
    if len(text) <= limit:
        return text
    end = text.rfind(" ", 0, limit)
    return text[:end if end > 0 else limit].rstrip() + "…"


def readable(text):
    """Testo leggibile senza rendere attivi HTML, immagini o link del documento."""
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", html.escape(html.unescape(text), quote=False))


def passage_card(chunk, *, context, editions, key, reason=None, root=None, profile=None, store=None):
    info = editions.get(chunk.metadata["filename"], {})
    with st.container(border=True, width=320):
        st.caption(info.get("title", "Dall’archivio") + " · " + info.get("date", "Data non disponibile"))
        # Le virgolette indicano un estratto, non un titolo ricostruito dall'app.
        st.markdown("**Una lettura da scoprire**")
        st.markdown(readable("«" + excerpt(chunk.text, 230) + "»"))
        st.caption(f"Pagina {chunk.metadata['page']} · Estratto originale")
        if reason:
            st.caption(reason)
        source_button(chunk.metadata["filename"], chunk.metadata["page"], context=context,
                      chunk_id=chunk.id, key=f"{key}_pdf")
        if root is not None and profile is not None:
            saved = chunk.id in profile.saved
            if st.button("Salvato" if saved else "Salva lettura", key=f"{key}_save", disabled=saved):
                try:
                    if store is not None:
                        store.assert_owner(profile.user_id)
                        store.save_passage(chunk)
                        st.session_state.pop("account_export", None)
                        st.session_state["account_notice"] = "Lettura salvata nel tuo account."
                    elif identity.local_demo():
                        save_passage(root, profile.user_id, chunk)
                        st.session_state["personal_notice"] = "Lettura salvata. La ritrovi nel profilo demo."
                    else:
                        raise RuntimeError("Profilo personale non disponibile.")
                    st.rerun()
                except (OSError, ValueError, RuntimeError, sqlite3.Error):
                    st.error("Non è stato possibile salvare la lettura. Riprova tra poco.")
        with st.expander("Leggi il passaggio originale"):
            st.text(info.get("title", "Documento dell’archivio") + f" · pagina {chunk.metadata['page']}")
            st.text(chunk.text)
            st.caption("Il passaggio può comprendere parti di più notizie, secondo l’impaginazione del quotidiano.")


def home_selection(catalog, limit=4):
    pools = defaultdict(deque)
    for chunk in sorted(catalog.chunks, key=lambda c: (-headline_priority(c), c.metadata["position"], c.id)):
        pools[chunk.metadata["filename"]].append(chunk)
    selected = []
    while pools and len(selected) < limit:
        for name in list(pools):
            while pools[name]:
                candidate = pools[name].popleft()
                if not any(candidate.metadata["filename"] == previous.metadata["filename"]
                           and " ".join(candidate.text.split()) == " ".join(previous.text.split()) for previous in selected):
                    selected.append(candidate)
                    break
            if not pools[name]:
                del pools[name]
            if len(selected) == limit:
                break
    return selected


def recent_editions(context, limit=3):
    try:
        raw = json.loads((context.root / "data/editions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    def published(document):
        try:
            return date.fromisoformat(raw[document.filename]["date"])
        except (KeyError, TypeError, ValueError):
            return date.min
    return sorted(context.documents, key=published, reverse=True)[:limit]


def render_home(root, context):
    identity.synchronize_identity()
    metadata = edition_metadata(root, context.documents)
    try:
        catalog = read_catalog(root)
    except Exception:
        st.info("Le letture selezionate saranno disponibili quando l’archivio sarà pronto.")
        return
    from edicola.press_review_ui import render_press_review
    render_press_review(catalog, context, metadata)

def render_for_you(root, context):
    """Letture consigliate accessibili dalla card Per te, senza invii AI."""
    identity.synchronize_identity()
    section_intro("Per te", "Le notizie più vicine agli argomenti che segui.", "La tua edicola")
    if not authenticated():
        st.info("Accedi con Google dal menu Profilo per consultare le tue letture consigliate."
                if not identity.local_demo() else
                "Per vedere le letture consigliate, accedi e imposta i tuoi interessi.")
        return
    try:
        store = None
        if identity.local_demo():
            profile = load_profile(root)
        else:
            from edicola.account_ui import personal_context
            store, profile = personal_context()
        if not profile.interests:
            st.info("Scegli gli argomenti che ti interessano nel Profilo per personalizzare questa sezione.")
            return
        catalog = read_catalog(root)
        items = recommend(catalog, profile)
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        st.info("Le letture consigliate non sono disponibili in questo momento.")
        return
    if catalog.coverage.get("partial"):
        st.caption("Le proposte si basano sulle edizioni attualmente disponibili.")
    if not items:
        st.info("Non ci sono ancora letture pertinenti agli argomenti scelti.")
        return
    metadata = edition_metadata(root, context.documents)
    with st.container(horizontal=True, gap="medium"):
        for index, item in enumerate(items):
            passage_card(item.chunk, context=context, editions=metadata, key=f"for_you_{index}",
                         root=root, profile=profile, store=store)
