"""Sezioni di lettura; i moduli di ricerca e generazione rimangono invariati."""

import streamlit as st

from edicola import editorial, knowledge, rag
from edicola.knowledge_ui import render_knowledge
from edicola.pdf_viewer import source_button


def render_chat(root, context):
    st.header("Chat AI")
    st.caption("Fai una domanda ai quotidiani indicizzati. Le risposte riportano le fonti; ogni domanda è indipendente.")
    with st.form("rag_question"):
        question = st.text_input("Inserisci una domanda", max_chars=2000, key="rag_input")
        authorized = st.checkbox("Autorizzo l'invio a Gemini della domanda e dei passaggi recuperati dai quotidiani.", key="rag_authorized")
        submitted = st.form_submit_button("Chiedi all'Edicola", key="rag_submit")
    if submitted:
        st.session_state.pop("rag_result", None)
        st.session_state.pop("rag_question_answered", None)
        if not question.strip():
            st.warning("Inserisci una domanda.")
        elif not authorized:
            st.warning("Autorizza l'invio della domanda e dei passaggi a Gemini prima di procedere.")
        else:
            try:
                with st.spinner("Ricerca dei passaggi e preparazione della risposta…"):
                    result = rag.ask_question(question, authorize_external=True, root=root)
                st.session_state["rag_result"] = result
                st.session_state["rag_question_answered"] = question
            except rag.RagError as exc:
                st.error(str(exc))
    if "rag_result" in st.session_state:
        result = st.session_state["rag_result"]
        st.subheader(st.session_state["rag_question_answered"])
        st.text(result.answer)
        if result.used_source_ids:
            st.subheader("Fonti utilizzate")
            for source in result.sources:
                if source.id in result.used_source_ids:
                    st.text(f"[{source.id}] {source.filename} — pagina {source.page}")
                    source_button(source.filename, source.page, context=context, chunk_id=source.chunk_id, key=f"rag_pdf_{source.id}")
        if result.sources:
            with st.expander("Passaggi originali recuperati"):
                for source in result.sources:
                    st.text(f"[{source.id}] {source.filename} — pagina {source.page} — distanza {source.distance:.6f}")
                    st.caption(f"Chunk: {source.chunk_id}")
                    st.text(source.text)


def render_editorial(root, context):
    st.header("Approfondimenti")
    st.caption("Crea un dossier su un argomento o un briefing delle notizie disponibili. I risultati validati vengono conservati in cache.")
    with st.form("editorial_products"):
        topic = st.text_input("Argomento del dossier", max_chars=500, key="editorial_topic")
        authorized = st.checkbox("Autorizzo l'invio a Gemini dell'argomento e dei passaggi selezionati per il prodotto editoriale.", key="editorial_authorized")
        dossier = st.form_submit_button("Genera dossier tematico", key="dossier_submit")
        briefing = st.form_submit_button("Genera briefing", key="briefing_submit")
    if dossier or briefing:
        st.session_state.pop("editorial_result", None)
        if not authorized:
            st.warning("Autorizza l'invio dei contenuti prima di generare il prodotto editoriale.")
        else:
            try:
                with st.spinner("Selezione delle fonti e preparazione del prodotto editoriale…"):
                    st.session_state["editorial_result"] = editorial.generate_product(
                        "dossier" if dossier else "briefing", topic, authorize_external=True, root=root)
            except editorial.EditorialError as exc:
                st.error(str(exc))
    if "editorial_result" not in st.session_state:
        return
    product = st.session_state["editorial_result"]
    coverage = product.coverage
    if coverage["partial"]:
        st.warning("Archivio parzialmente indicizzato: il prodotto copre soltanto i contenuti disponibili, non tutti i quotidiani.")
    if product.from_cache:
        st.caption("Risultato riutilizzato dalla cache.")
    st.subheader(product.title)
    if product.message:
        st.info(product.message)
    for section in product.sections:
        st.subheader(section["heading"])
        st.text(section["text"])
    if product.used_source_ids:
        st.subheader("Fonti del prodotto editoriale")
        for source in product.sources:
            if source.id in product.used_source_ids:
                st.text(f"[{source.id}] {source.filename} — pagina {source.page}")
                source_button(source.filename, source.page, context=context, chunk_id=source.chunk_id, key=f"editorial_pdf_{source.id}")
    with st.expander("Copertura, diagnostica e passaggi selezionati"):
        st.caption(f"Copertura: {coverage['indexed']} chunk indicizzati su {coverage['total']}.")
        for warning in coverage["warnings"]:
            st.info(warning)
        st.dataframe(coverage["files"], hide_index=True)
        st.caption(f"Selezione: {len(product.sources)} passaggi da {len({s.filename for s in product.sources})} PDF.")
        if product.diagnostics:
            st.caption(f"Strategia: {product.diagnostics.get('strategy', '')} · Stato: {product.diagnostics.get('status', '')}")
        for source in product.sources:
            st.text(f"[{source.id}] {source.filename} — pagina {source.page}")
            st.text(source.text)


def render_visuals(root, context):
    st.header("Timeline e Mappe")
    st.caption("Esplora date documentate e relazioni verificate. Non vengono aggiunti eventi o collegamenti privi di fonti.")
    with st.form("knowledge_products"):
        topic = st.text_input("Argomento della timeline o mappa", max_chars=500, key="knowledge_topic")
        authorized = st.checkbox("Autorizzo l'invio a Gemini dell'argomento e dei passaggi per timeline o mappa.", key="knowledge_authorized")
        timeline = st.form_submit_button("Genera timeline", key="timeline_submit")
        concept_map = st.form_submit_button("Genera mappa concettuale", key="map_submit")
    if timeline or concept_map:
        st.session_state.pop("knowledge_result", None)
        if not authorized:
            st.warning("Autorizza l'invio dell'argomento e dei passaggi prima di generare la rappresentazione.")
        else:
            try:
                with st.spinner("Ricerca delle fonti e validazione della rappresentazione…"):
                    st.session_state["knowledge_result"] = knowledge.generate_knowledge(
                        "timeline" if timeline else "map", topic, authorize_external=True, root=root)
            except knowledge.KnowledgeError as exc:
                st.error(str(exc))
    if "knowledge_result" in st.session_state:
        render_knowledge(st.session_state["knowledge_result"], archive=context)
