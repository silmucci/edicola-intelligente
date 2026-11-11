"""Presentazione editoriale e homepage: sole letture locali, nessuna generazione."""

import html
import re
import sqlite3
from collections import defaultdict, deque

import streamlit as st

from edicola.archive_ui import edition_metadata, latest_first
from edicola.editorial_selection import headline_priority, read_catalog
from edicola.pdf_viewer import source_button
from edicola.for_you import select_feed
from edicola.profiles import load_profile, save_passage
from edicola import identity
from edicola.design import section_intro
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


def save_reading_button(chunk, *, key, root=None, profile=None, store=None):
    """Salvataggio condiviso dal feed e dalle vecchie schede di lettura."""
    if root is None or profile is None:
        return
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


def passage_card(chunk, *, context, editions, key, reason=None, root=None, profile=None, store=None):
    """Scheda legacy usata anche da altre viste: mantiene azioni e riferimenti."""
    info = editions.get(chunk.metadata["filename"], {})
    with st.container(border=True, width=320):
        st.caption(info.get("title", "Dall’archivio") + " · " + info.get("date", "Data non disponibile"))
        st.markdown("**Una lettura da scoprire**")
        st.markdown(readable("«" + excerpt(chunk.text, 230) + "»"))
        source_button(chunk.metadata["filename"], chunk.metadata["page"], context=context,
                      chunk_id=chunk.id, key=f"{key}_pdf")
        save_reading_button(chunk, key=key, root=root, profile=profile, store=store)


def home_selection(catalog, limit=4):
    pools = defaultdict(deque)
    for chunk in sorted(catalog.chunks, key=lambda c: (-headline_priority(c), c.metadata["position"], c.id)):
        pools[chunk.metadata["filename"]].append(chunk)
    selected = []
    seen_text = defaultdict(set)
    while pools and len(selected) < limit:
        for name in list(pools):
            while pools[name]:
                candidate = pools[name].popleft()
                normalized = " ".join(candidate.text.split())
                if normalized not in seen_text[name]:
                    seen_text[name].add(normalized)
                    selected.append(candidate)
                    break
            if not pools[name]:
                del pools[name]
            if len(selected) == limit:
                break
    return selected


def recent_editions(context, limit=3):
    """Condivide l'ordinamento dell'archivio senza duplicare la logica delle date."""
    return latest_first(context.root, context.documents)[:limit]


def render_home(root, context):
    """Compatibilità: vecchi invii alla Rassegna aprono la vista completa."""
    st.session_state["for_you_mode"] = "Tutte le notizie"
    render_for_you(root, context)

def render_for_you(root, context):
    """Feed compatto: titoli verificati, preferenze e fonti originali."""
    identity.synchronize_identity()
    section_intro("Per te", "Scopri le notizie, segui i tuoi interessi e consulta le fonti.", "La tua edicola")
    modes = ("Consigliate", "Tutte le notizie")
    if st.session_state.get("for_you_mode") not in (*modes, None):
        st.session_state.pop("for_you_mode", None)
    mode = st.segmented_control("Quali notizie vuoi leggere?", modes,
                                default="Consigliate", key="for_you_mode",
                                on_change=cancel_navigation_action) or "Consigliate"

    store, profile = None, None
    if mode == "Consigliate" and authenticated():
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
        if mode == "Tutte le notizie":
            from edicola.press_review_ui import render_press_review
            st.caption("Consulta tutte le edizioni disponibili oppure cerca un argomento.")
            render_press_review(catalog, context, edition_metadata(root, context.documents))
            return
        interests = profile.interests if profile and profile.interests else []
        st.subheader("Notizie per i tuoi interessi" if interests else "Notizie da esplorare")
        if not interests:
            st.caption("Scegli i tuoi interessi nel Profilo per personalizzare questa selezione.")
        selected_topic = ""
        if interests:
            choice = st.selectbox("Argomento", ["Tutti gli interessi", *interests],
                                  key="for_you_topic", width=270)
            selected_topic = "" if choice == "Tutti gli interessi" else choice
        if st.session_state.get("for_you_previous_topic") != selected_topic:
            st.session_state["for_you_previous_topic"] = selected_topic
            st.session_state["for_you_more"] = False

        entries = select_feed(catalog, profile, topic=selected_topic, limit=17)
        if entries:
            metadata = edition_metadata(root, context.documents)
            visible = entries if st.session_state.get("for_you_more") else entries[:8]
            for index, entry in enumerate(visible):
                chunk = entry.chunk
                info = metadata.get(chunk.metadata["filename"], {})
                details = [info.get("title") or "Dall’archivio",
                           info.get("date") or "Data non disponibile",
                           f"pagina {chunk.metadata['page']}"]
                if entry.topics:
                    details.append(", ".join(entry.topics[:2]))
                if not entry.verified_title:
                    details.append("Estratto originale")
                with st.container(border=True):
                    st.caption(" · ".join(details))
                    st.markdown("**" + readable(entry.title) + "**")
                    if entry.preview:
                        st.markdown(readable(entry.preview))
                    with st.container(horizontal=True, gap="small"):
                        source_button(chunk.metadata["filename"], chunk.metadata["page"],
                                      context=context, chunk_id=chunk.id,
                                      key=f"for_you_{index}_pdf", label="Leggi nel PDF")
                        save_reading_button(chunk, key=f"for_you_{index}",
                                            root=root if profile else None,
                                            profile=profile, store=store)
            if len(entries) > 8 and not st.session_state.get("for_you_more"):
                if st.button("Mostra altre notizie", key="for_you_show_more"):
                    st.session_state["for_you_more"] = True
                    st.rerun()
        else:
            st.info("Non ci sono notizie per questa selezione. Prova un altro interesse oppure scegli Tutte le notizie.")
    else:
        st.info("Le letture non sono disponibili in questo momento.")
