"""Viste di esplorazione, senza generazioni o modifiche ai documenti."""
from pathlib import Path
from datetime import date as calendar_date
import hashlib
import json
import streamlit as st
from edicola.archive_ui import diagnostics_enabled
from edicola.pdf_viewer import source_button, resolve_reference, open_reference, PdfViewError
from edicola.rag_context import source_editions
from edicola.article_evidence import article_reference
from edicola.knowledge_components import event_card, event_text, timeline_story, LABELS
from edicola.knowledge_presentation import undated_order, empty_knowledge_message, theme_title, short_text
from edicola.knowledge_validation import compact_map
from edicola.map_presentation import GROUPS, node_captions, node_groups
from edicola.chat_sources import render_context_limit
from edicola.map_relations import relation_category
from edicola.map_component import render_graph

NODE_TYPES = {kind: values[0] for kind, values in GROUPS.items()}


def compact_sources(ids, sources, archive, key, *, articles=None):
    from edicola.experience_ui import readable
    selected = [s for s in sources if s.id in ids]
    if selected:
        root = archive.root if archive else Path(__file__).resolve().parents[1]
        editions = source_editions(root, selected)
        seen = set()
        with st.container(horizontal=True, gap="small"):
            for source in selected:
                if (source.filename, source.page) in seen:
                    continue
                seen.add((source.filename, source.page))
                name = editions.get(source.id, {}).get("publication") or "Documento dell’archivio"
                published = editions.get(source.id, {}).get("publication_date") or "Data non disponibile"
                article = (articles or {}).get(source.id)
                title = article_reference(article) if article else ""
                label = name + f" · {published} · pagina {source.page}"
                if title:
                    label += " · " + title
                source_button(source.filename, source.page, context=archive, chunk_id=source.chunk_id,
                              key=f"{key}_pdf_{source.id}", label=readable(label),
                              help_text="Apri la pagina originale")
        with st.popover("Leggi la fonte", key=key + "_passages"):
            for source in selected:
                article = (articles or {}).get(source.id)
                if article:
                    st.caption(article_reference(article))
                st.text(source.text)


def render_knowledge(result, archive=None):
    technical = diagnostics_enabled(archive.root if archive else Path(__file__).resolve().parents[1])
    data = result.data or {}
    useful = (data.get("events") or data.get("undated_events")) if result.kind == "timeline" else data.get("nodes")
    if not useful:
        st.caption(theme_title(result.topic))
        st.info(empty_knowledge_message(result))
        render_context_limit(result.coverage)
        if technical:
            with st.expander("Diagnostica · sviluppo"):
                st.json(result.diagnostics)
        return
    st.subheader(theme_title(result.topic))
    from edicola.corpus_cache import render_history_notice
    render_history_notice(result.coverage, archive)
    render_context_limit(result.coverage)
    if result.kind == "timeline":
        if data["events"]:
            render_timeline(sorted(data["events"], key=lambda item: item["event_date"]), result.sources, archive,
                            articles=result.source_articles)
        else:
            st.info("Le fonti disponibili non permettono di ricostruire una cronologia affidabile. Puoi consultare le fonti e gli altri sviluppi.")
            compact_sources([s.id for s in result.sources], result.sources, archive, "timeline_unresolved",
                            articles=result.source_articles)
        if data["undated_events"]:
            with st.expander("Altri sviluppi"):
                st.caption("Sviluppi documentati sul tema, senza una data certa. L’ordine non è cronologico.")
                for index, event in enumerate(undated_order(data["undated_events"], result.sources)):
                    render_event(event, result.sources, archive, f"undated_{index}", articles=result.source_articles)
    else:
        render_map(result, archive, technical)
    if technical:
        with st.expander("Diagnostica · sviluppo"):
            st.json(result.diagnostics)
            st.caption("Cache" if result.from_cache else "Nuova elaborazione")


