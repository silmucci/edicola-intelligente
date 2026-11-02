"""Sezioni di lettura; i moduli di ricerca e generazione rimangono invariati."""

import html
import re
from uuid import uuid4

import streamlit as st

from edicola import editorial, knowledge, rag
from edicola.knowledge_ui import render_knowledge
from edicola.pdf_viewer import source_button
from edicola.experience_ui import readable
from edicola.archive_ui import diagnostics_enabled
from edicola.consent_ui import authorize_action
from edicola.consent import perform
from edicola.api_guard import PermissionDenied
from edicola.personal_store import PersonalStoreError
from edicola.design import section_intro, friendly_error, reading_title
from edicola import consent
from edicola.identity import synchronize_identity
from edicola.rag_context import source_editions
from edicola import chat_sessions
from edicola.chat_navigation import render_navigation
from edicola.chat_sources import render_sources, citation_text, render_context_limit
from edicola.chat_data import turn_context


def chat_markdown(text, *, cited=(), anchor=None):
    """Entità legacy decodificate prima dell'escaping; mai HTML attivo o link del testo."""
    for _ in range(2):
        text = html.unescape(text)
    # quote=False evita &#x27;, il cui # veniva poi escapato come Markdown.
    text = html.escape(text, quote=False)
    text = re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", text)
    if anchor:
        for source_id in cited:
            if re.fullmatch(r"S[1-9]\d*", source_id):
                literal = "\\[" + source_id + "\\]"
                text = text.replace(literal, f"[{source_id}](#{anchor})")
    return text


def _queue_chat_question():
    question = st.session_state.get("rag_input")
    if not isinstance(question, str) or not question.strip() or st.session_state.get("rag_pending"):
        return
    try:
        chat = chat_sessions.prepare_send(question.strip())
    except PersonalStoreError:
        st.session_state["rag_navigation_error"] = "Non possiamo preparare o salvare questa chat. Nessuna richiesta AI è stata inviata."
        return
    turn_id = uuid4().hex
    history = chat["turns"]
    context = turn_context(history)
    history.append({"id": turn_id, "question": question.strip(), "result": None})
    st.session_state["rag_history"] = history
    st.session_state["rag_pending"] = {"id": turn_id, "question": question.strip(), "owner": consent.actor(),
                                       "chat_id": chat["id"], "context": context, "new": True}


def _finish_chat_turn(pending, *, result=None, error=None):
    if st.session_state.get("rag_pending", {}).get("id") != pending["id"]:
        return False  # Non consumare una richiesta più recente o di un'altra identità.
    owned = consent.actor() == pending["owner"]
    if owned:
        for turn in st.session_state.get("rag_history", []):
            if turn.get("id") == pending["id"]:
                turn["result"], turn["error"] = result, error
                chat = st.session_state.get("rag_chats", {}).get(pending.get("chat_id"))
                if chat:
                    chat_sessions.save_completed(chat, turn)
                break
    st.session_state.pop("rag_pending", None)
    return owned


def _render_chat_turn(turn, index, last, root, context):
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(chat_markdown(turn["question"]), unsafe_allow_html=False)
    result = turn.get("result")
    if result is None:
        if turn.get("error"):
            with st.chat_message("assistant", avatar=":material/auto_awesome:"):
                st.error(turn["error"])
                _render_save_status(turn)
        return
    with st.chat_message("assistant", avatar=":material/auto_awesome:"):
        if getattr(result, "temporal_notice", ""):
            st.info(result.temporal_notice)
        st.markdown(chat_markdown(citation_text(result.answer, result.used_source_ids)), unsafe_allow_html=False)
        render_sources(result, index=index, last=last, root=root, context=context, formatter=chat_markdown)
        _render_save_status(turn)
        if last and result.sufficient:
            from edicola.editorial_handoff import render_handoff
            render_handoff(turn["question"])


def _render_save_status(turn):
    if turn.get("save_error"):
        st.warning("Questo scambio è disponibile soltanto in questa sessione: il salvataggio non è riuscito.")
        if st.button("Riprova salvataggio", key=f"rag_retry_save_{turn['id']}"):
            chat_sessions.save_completed(chat_sessions.active(), turn)
            st.rerun()


