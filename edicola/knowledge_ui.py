"""Visualizzazione nativa Streamlit; nessuna API e nessun modello locale."""

import streamlit as st

from edicola.knowledge_validation import compact_map, map_dot
from edicola.pdf_viewer import source_button


def render_knowledge(result, archive=None):
    st.subheader(("Timeline: " if result.kind == "timeline" else "Mappa concettuale: ") + result.topic)
    st.caption(f"Copertura: {result.coverage['indexed']} chunk su {result.coverage['total']}. "
               + ("Risultato riutilizzato dalla cache." if result.from_cache else ""))
    if result.coverage["partial"]:
        st.warning("Archivio parzialmente indicizzato: rappresentazione limitata ai passaggi disponibili.")
    for warning in result.coverage["warnings"]:
        st.info(warning)
    if result.diagnostics.get("status") == "partial_validation":
        st.warning("Alcuni elementi o collegamenti sono stati scartati perché non validati.")
    if not result.data:
        st.info("Nessuna fonte indicizzata disponibile per questo argomento.")
        return
    if result.kind == "timeline":
        events = result.data["events"]
        if events:
            st.vega_lite_chart(
                [{"date": event["event_date"], "title": event["title"], "description": event["description"]} for event in events],
                {"mark": {"type": "point", "filled": True, "size": 120},
                 "encoding": {
                     "x": {"field": "date", "type": "temporal", "title": "Data documentata dell'evento"},
                     "y": {"field": "title", "type": "nominal", "sort": None, "title": "Evento", "axis": {"labelLimit": 220}},
                     "tooltip": [{"field": "date", "type": "temporal"}, {"field": "title"}, {"field": "description"}],
                 }}, width="stretch",
            )
        else:
            st.info("Nessun evento con data completa verificata da collocare sulla timeline.")
        for index, event in enumerate(events):
            render_event(event, result.sources, archive, f"timeline_{index}")
        if result.data["undated_events"]:
            st.subheader("Eventi non collocati cronologicamente")
            st.info("Data non determinabile: anno o contesto temporale non verificabili senza ambiguità.")
            for index, event in enumerate(result.data["undated_events"]):
                render_event(event, result.sources, archive, f"undated_{index}")
        if not events and not result.data["undated_events"]:
            st.info("Nessun evento supportato dalle fonti ha superato la validazione.")
    else:
        diagnostics = result.diagnostics
        if "candidate_edges" in diagnostics:
            st.caption(f"Relazioni candidate: {diagnostics['candidate_edges']} · Accettate: {diagnostics['accepted_edges']} · Escluse: {diagnostics['rejected_edges']}")
            if diagnostics["relations_status"] == "none_generated":
                st.info("Gemini non ha proposto relazioni per i passaggi selezionati.")
            elif diagnostics["relations_status"] == "all_rejected":
                st.info("Gemini ha proposto relazioni, ma tutte sono state escluse dai controlli: consultare i motivi nei dettagli.")
        else:
            st.caption("Conteggi delle relazioni non disponibili per questo risultato precedente: rigenerare la mappa.")
        if "used_chunks" in diagnostics:
            st.caption(f"Passaggi usati: {diagnostics['used_chunks']}, di cui {diagnostics['adjacent_chunks_used']} adiacenti. "
                       f"Esclusi per il budget: {diagnostics['chunks_dropped_for_budget']}.")
        if result.data["nodes"]:
            view = compact_map(result.data)
            if view["edges"]:
                st.caption("Linea continua con freccia: relazione documentata. Linea tratteggiata senza freccia: tema comune verificato, senza causalità.")
                # Larghezza naturale fino al limite del contenitore: non ingrandire i grafi piccoli.
                st.graphviz_chart(map_dot(view), width="content", height=360)
                st.caption("Organizzazioni: azzurro; luoghi: verde; eventi: ocra; concetti: grigio.")
            else:
                st.info("Concetti individuati, ma nessun collegamento validato: elenco senza grafo di nodi scollegati.")
            if len(view["nodes"]) < len(result.data["nodes"]):
                st.caption(f"Vista compatta: {len(view['nodes'])} di {len(result.data['nodes'])} concetti; elenco completo nei dettagli.")
            def node_rows(nodes):
                types = {"organization": "Organizzazione", "place": "Luogo", "event": "Evento", "concept": "Concetto"}
                return [{"Concetto": n["label"], "Tipo": types[n["kind"]], "Fonti": ", ".join(n["source_ids"])} for n in nodes]
            st.dataframe(node_rows(view["nodes"]), hide_index=True, width="stretch")
            with st.expander("Dettagli e prove dei collegamenti"):
                st.dataframe(node_rows(result.data["nodes"]), hide_index=True)
                reasons = {"invalid_or_missing_endpoint": "Estremi assenti o scartati",
                           "unknown_source": "Identificativo fonte sconosciuto", "invalid_citation": "Citazione non verificata",
                           "relation_not_explicit": "Relazione non esplicita o forma linguistica non verificabile",
                           "theme_not_supported": "Tema comune non documentato per entrambi i nodi"}
                for reason, count in result.diagnostics.get("edge_rejections", {}).items():
                    st.caption(f"{reasons.get(reason, 'Collegamento non verificato')}: {count}.")
                details = {
                    "invalid_edge_structure": "Struttura della relazione non valida",
                    "unknown_endpoint": "Identificativo di nodo inesistente",
                    "rejected_endpoint": "Nodo citato escluso dalla validazione",
                    "self_link": "Collegamento del nodo a sé stesso",
                    "invalid_kind": "Tipo di relazione non ammesso",
                    "unknown_source": "Identificativo della fonte inesistente",
                    "invalid_citation": "Citazione non presente letteralmente nel chunk indicato",
                    "invalid_predicate": "Predicato testuale assente o non valido",
                    "predicate_not_literal": "Predicato non presente nelle prove: etichetta parafrasata senza predicato originale",
                    "endpoints_not_in_evidence": "Le prove non collegano entrambi i nodi; contesto assente o non ricongiungibile",
                    "uncertain_or_negated": "La prova contiene negazioni o elementi di incertezza",
                    "unsupported_relation_form": "La costruzione linguistica non consente di verificare soggetto e oggetto",
                    "theme_not_supported": "Tema comune non documentato per entrambi i nodi",
                    "duplicate": "Relazione duplicata",
                    "verified_evidence": "Predicato e nodi verificati nel passaggio originale",
                    "adjacent_evidence": "Prova verificata su due chunk adiacenti della stessa pagina",
                }
                if diagnostics.get("edge_decisions"):
                    st.dataframe([{"Candidata": d["candidate"], "Esito": "Accettata" if d["outcome"] == "accepted" else "Esclusa",
                                   "Motivo": details[d["reason"]]} for d in diagnostics["edge_decisions"]], hide_index=True)
                nodes = {n["id"]: n["label"] for n in result.data["nodes"]}
                sources = {s.id: s for s in result.sources}
                for edge_index, edge in enumerate(result.data["edges"]):
                    relation = edge["label"] + (": " + edge["topic"] if edge.get("topic") else "")
                    connector = " → " if edge["kind"] == "documented" else " — "
                    st.text(connector.join((nodes[edge["from_id"]], relation, nodes[edge["to_id"]])))
                    if edge.get("adjacent_evidence"):
                        st.caption("Relazione verificata su citazioni contigue: entrambi i chunk originali sono riportati qui sotto.")
                    for evidence_index, evidence in enumerate(edge.get("evidence", [])):
                        source = sources[evidence["source_id"]]
                        st.caption(f"[{source.id}] {source.filename} — pagina {source.page}")
                        st.text(evidence["quote"])
                        source_button(source.filename, source.page, context=archive, chunk_id=source.chunk_id,
                                      key=f"map_edge_{edge_index}_{evidence_index}")
        else:
            st.info("Nessun concetto supportato dalle fonti ha superato la validazione.")
    with st.expander("Fonti originali della rappresentazione"):
        for source in result.sources:
            st.text(f"[{source.id}] {source.filename} — pagina {source.page}")
            st.caption(f"Chunk originale: {source.chunk_id}")
            st.text(source.text)
            source_button(source.filename, source.page, context=archive, chunk_id=source.chunk_id, key=f"knowledge_pdf_{source.id}")