def render_map(result, archive, technical):
    from edicola.experience_ui import readable
    data, diagnostics = result.data, result.diagnostics
    captions = node_captions(data["nodes"])
    view = compact_map(data)
    if not data["edges"]:
        st.info("Non emergono relazioni verificabili fra i concetti. Puoi consultare le entità documentate e le loro fonti.")
        mode = "Elenco"
    else:
        mode = st.segmented_control("Vista della mappa", ["Grafo", "Elenco"], default="Grafo", key="knowledge_map_view") or "Grafo"
    focus = ""
    if mode == "Grafo":
        if st.session_state.get("knowledge_map_focus", "") not in {n["id"] for n in view["nodes"]}:
            st.session_state["knowledge_map_focus"] = ""
        focus = st.session_state.get("knowledge_map_focus", "")
    isolated = {n["id"] for n in view["nodes"]} - {identity for e in view["edges"] for identity in (e["from_id"], e["to_id"])}
    if view["edges"]:
        legend = "→ Relazione documentata"
        if any(edge["kind"] != "documented" for edge in view["edges"]):
            legend += " · ┄ Tema comune, senza legame fattuale"
        if isolated:
            legend += " · Concetti separati: nessun collegamento documentato"
        st.caption(legend)
    else:
        st.caption("Concetti documentati sul tema. Le fonti di questa mappa non attestano collegamenti fra loro.")
    if mode == "Grafo":
        def choose(node_id):
            st.session_state["knowledge_map_focus"] = node_id
        st.caption("Seleziona un concetto per leggere collegamenti e fonti. Scorri nella mappa per esplorarla.")
        render_graph(view, topic=result.topic, selected=focus, on_select=choose)
        if focus:
            selected = next(n for n in view["nodes"] if n["id"] == focus)
            with st.container(border=True):
                st.subheader(readable(captions[focus]))
                st.caption(NODE_TYPES[selected["kind"]])
                st.text(selected["label"])
                compact_sources(selected["source_ids"], result.sources, archive, "map_selected_" + focus,
                                articles=result.source_articles)
                render_node_connections(selected, data, {n["id"]: n["label"] for n in data["nodes"]}, result.sources, archive,
                                        articles=result.source_articles)
    if mode == "Grafo" and len(view["nodes"]) < len(data["nodes"]):
        st.caption("Altri concetti disponibili nella vista Elenco.")
    nodes = {n["id"]: n["label"] for n in data["nodes"]}
    for kind, members in node_groups(data["nodes"] if mode == "Elenco" else []):
        st.caption(GROUPS[kind][1])
        with st.container(horizontal=mode == "Grafo", gap="small"):
            for node in members:
                with st.popover(readable(captions[node["id"]]), key="knowledge_node_" + node["id"], icon=":material/info:"):
                    st.caption(NODE_TYPES[kind])
                    st.text(node["label"])
                    compact_sources(node["source_ids"], result.sources, archive, "map_node_" + node["id"],
                                    articles=result.source_articles)
                    render_node_connections(node, data, nodes, result.sources, archive, articles=result.source_articles)
    if technical:
        with st.expander("Relazioni · sviluppo"):
            st.caption("Nodi nel grafo: " + ", ".join(n["id"] for n in view["nodes"]))
            if diagnostics.get("relevance_nodes"):
                st.dataframe(diagnostics["relevance_nodes"], hide_index=True)
            if diagnostics.get("relevance_edges"):
                st.dataframe(diagnostics["relevance_edges"], hide_index=True)
            reasons = {"predicate_not_literal": "Predicato non presente nelle prove: etichetta parafrasata",
                       "unknown_source": "Fonte sconosciuta", "invalid_citation": "Citazione non verificata",
                       "endpoints_not_in_evidence": "Estremi non collegati dalle prove",
                       "uncertain_or_negated": "Relazione ipotetica o negata",
                       "unsupported_relation_form": "Costruzione linguistica non verificabile"}
            if diagnostics.get("edge_decisions"):
                st.dataframe([{"Candidata": d["candidate"], "Esito": d["outcome"],
                               "Motivo": reasons.get(d["reason"], d["reason"].replace("_", " "))}
                              for d in diagnostics["edge_decisions"]], hide_index=True)
            for source in result.sources:
                st.caption(f"[{source.id}] {source.filename} — pagina {source.page}")
                st.text(source.text)