def render_chat(root, context):
    synchronize_identity()
    section_intro("Chat AI", "Riprendi un argomento, approfondisci le notizie, ritrova le fonti. Nessuna ricerca web.")
    try:
        from edicola.editorial_selection import read_catalog
        if read_catalog(root).coverage.get("partial"):
            st.caption("Le risposte coprono solo una parte dell’archivio. Puoi consultare tutte le edizioni nella sezione In edicola.")
    except (OSError, ValueError, RuntimeError):
        pass
    try:
        chat = render_navigation()
    except PersonalStoreError:
        st.error("Le conversazioni del tuo account non sono disponibili in questo momento. Riprova più tardi.")
        st.chat_input("Chat momentaneamente non disponibile", key="rag_input", disabled=True)
        return
    pending = st.session_state.get("rag_pending")
    if pending and pending.get("running"):
        # Un rerun ha interrotto il flusso precedente: non ripetere la richiesta API.
        _finish_chat_turn(pending, error="La richiesta è stata interrotta. Puoi inviarla nuovamente.")
    history = st.session_state.get("rag_history", [])
    thread = st.container(height=420, border=False, autoscroll=True, key="rag_thread")
    with thread:
        if not history:
            st.caption("Da dove vuoi iniziare? Chiedi un fatto o un approfondimento sulle edizioni disponibili.")
        for index, turn in enumerate(history):
            _render_chat_turn(turn, index, index == len(history) - 1, root, context)
    st.caption("Cronologia account · gli scambi completati vengono salvati; eventuali errori sono segnalati." if chat["saved"] else "Chat temporanea · disponibile soltanto in questa sessione.")
    st.chat_input("Chiedi ai quotidiani…", key="rag_input", max_chars=2000,
                  on_submit=_queue_chat_question, disabled=bool(st.session_state.get("rag_pending")),
                  submit_mode="disable", accept_file=False, accept_audio=False)
    pending = st.session_state.get("rag_pending")
    if not pending:
        return
    submitted = pending.pop("new", False)
    payload = [pending["chat_id"], pending["id"], pending["question"], pending["context"]]
    if authorize_action("text", "chat", submitted, payload):
        pending["running"] = True
        st.session_state.pop("rag_result", None)
        try:
            with thread, st.chat_message("assistant", avatar=":material/auto_awesome:"):
                with st.spinner("Leggo le fonti…"):
                    options = {"conversation": pending["context"]} if pending["context"] else {}
                    result = perform("text", rag.ask_question, pending["question"], authorize_external=True, root=root, **options)
            if _finish_chat_turn(pending, result=result):
                st.session_state["rag_result"] = result
                st.session_state["rag_question_answered"] = pending["question"]
        except (rag.RagError, PermissionDenied, PersonalStoreError) as exc:
            _finish_chat_turn(pending, error=friendly_error(exc))
        st.rerun()
    elif st.session_state.get("consent_pending", {}).get("action") != "chat":
        _finish_chat_turn(pending, error="La richiesta non è stata inviata: autorizzazione non concessa o non disponibile.")
        st.rerun()


def render_editorial(root, context):
    """Un solo flusso di generazione; lettura compatibile dei prodotti precedenti."""
    from dataclasses import asdict
    from edicola.press_review_ui import review_controls
    from edicola.product_navigation import cancel_navigation_action
    from edicola.podcast_text import list_products, PodcastError
    section_intro("Briefing", "Scegli un tema e le edizioni: ritrova le notizie con le loro fonti.")
    results = st.session_state.setdefault("editorial_results", {})
    previous = st.session_state.get("editorial_result")
    if previous is not None:
        results[previous.kind] = previous
    _, review = review_controls(root)
    submitted = st.button("Genera briefing", key="briefing_submit", type="primary")
    payload = ["", asdict(review)]
    if authorize_action("text", "briefing", submitted, payload):
        st.session_state.pop("editorial_result", None)
        st.session_state.pop("editorial_saved_product", None)
        results.pop("briefing", None)
        try:
            with st.spinner("Leggo le fonti e preparo il briefing…"):
                product = perform("text", editorial.generate_product, "briefing", "",
                                  authorize_external=True, root=root, selection=review)
                st.session_state["editorial_result"] = product
                results["briefing"] = product
        except (editorial.EditorialError, PermissionDenied, PersonalStoreError) as exc:
            st.error(friendly_error(exc))
    # Lettura soltanto: nessuna copia, migrazione o riscrittura della cache.
    available = {}
    try:
        for saved in list_products(root):
            available[saved.key] = (saved.result, saved.created_at)
    except PodcastError:
        st.caption("Le letture salvate non sono disponibili in questo momento.")
    if "dossier" in results:
        available["session:dossier"] = (results["dossier"], "Questa sessione")
    selected = None
    if available:
        if st.session_state.get("editorial_saved_product") not in available:
            st.session_state.pop("editorial_saved_product", None)
        selected = st.selectbox("Letture già disponibili", [None] + list(available), key="editorial_saved_product",
            format_func=lambda key: (citation_text(reading_title(available[key][0]), available[key][0].used_source_ids)
                                     + " · " + available[key][1]) if key else "Briefing corrente",
            on_change=cancel_navigation_action)
    product = available[selected][0] if selected else results.get("briefing")
    if product is None:
        st.info("Scegli le fonti e premi Genera briefing per iniziare.")
        return
    if not selected:
        expected, actual = asdict(review), product.coverage.get("selection", {})
        if (expected.get("keyword", "") != actual.get("keyword", "")
                or list(expected.get("filenames", ())) != actual.get("files", [])
                or any(expected.get(key, "") != actual.get(key, "") for key in ("scope", "date_from", "date_to"))
                or expected.get("latest", False) != actual.get("latest", False)):
            st.caption("Questo briefing si riferisce alla selezione precedente. Generane uno nuovo per applicare i filtri attuali.")
    render_editorial_product(product, root, context)


