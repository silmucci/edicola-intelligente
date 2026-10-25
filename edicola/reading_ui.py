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
from edicola.design import section_intro, friendly_error
from edicola import consent
from edicola.identity import synchronize_identity
from edicola.rag_context import source_editions
from edicola import chat_sessions
from edicola.chat_navigation import render_navigation
from edicola.chat_sources import render_sources
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
        st.markdown(chat_markdown(result.answer), unsafe_allow_html=False)
        render_sources(result, index=index, last=last, root=root, context=context, formatter=chat_markdown)
        _render_save_status(turn)


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
        chat = render_navigation()
    except PersonalStoreError:
        st.error("Le conversazioni del tuo account non sono disponibili. Riprova più tardi; il gestore deve verificare la configurazione della cronologia.")
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


def render_editorial(root, context, *, kind=None):
    if kind is None:  # Compatibilità delle viste richiamate separatamente.
        kind = st.segmented_control("Cosa vuoi leggere?", ["Briefing", "Dossier"], default="Briefing", key="editorial_kind") or "Briefing"
    section_intro(kind, "Una sintesi delle edizioni disponibili." if kind == "Briefing" else "Un percorso tra le fonti su un tema a tua scelta.", "Oltre il titolo")
    results = st.session_state.setdefault("editorial_results", {})
    previous = st.session_state.get("editorial_result")
    if previous is not None:
        results[previous.kind] = previous
    if kind == "Dossier":
        topic = st.text_input("Argomento del dossier", max_chars=500, key="editorial_topic", placeholder="Un argomento, un luogo, una questione")
        st.caption("Un percorso ragionato tra le fonti, con introduzione, sezioni e conclusioni.")
    else:
        topic = ""
        st.caption("Una sintesi delle notizie disponibili, bilanciata tra le edizioni dell’archivio.")
    submitted = st.button("Genera dossier tematico" if kind == "Dossier" else "Genera briefing",
                          key="dossier_submit" if kind == "Dossier" else "briefing_submit", type="primary")
    valid = kind != "Dossier" or bool(topic.strip())
    if submitted and not valid:
        st.warning("Scegli un argomento per il dossier.")
    if valid and authorize_action("text", kind.lower(), submitted, topic):
        st.session_state.pop("editorial_result", None)
        results.pop(kind.lower(), None)
        try:
            with st.spinner("Seleziono le fonti e preparo la lettura…"):
                st.session_state["editorial_result"] = perform("text", editorial.generate_product,
                    kind.lower(), topic, authorize_external=True, root=root)
                results[kind.lower()] = st.session_state["editorial_result"]
        except (editorial.EditorialError, PermissionDenied, PersonalStoreError) as exc:
            st.error(friendly_error(exc))
    if kind.lower() not in results:
        st.info("Scegli un argomento per iniziare." if kind == "Dossier" else "Il tuo briefing raccoglierà le notizie disponibili. Premi Genera briefing per iniziare.")
        return
    product = results[kind.lower()]
    coverage = product.coverage
    if coverage["partial"]:
        st.warning("Archivio parzialmente indicizzato: il prodotto copre soltanto i contenuti disponibili, non tutti i quotidiani.")
    st.subheader(readable(product.title))
    if product.message:
        st.info(product.message)
    for section in product.sections:
        with st.container(border=True):
            st.markdown("### " + readable(section["heading"]))
            st.markdown(readable(section["text"]))
    render_sources(product, index=0, last=True, root=root, context=context, formatter=chat_markdown, namespace="editorial")
    with st.expander("Edizioni considerate e copertura"):
        st.caption(f"Fonti selezionate da {len({s.filename for s in product.sources})} edizioni.")
        if diagnostics_enabled(root):
            st.caption(f"Copertura: {coverage['indexed']} chunk indicizzati su {coverage['total']}.")
            for warning in coverage["warnings"]:
                st.info(warning)
            st.dataframe(coverage["files"], hide_index=True)
            if product.diagnostics:
                st.caption(f"Strategia: {product.diagnostics.get('strategy', '')} · Stato: {product.diagnostics.get('status', '')}")
        if diagnostics_enabled(root):
            for source in product.sources:
                st.text(f"[{source.id}] {source.filename} — pagina {source.page}")
                st.text(source.text)


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
    outdated = result_kind in results and versions.get(result_kind) != strategies[result_kind]
    if outdated:
        results.pop(result_kind, None)
        if previous is not None and previous.kind == result_kind:
            st.session_state.pop("knowledge_result", None)
    topic_key = "knowledge_topic" if standalone else "knowledge_topic_" + result_kind
    topic = st.text_input("Quale tema vuoi esplorare?", max_chars=500, key=topic_key, placeholder="Un argomento, un luogo, una questione")
    submitted = st.button("Genera timeline" if kind == "Timeline" else "Genera mappa concettuale",
                          key="timeline_submit" if kind == "Timeline" else "map_submit", type="primary")
    if submitted and not topic.strip():
        st.warning("Scegli un argomento da esplorare.")
    if topic.strip() and authorize_action("text", "visual_" + kind, submitted, topic):
        st.session_state.pop("knowledge_result", None)
        results.pop(result_kind, None)
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
        if " ".join(topic.split()) != result.topic:
            st.caption("Risultato dell’argomento precedente: modifica la richiesta e avvia la generazione per aggiornarlo.")
        render_knowledge(result, archive=context)
    else:
        st.info("La mappa o timeline precedente va aggiornata: premi Genera per usare i nuovi criteri." if outdated else "Scegli un tema per iniziare.")
