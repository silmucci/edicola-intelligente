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
from edicola.knowledge_presentation import undated_order, ordered_timeline, empty_knowledge_message, theme_title, short_text
from edicola.knowledge_validation import compact_map
from edicola.map_presentation import GROUPS, node_captions
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
    articles = getattr(result, "source_articles", None) or {}
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
        ordered, unplaced = ordered_timeline(data["events"], data["undated_events"])
        if ordered:
            render_timeline(ordered, result.sources, archive, articles=articles)
        elif not unplaced:
            st.info("Non emergono sviluppi documentati sufficienti per costruire la timeline.")
        if unplaced:
            with st.expander("Sviluppi senza data di edizione verificata"):
                for index, event in enumerate(undated_order(unplaced, result.sources)):
                    render_event(event, result.sources, archive, f"undated_{index}", articles=articles)
    else:
        render_map(result, archive, technical)
    if technical:
        with st.expander("Diagnostica · sviluppo"):
            st.json(result.diagnostics)
            st.caption("Cache" if result.from_cache else "Nuova elaborazione")


def render_map(result, archive, technical):
    from edicola.experience_ui import readable
    from edicola.map_story import story_graph
    data, diagnostics = result.data, result.diagnostics
    articles = getattr(result, "source_articles", None) or {}
    # Il grafo mostra solo relazioni effettivamente validate: nessun nodo
    # decorativo o isolato. Non si inventano archi per riempire lo spazio.
    linked = {identity for edge in data.get("edges", [])
              for identity in (edge["from_id"], edge["to_id"])}
    connected = {"nodes": [node for node in data["nodes"] if node["id"] in linked],
                 "edges": data.get("edges", [])}
    if not connected["nodes"] or not connected["edges"]:
        st.caption("Non emergono collegamenti sufficientemente documentati per costruire una mappa.")
        return
    # Le relazioni fattuali guidano la lettura; Articolo/Fonte sono
    # supporto alla consultazione, non il centro del grafo.
    view = story_graph(connected, result.topic, limit=14, sources=result.sources)
    if not view["edges"]:
        # Non spacciare un articolo che menziona due persone per una
        # spiegazione delle relazioni fra loro. Le fonti restano accessibili.
        st.caption("Le fonti recuperate non documentano ancora relazioni sufficienti per una mappa significativa.")
        compact_sources([source.id for source in result.sources[:4]], result.sources,
                        archive, "map_unlinked_sources", articles=articles)
        return
    visible = {identity for edge in view["edges"]
               for identity in (edge["from_id"], edge["to_id"])}
    view["nodes"] = [n for n in view["nodes"] if n["id"] in visible]
    captions = node_captions(view["nodes"])
    valid_ids = {n["id"] for n in view["nodes"]}
    if st.session_state.get("knowledge_map_focus", "") not in valid_ids:
        st.session_state["knowledge_map_focus"] = ""
    focus = st.session_state.get("knowledge_map_focus", "")

    if view["edges"]:
        legend = "→ Relazione documentata"
        if any(edge["kind"] == "thematic" for edge in view["edges"]):
            legend += " · ┄ Tema comune, senza legame fattuale"
        if any(edge["kind"] == "contextual" for edge in view["edges"]):
            legend += " · ⇢ Misura descritta nello stesso articolo verificato"
        if any(edge["kind"] == "mention" for edge in view["edges"]):
            legend += " · ↝ Menzione verificata dalla fonte"
        st.caption(legend)
    st.caption("Esplora i fatti principali e seleziona un nodo per leggere le relazioni e le fonti.")
    def choose(node_id):
        st.session_state["knowledge_map_focus"] = node_id
    render_graph(view, topic=result.topic, selected=focus, on_select=choose)

    # Lettura editoriale opzionale: solo triple validate, sempre con i passaggi
    # e i PDF originali. Nessuna sintesi generata senza prove.
    documented = [edge for edge in view["edges"] if edge["kind"] == "documented"]
    if documented:
        labels = {node["id"]: node["label"] for node in data["nodes"]}
        with st.expander("I fatti principali, documentati dai quotidiani", expanded=False):
            for i, edge in enumerate(documented[:8]):
                left, right = labels[edge["from_id"]], labels[edge["to_id"]]
                st.markdown(f"**{readable(left)}** — {readable(edge['label'])} — **{readable(right)}**")
                for evidence in edge.get("evidence", [])[:2]:
                    st.caption(evidence["quote"])
                compact_sources(edge["source_ids"], result.sources, archive,
                                f"map_main_fact_{i}", articles=articles)

    if focus:
        selected = next(n for n in view["nodes"] if n["id"] == focus)
        with st.container(border=True):
            st.subheader(readable(captions[focus]))
            st.caption(NODE_TYPES[selected["kind"]])
            if selected["kind"] in {"article", "source"}:
                # Sono proprietà della pubblicazione, NON date dell'evento.
                details = [selected.get("publication", ""),
                           selected.get("publication_date", "")]
                pages = selected.get("pages") or []
                if pages:
                    details.append("p. " + ", ".join(map(str, pages[:5])))
                st.caption(" · ".join(value for value in details if value))
            st.text(selected["label"])
            compact_sources(selected["source_ids"], result.sources, archive, "map_selected_" + focus,
                            articles=articles)
            render_node_connections(selected, view, {n["id"]: n["label"] for n in view["nodes"]},
                                    result.sources, archive, articles=articles)
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
    """Asse continuo: eventi datati o notizie ordinate per edizione verificata."""
    root = archive.root if archive else Path(__file__).resolve().parents[1]
    editions = source_editions(root, sources)
    months = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")
    payload, references = [], []
    for event in events:
        publication_days = [p.get("date") for p in event.get("publication_dates", []) if p.get("date")]
        display_iso = event.get("event_date") or (min(publication_days) if publication_days else None)
        if not display_iso:
            continue
        date = calendar_date.fromisoformat(display_iso)
        selected, seen = [], set()
        for source in sources:
            if source.id in event.get("source_ids", []) and (source.filename, source.page) not in seen:
                selected.append(source)
                seen.add((source.filename, source.page))
        refs = []
        for source in selected:
            info = editions.get(source.id, {})
            label = " · ".join([info.get("publication") or "Quotidiano",
                                info.get("publication_date") or "Edizione", f"p. {source.page}"])
            article = (articles or {}).get(source.id)
            available = archive is not None
            if available:
                try:
                    resolve_reference(archive, source.filename, source.page, source.chunk_id)
                except PdfViewError:
                    available = False
            refs.append({"label": label, "available": available})
        description = event_text(event["description"])
        is_edition = not bool(event.get("event_date"))
        label = f"{date.day} {months[date.month-1]} {date.year}"
        payload.append({"iso": display_iso, "date": ("Edizione · " if is_edition else "") + label,
                        "edition_fallback": is_edition,
                        "title": short_text(event_text(event["title"]), 115), "summary": short_text(description, 210),
                        "description": description, "status": "", "sources": refs})
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
        if edge["kind"] == "documented":
            st.caption("Posizione attribuita" if relation_category(edge["label"]) == "attributed"
                       else "Relazione fattuale documentata")
        elif edge["kind"] == "mention":
            st.caption("Menzione nel documento · non prova una relazione fra i soggetti citati")
        else:
            st.caption("Tema comune · non indica un legame fattuale")
        connector = " → " if edge["kind"] in {"documented", "mention"} else " — "
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
    if event.get("event_date"):
        st.caption("Data dell’evento: " + event["event_date"])
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
    if event.get("temporal_quote"):
        st.text("Riferimento temporale originale: " + event["temporal_quote"])
    for evidence in event.get("evidence", []):
        st.text(evidence["quote"])