def render_editorial_product(product, root, context):
    from edicola.corpus_cache import render_history_notice
    from edicola.design import product_notice
    coverage = product.coverage
    render_history_notice(coverage, context)
    render_context_limit(coverage)
    st.subheader(readable(citation_text(reading_title(product), product.used_source_ids)))
    if product.message:
        st.info(product_notice(product))
    for section in product.sections:
        with st.container(border=True):
            st.markdown("### " + readable(citation_text(section["heading"], product.used_source_ids)))
            st.markdown(readable(citation_text(section["text"], product.used_source_ids)))
    render_sources(product, index=0, last=True, root=root, context=context, formatter=chat_markdown, namespace="editorial")
    if diagnostics_enabled(root):
        with st.expander("Diagnostica editoriale · sviluppo"):
            st.json(product.diagnostics)
            st.json(coverage)


def render_visuals(root, context, *, kind=None):
    standalone = kind is None
    if standalone:
        kind = st.segmented_control("Come vuoi esplorare?", ["Timeline", "Mappa"], default="Timeline", key="knowledge_kind") or "Timeline"
    section_intro("Timeline" if kind == "Timeline" else "Mappe concettuali",
                  "Segui gli eventi e gli sviluppi nelle fonti." if kind == "Timeline" else "Esplora i concetti e i loro collegamenti.")
    result_kind = "timeline" if kind == "Timeline" else "map"
    results = st.session_state.setdefault("knowledge_results", {})
    previous = st.session_state.get("knowledge_result")
    if previous is not None:
        results[previous.kind] = previous
    versions = st.session_state.setdefault("knowledge_result_versions", {})
    strategies = {"map": (knowledge.MAP_VERSION, knowledge.RELEVANCE_VERSION),
                  "timeline": (knowledge.TIMELINE_CONTENT_VERSION, knowledge.TIMELINE_VERSION, knowledge.RELEVANCE_VERSION)}
    topic_key = "knowledge_topic" if standalone else "knowledge_topic_" + result_kind
    topic = st.text_input("Quale tema vuoi esplorare?", max_chars=500, key=topic_key, placeholder="Un argomento, un luogo, una questione")
    submitted = st.button("Genera timeline" if kind == "Timeline" else "Genera mappa concettuale",
                          key="timeline_submit" if kind == "Timeline" else "map_submit", type="primary")
    if submitted and not topic.strip():
        st.warning("Scegli un argomento da esplorare.")
    if topic.strip() and authorize_action("text", "visual_" + kind, submitted, topic):
        try:
            with st.spinner("Preparo la timeline…" if kind == "Timeline" else "Preparo la mappa…"):
                st.session_state["knowledge_result"] = perform("text", knowledge.generate_knowledge,
                    "timeline" if kind == "Timeline" else "map", topic, authorize_external=True, root=root)
                results[result_kind] = st.session_state["knowledge_result"]
                versions[result_kind] = strategies[result_kind]
        except (knowledge.KnowledgeError, PermissionDenied, PersonalStoreError) as exc:
            st.error(friendly_error(exc))
    if result_kind in results:
        result = results[result_kind]
        if versions.get(result_kind) != strategies[result_kind]:
            st.caption("Lettura precedente: un nuovo invio applicherà gli aggiornamenti del prodotto.")
        if " ".join(topic.split()) != result.topic:
            st.caption("Risultato dell’argomento precedente: modifica la richiesta e avvia la generazione per aggiornarlo.")
        render_knowledge(result, archive=context)
    else:
        st.info("Scegli un tema per iniziare.")
