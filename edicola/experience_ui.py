"""Presentazione editoriale e homepage: sole letture locali, nessuna generazione."""

import html
import json
import re
import sqlite3
from collections import defaultdict, deque
from datetime import date

import streamlit as st

from edicola.archive_ui import edition_metadata, edition_filter, render_gallery
from edicola.editorial_selection import headline_priority, near_duplicate, read_catalog
from edicola.pdf_viewer import source_button
from edicola.personalization import recommend
from edicola.profiles import load_profile, save_passage
from edicola import identity
from edicola.design import section_intro, empty_state
from edicola.editorial_components import render_products, render_highlights

from edicola.product_navigation import SECTIONS, cancel_navigation_action
INTERESTS = ["Ambiente", "Cultura", "Economia", "Politica", "Salute", "Scuola", "Sport", "Tecnologia", "Trasporti"]


def navigate(section):
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
            st.text(chunk.metadata["filename"] + f" — pagina {chunk.metadata['page']}")
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
                if not any(near_duplicate(candidate.text, previous.text) for previous in selected):
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
    render_products()
    metadata = edition_metadata(root, context.documents)
    if context.documents:
        ordered = recent_editions(context, limit=len(context.documents))
        visible = edition_filter(ordered, metadata, key="home_edition_date")
        render_gallery(context, metadata, documents=visible, title="Quotidiani in primo piano", key="home_gallery")
    else:
        empty_state("La tua edicola è ancora vuota", "Le copertine appariranno qui quando saranno disponibili edizioni nell’archivio.")
    section_intro("In evidenza", "Estratti dalle edizioni disponibili, senza aggiornamenti in tempo reale.", "Dalle fonti originali")
    st.caption("Estratti originali, alternati tra le edizioni disponibili. Nessuna notizia aggiunta o riscritta.")
    try:
        catalog = read_catalog(root)
    except Exception:
        st.info("Le letture selezionate saranno disponibili quando l’archivio sarà pronto.")
        return
    if catalog.coverage.get("partial"):
        st.caption("La selezione copre soltanto la parte dell’archivio attualmente disponibile alla ricerca.")
    selected = home_selection(catalog)
    if not selected:
        empty_state("Le letture arriveranno qui", "Non ci sono passaggi indicizzati per questa selezione. Puoi intanto sfogliare le edizioni originali.")
    if selected:
        render_highlights(selected, metadata=metadata, context=context, shorten=excerpt)
    if authenticated():
        st.subheader("Consigliati per te")
        try:
            store = None
            if identity.local_demo():
                st.caption("Sviluppo locale · preferenze del profilo demo condiviso, senza tracciamento.")
                profile = load_profile(root)
            else:
                from edicola.account_ui import personal_context
                st.caption("Letture selezionate per le tue preferenze personali, senza tracciamento implicito.")
                store, profile = personal_context()
            items = recommend(catalog, profile, limit=3)
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            st.info("Le preferenze non sono disponibili in questo momento.")
            return
        if not items:
            st.info("Scegli i tuoi interessi nel profilo per trovare letture pertinenti tra le fonti disponibili.")
        with st.container(horizontal=True, gap="medium"):
            for index, item in enumerate(items):
                passage_card(item.chunk, context=context, editions=metadata, key=f"home_personal_{index}",
                             reason=item.reason, root=root, profile=profile, store=store)
    else:
        st.caption("Stai esplorando l’edizione per tutti. Accedi con Google per salvare le tue preferenze personali." if not identity.local_demo() else
                   "Sviluppo locale: puoi provare le preferenze demo condivise; non è un account personale.")