def render_timeline(events, sources, archive, *, articles=None):
    """Asse continuo con sole date verificate; azioni PDF validate sul server."""
    root = archive.root if archive else Path(__file__).resolve().parents[1]
    editions = source_editions(root, sources)
    months = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")
    payload, references = [], []
    for event in events:
        date = calendar_date.fromisoformat(event["event_date"])
        selected, seen = [], set()
        for source in sources:
            if source.id in event.get("source_ids", []) and (source.filename, source.page) not in seen:
                selected.append(source)
                seen.add((source.filename, source.page))
        refs = []
        for source in selected:
            info = editions.get(source.id, {})
            label = " · ".join([info.get("publication") or "Documento dell’archivio",
                                info.get("publication_date") or "Data non disponibile", f"pagina {source.page}"])
            article = (articles or {}).get(source.id)
            if article:
                label += " · " + article_reference(article)
            available = archive is not None
            if available:
                try:
                    resolve_reference(archive, source.filename, source.page, source.chunk_id)
                except PdfViewError:
                    available = False
            refs.append({"label": label, "available": available})
        description = event_text(event["description"])
        payload.append({"iso": event["event_date"], "date": f"{date.day} {months[date.month-1]} {date.year}",
                        "title": event_text(event["title"]), "summary": short_text(description, 280),
                        "description": description, "status": LABELS.get(event.get("development_kind"), "")
                        if event.get("development_kind") != "undetermined" else "", "sources": refs})
        references.append(selected)
    identity = hashlib.sha256(json.dumps([payload, [[s.chunk_id for s in refs] for refs in references]], sort_keys=True).encode()).hexdigest()[:16]
    key = "knowledge_timeline_story_" + identity
    def action():
        value = st.session_state.get(key, {}).get("action")
        if not isinstance(value, dict) or type(value.get("event")) is not int or not 0 <= value["event"] < len(events):
            return
        index = value["event"]
        if "source" not in value:
            st.session_state["knowledge_timeline_detail"] = {"key": key, "index": index}
            return
        source_index = value["source"]
        if type(source_index) is int and 0 <= source_index < len(references[index]) and archive is not None:
            source = references[index][source_index]
            try:
                open_reference(archive, source.filename, source.page, source.chunk_id)
            except PdfViewError:
                st.session_state["knowledge_source_notice"] = "Questa fonte non è disponibile nell’archivio attuale."
    timeline_story(data={"items": payload}, key=key, on_action_change=action)
    if notice := st.session_state.pop("knowledge_source_notice", None):
        st.info(notice)
    detail = st.session_state.get("knowledge_timeline_detail", {})
    if detail.get("key") == key and type(detail.get("index")) is int and 0 <= detail["index"] < len(events):
        with st.expander("Dettagli dell’evento selezionato", expanded=True):
            render_event_details(events[detail["index"]], sources)


def render_node_connections(node, data, labels, sources, archive, *, articles=None):
    """Solo collegamenti già validati, accanto al concetto cui appartengono."""
    edges = data["edges"] + data.get("context_edges", [])
    connected = [(index, edge) for index, edge in enumerate(edges)
                 if node["id"] in (edge["from_id"], edge["to_id"])]
    if not connected:
        st.caption("Nessun collegamento documentato per questo concetto.")
    for index, edge in connected:
        st.caption(("Posizione attribuita" if relation_category(edge["label"]) == "attributed" else "Relazione documentata")
                   if edge["kind"] == "documented" else "Tema comune · non indica un legame fattuale")
        connector = " → " if edge["kind"] == "documented" else " — "
        label = edge["label"] + (": " + edge["topic"] if edge.get("topic") else "")
        st.text(connector.join((labels[edge["from_id"]], label, labels[edge["to_id"]])))
        key = f"map_node_{node['id']}_edge_{index}"
        compact_sources(edge["source_ids"], sources, archive, key, articles=articles)
        with st.popover("Citazioni del collegamento", key=key + "_quotes"):
            for evidence in edge.get("evidence", []):
                st.text(evidence["quote"])


def render_event(event, sources=(), archive=None, key="event", *, articles=None):
    # Un contenitore comprende narrazione e azioni, anche sugli schermi stretti.
    with st.container(border=False):
        event_card(event)
        compact_sources(event.get("source_ids", []), sources, archive, key, articles=articles)
        with st.popover("Dettagli e date", key=key + "_details"):
            render_event_details(event, sources)


def render_event_details(event, sources):
    st.text(event_text(event["title"]))
    st.text(event_text(event["description"]))
    origin = {"explicit": "Data esplicita nel testo", "edition_metadata": "Data completata tramite metadati verificati",
              "undetermined": "Data non determinabile"}
    st.caption(origin.get(event.get("date_origin"), "Data non determinabile"))
    st.caption("Data evento: " + (event["event_date"] or "non verificata"))
    states = {"announced": "Annunciato / programmato; non attestato come avvenuto", "future": "Futuro rispetto all’edizione",
              "occurred": "Riferito come avvenuto nel passaggio originale", "conflicting": "Indizi temporali discordanti",
              "undetermined": "Svolgimento non determinabile"}
    st.caption(states.get(event.get("event_status"), "Svolgimento non determinabile"))
    source_map = {source.id: source for source in sources}
    for item in event.get("publication_dates", []):
        source = source_map.get(item["source_id"])
        page = f" · pagina {source.page}" if source else ""
        st.caption("Pubblicazione della fonte" + page + ": " + (item["date"] or "non disponibile"))
    if event.get("date_anchor"):
        st.caption("Anno completato con l’edizione " + event["date_anchor"]["publication_date"])
    if event.get("date_reason"):
        st.caption("La citazione non consente una data evento completa e coerente; nessuna data editoriale sostituita all’evento.")
    if event.get("temporal_quote"):
        st.text("Riferimento temporale originale: " + event["temporal_quote"])
    for evidence in event.get("evidence", []):
        st.text(evidence["quote"])
