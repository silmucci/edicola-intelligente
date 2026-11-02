"""Viste di esplorazione, senza generazioni o modifiche ai documenti."""
from pathlib import Path
import streamlit as st
from edicola.archive_ui import diagnostics_enabled
from edicola.pdf_viewer import source_button
from edicola.rag_context import source_editions
from edicola.knowledge_components import event_card, event_text
from edicola.knowledge_presentation import undated_order, empty_knowledge_message, theme_title
from edicola.knowledge_validation import compact_map, map_dot
from edicola.map_presentation import GROUPS, node_captions, node_groups
from edicola.chat_sources import render_contributions, render_context_limit
from edicola.map_relations import relation_category
from edicola.map_exploration import focused_map

NODE_TYPES = {kind: values[0] for kind, values in GROUPS.items()}


def compact_sources(ids, sources, archive, key):
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
                source_button(source.filename, source.page, context=archive, chunk_id=source.chunk_id,
                              key=f"{key}_pdf_{source.id}", label=readable(name + f" · {published} · pagina {source.page}"), help_text="Apri la pagina originale")
        with st.popover("Passaggi originali", key=key + "_passages"):
            for source in selected:
                st.text(source.text)


def render_knowledge(result, archive=None):
    technical = diagnostics_enabled(archive.root if archive else Path(__file__).resolve().parents[1])
    data = result.data or {}
    useful = (data.get("events") or data.get("undated_events")) if result.kind == "timeline" else data.get("nodes")
    if not useful:
        st.caption(theme_title(result.topic))
        st.info(empty_knowledge_message(result))
        render_context_limit(result.coverage)
        render_contributions(result.sources, [], archive.root if archive else Path(__file__).resolve().parents[1])
        if technical:
            with st.expander("Diagnostica · sviluppo"):
                st.json(result.diagnostics)
        return
    st.subheader(theme_title(result.topic))
    from edicola.corpus_cache import render_history_notice
    render_history_notice(result.coverage, archive)
    if result.coverage.get("partial"):
        st.caption("Copertura parziale dell’archivio.")
    render_context_limit(result.coverage)
    if result.kind == "timeline":
        if data["events"]:
            for index, event in enumerate(sorted(data["events"], key=lambda item: item["event_date"])):
                render_event(event, result.sources, archive, f"timeline_{index}")
        if data["undated_events"]:
            st.subheader("Senza data")
            st.caption("Sviluppi senza una data certa, nell’ordine delle letture e non cronologico.")
            for index, event in enumerate(undated_order(data["undated_events"], result.sources)):
                render_event(event, result.sources, archive, f"undated_{index}")
    else:
        render_map(result, archive, technical)
    items = (data.get("events", []) + data.get("undated_events", []) if result.kind == "timeline" else
             data.get("nodes", []) + data.get("edges", []) + data.get("context_edges", []))
    used_ids = {identity for item in items for identity in item.get("source_ids", [])}
    render_contributions(result.sources, used_ids, archive.root if archive else Path(__file__).resolve().parents[1])
    with st.popover("Richiesta originale"):
        st.text(result.topic)
    if technical:
        with st.expander("Diagnostica · sviluppo"):
            st.json(result.diagnostics)
            st.caption("Cache" if result.from_cache else "Nuova elaborazione")


def render_map(result, archive, technical):
    data, diagnostics = result.data, result.diagnostics
    captions = node_captions(data["nodes"])
    view = compact_map(data)
    mode = st.segmented_control("Vista della mappa", ["Grafo", "Elenco"], default="Grafo", key="knowledge_map_view") or "Grafo"
    focus = ""
    if mode == "Grafo":
        options = [""] + [node["id"] for node in data["nodes"]]
        if st.session_state.get("knowledge_map_focus", "") not in options:
            st.session_state["knowledge_map_focus"] = ""
        focus = st.selectbox("Esplora un concetto", options, key="knowledge_map_focus",
                             format_func=lambda value: captions[value] if value else "Tutti i concetti")
        view = compact_map(focused_map(data, focus))
    isolated = {n["id"] for n in view["nodes"]} - {identity for e in view["edges"] for identity in (e["from_id"], e["to_id"])}
    if view["edges"]:
        legend = "→ Relazione documentata · ┄ Tema comune, senza legame fattuale"
        if isolated:
            legend += " · Concetti separati: nessun collegamento documentato"
        st.caption(legend)
    else:
        st.caption("Gruppi di concetti per orientarsi sul tema; non indicano relazioni.")
    if mode == "Grafo":
        # Dimensioni intrinseche: non adattare un grafo di due nodi a tutta la
        # larghezza/altezza della pagina, causando uno zoom iniziale enorme.
        with st.container(horizontal=True, horizontal_alignment="center"):
            with st.container(width=760):
                st.graphviz_chart(map_dot(view, topic=result.topic, grouping=not view["edges"], focused_node=focus),
                                  width="content", height="content", alt="Concetti e collegamenti sul tema richiesto")
    if mode == "Grafo" and len(view["nodes"]) < len(data["nodes"]):
        st.caption("Altri concetti consultabili nei dettagli.")
    nodes = {n["id"]: n["label"] for n in data["nodes"]}
    st.caption("Apri un nome per leggere dettagli, collegamenti e fonti.")
    from edicola.experience_ui import readable
    for kind, members in node_groups(view["nodes"] if focus else data["nodes"]):
        st.caption(GROUPS[kind][1])
        with st.container(horizontal=mode == "Grafo", gap="small"):
            for node in members:
                with st.popover(readable(captions[node["id"]]), key="knowledge_node_" + node["id"], icon=":material/info:"):
                    st.caption(NODE_TYPES[kind])
                    st.text(node["label"])
                    compact_sources(node["source_ids"], result.sources, archive, "map_node_" + node["id"])
                    render_node_connections(node, data, nodes, result.sources, archive)
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


def render_node_connections(node, data, labels, sources, archive):
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
        compact_sources(edge["source_ids"], sources, archive, key)
        with st.popover("Citazioni del collegamento", key=key + "_quotes"):
            for evidence in edge.get("evidence", []):
                st.text(evidence["quote"])


def render_event(event, sources=(), archive=None, key="event"):
    # Un contenitore comprende narrazione e azioni, anche sugli schermi stretti.
    with st.container(border=False):
        event_card(event)
        compact_sources(event.get("source_ids", []), sources, archive, key)
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
