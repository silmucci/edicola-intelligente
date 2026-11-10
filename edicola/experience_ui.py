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
    """Notizie personalizzate, letture salvate e briefing senza pannelli tecnici."""
    identity.synchronize_identity()
    section_intro("Per te", "Le notizie più vicine ai tuoi interessi.", "La tua edicola")

    store, profile = None, None
    if authenticated():
        try:
            if identity.local_demo():
                profile = load_profile(root)
            else:
                from edicola.account_ui import personal_context
                store, profile = personal_context()
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            st.info("Le tue preferenze non sono disponibili in questo momento.")

    try:
        catalog = read_catalog(root)
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        catalog = None

    if catalog and catalog.chunks:
        personalized = recommend(catalog, profile, limit=6) if profile and profile.interests else []
        selected = [item.chunk for item in personalized]
        used = {chunk.id for chunk in selected}
        # Completa le proposte con notizie di varie edizioni, senza
        # sostituire o nascondere quelle in linea con gli interessi.
        for chunk in home_selection(catalog, limit=8):
            if len(selected) >= 6:
                break
            if chunk.id not in used:
                selected.append(chunk)
                used.add(chunk.id)
        if personalized:
            st.subheader("Scelte per i tuoi interessi")
        else:
            st.subheader("Da scoprire")
            if not profile:
                st.caption("Accedi dal Profilo per ricevere consigli più vicini ai tuoi interessi.")
            elif not profile.interests:
                st.caption("Scegli i tuoi interessi nel Profilo per personalizzare le letture.")
        metadata = edition_metadata(root, context.documents)
        with st.container(horizontal=True, gap="medium"):
            for index, chunk in enumerate(selected):
                passage_card(chunk, context=context, editions=metadata, key=f"for_you_{index}",
                             root=root if profile else None, profile=profile, store=store)
    else:
        st.info("Le letture non sono disponibili in questo momento.")

    if profile is None:
        return
    if identity.local_demo():
        from edicola.personalization_ui import render_demo_readings
        render_demo_readings(root, context, profile, catalog)
    else:
        from edicola.account_ui import render_account_readings
        render_account_readings(root, context, store, profile, catalog)