def render_event(event, sources=(), archive=None, key="event"):
    with st.container(border=True):
        st.caption("● Data evento: " + (event["event_date"] or "non verificata"))
        origin = {"explicit": "Data esplicita nel testo", "edition_metadata": "Data completata tramite metadati verificati",
                  "undetermined": "Data non determinabile"}
        st.caption(origin.get(event.get("date_origin"), "Data non determinabile"))
        states = {"announced": "Annunciato / programmato; non attestato come avvenuto",
                  "future": "Futuro rispetto all'edizione; svolgimento non attestato",
                  "occurred": "Riferito come avvenuto nel passaggio originale",
                  "undetermined": "Svolgimento non determinabile", "conflicting": "Indizi temporali discordanti"}
        st.caption("Stato dell'evento: " + states[event.get("event_status", "undetermined")])
        if event.get("date_reason"):
            reasons = {
                "missing_evidence": "Citazione temporale assente o non verificata.",
                "missing_edition_date": "Data verificata dell'edizione non disponibile.",
                "missing_calendar_date": "Giorno e mese non presenti nella citazione.",
                "missing_year_anchor": "Nessun indizio sufficiente per determinare l'anno.",
                "multiple_dates": "La citazione contiene più date: riferimento ambiguo.",
                "invalid_calendar_date": "Data non valida nel calendario.",
                "calendar_or_context_conflict": "Calendario, giorno settimanale o contesto temporale non concordano.",
                "publication_reference": "Il riferimento riguarda la pubblicazione, non l'evento.",
                "model_date_conflict": "La data proposta non concorda con la fonte verificata.",
                "historical_context": "Contesto storico: anno non ricostruibile con certezza.",
            }
            st.caption(reasons.get(event["date_reason"], "Contesto temporale ambiguo: data non determinabile."))
        if event.get("date_anchor"):
            anchor = event["date_anchor"]
            st.caption(f"Anno verificato con [{anchor['source_id']}] {anchor['pdf']}, edizione {anchor['publication_date']}.")
        st.text(event["title"])
        st.text(event["description"])
        publication = "; ".join(f"[{item['source_id']}] {item['date'] or 'non disponibile'}" for item in event["publication_dates"])
        st.caption("Data di pubblicazione delle fonti: " + publication)
        if event["temporal_quote"]:
            st.text("Riferimento temporale originale: " + event["temporal_quote"])
        for source in sources:
            if source.id in event.get("source_ids", []):
                st.caption(f"[{source.id}] {source.filename} — pagina {source.page}")
                source_button(source.filename, source.page, context=archive, chunk_id=source.chunk_id, key=f"{key}_pdf_{source.id}")
