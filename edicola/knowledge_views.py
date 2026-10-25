"""Viste di esplorazione, senza generazioni o modifiche ai documenti."""
from pathlib import Path
import streamlit as st
from edicola.archive_ui import diagnostics_enabled
from edicola.pdf_viewer import source_button
from edicola.rag_context import source_editions
from edicola.knowledge_components import event_card
from edicola.knowledge_presentation import undated_order, empty_knowledge_message, theme_title
from edicola.knowledge_validation import compact_map, map_dot
from edicola.map_presentation import GROUPS, node_captions, node_groups

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
                source_button(source.filename, source.page, context=archive, chunk_id=source.chunk_id,
                              key=f"{key}_pdf_{source.id}", label=readable(name + f" · p. {source.page}"), help_text="Apri la pagina originale")
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
        if technical:
            with st.expander("Diagnostica · sviluppo"):
                st.json(result.diagnostics)
        return
    st.subheader(theme_title(result.topic))
    if result.coverage.get("partial"):
        st.caption("Copertura parziale dell’archivio.")
    if result.kind == "timeline":
        if data["events"]:
            st.subheader("Cronologia documentata")
            for index, event in enumerate(data["events"]):
                render_event(event, result.sources, archive, f"timeline_{index}")
        if data["undated_events"]:
            st.subheader("Eventi e sviluppi documentati")
            st.caption("Senza data evento · ordine delle fonti, non cronologico.")
            for index, event in enumerate(undated_order(data["undated_events"], result.sources)):
                render_event(event, result.sources, archive, f"undated_{index}")
    else:
        render_map(result, archive, technical)
    with st.popover("Richiesta originale"):
        st.text(result.topic)
    if technical:
        with st.expander("Diagnostica · sviluppo"):
            st.json(result.diagnostics)
            st.caption("Cache" if result.from_cache else "Nuova elaborazione")


def render_map(result, archive, technical):
    data, diagnostics = result.data, result.diagnostics
    view = compact_map(data)
    mode = st.segmented_control("Vista della mappa", ["Grafo", "Elenco"], default="Grafo", key="knowledge_map_view") or "Grafo"
    isolated = {n["id"] for n in view["nodes"]} - {identity for e in view["edges"] for identity in (e["from_id"], e["to_id"])}
    if view["edges"]:
        legend = "→ Relazione documentata · ┄ Tema comune"
        if isolated:
            legend += " · Nodi liberi: altri concetti sul tema"
        st.caption(legend)
    else:
        st.caption("Concetti sul tema · senza relazioni documentate")
    if mode == "Grafo":
        # Dimensioni intrinseche: non adattare un grafo di due nodi a tutta la
        # larghezza/altezza della pagina, causando uno zoom iniziale enorme.
        with st.container(horizontal=True, horizontal_alignment="center"):
            with st.container(width=760):
                st.graphviz_chart(map_dot(view, topic=result.topic, grouping=not view["edges"]),
                                  width="content", height="content", alt="Concetti e collegamenti sul tema richiesto")
    if len(view["nodes"]) < len(data["nodes"]):
        st.caption("Altri concetti consultabili nei dettagli.")
    if mode == "Elenco":
        st.dataframe([{"Concetto": n["label"], "Tipo": NODE_TYPES[n["kind"]]} for n in data["nodes"]], hide_index=True, width="stretch")
    nodes = {n["id"]: n["label"] for n in data["nodes"]}
    detail_edges = view["edges"] + data.get("context_edges", [])
    if detail_edges:
        with st.expander("Collegamenti e prove"):
            for index, edge in enumerate(detail_edges):
                with st.container(border=False):
                    st.caption("Relazione documentata" if edge["kind"] == "documented" else "Tema comune")
                    connector = " → " if edge["kind"] == "documented" else " — "
                    label = edge["label"] + (": " + edge["topic"] if edge.get("topic") else "")
                    st.text(connector.join((nodes[edge["from_id"]], label, nodes[edge["to_id"]])))
                    compact_sources(edge["source_ids"], result.sources, archive, f"map_edge_{index}")
                    with st.popover("Prova del collegamento"):
                        for evidence in edge.get("evidence", []):
                            st.text(evidence["quote"])
    st.caption("Esplora un concetto")
    captions = node_captions(data["nodes"])
    from edicola.experience_ui import readable
    for kind, members in node_groups(data["nodes"]):
        st.caption(GROUPS[kind][1])
        with st.container(horizontal=True, gap="small"):
            for node in members:
                with st.popover(readable(captions[node["id"]]), key="knowledge_node_" + node["id"], icon=":material/info:"):
                    st.caption(NODE_TYPES[kind])
                    st.text(node["label"])
                    compact_sources(node["source_ids"], result.sources, archive, "map_node_" + node["id"])
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


def render_event(event, sources=(), archive=None, key="event"):
    event_card(event)
    compact_sources(event.get("source_ids", []), sources, archive, key)
    with st.popover("Dettagli dell’evento", key=key + "_details"):
        st.text(event["title"])
        st.text(event["description"])
        origin = {"explicit": "Data esplicita nel testo", "edition_metadata": "Data completata tramite metadati verificati",
                  "undetermined": "Data non determinabile"}
        st.caption(origin.get(event.get("date_origin"), "Data non determinabile"))
        st.caption("Data evento: " + (event["event_date"] or "non verificata"))
        states = {"announced": "Annunciato / programmato; non attestato come avvenuto", "future": "Futuro rispetto all’edizione",
                  "occurred": "Riferito come avvenuto nel passaggio originale", "conflicting": "Indizi temporali discordanti",
                  "undetermined": "Svolgimento non determinabile"}
        st.caption(states.get(event.get("event_status"), "Svolgimento non determinabile"))
        publication = "; ".join(f"[{item['source_id']}] {item['date'] or 'non disponibile'}" for item in event["publication_dates"])
        st.caption("Data di pubblicazione delle fonti: " + publication)
        if event.get("date_anchor"):
            st.caption("Anno completato con l’edizione " + event["date_anchor"]["publication_date"])
            st.caption("edizione " + event["date_anchor"]["publication_date"])
        if event.get("date_reason"):
            st.caption("La citazione non consente una data evento completa e coerente; nessuna data editoriale sostituita all’evento.")
        if event.get("temporal_quote"):
            st.text("Riferimento temporale originale: " + event["temporal_quote"])
        for evidence in event.get("evidence", []):
            st.text(evidence["quote"])
