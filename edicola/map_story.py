"""Montaggio editoriale della sola Mappa.

Il grafo principale dà precedenza a eventi/provvedimenti e relazioni
fattuali; articoli e menzioni restano navigabili, ma non sostituiscono
gli avvenimenti. Non aggiunge mai archi o fatti.
"""
from collections import Counter

from edicola.knowledge_relevance import terms


CORE_KINDS = {"event", "measure", "proposal"}
SOURCE_KINDS = {"article", "source"}
EDGE_VALUE = {"documented": 7, "thematic": 4, "mention": 1}


def story_graph(data: dict, topic: str, *, limit: int = 14) -> dict:
    """Selezione per valore giornalistico e capacità di collegare più fatti."""
    if not 2 <= limit <= 20:
        raise ValueError("Numero di nodi del grafo fuori intervallo.")
    nodes = {n["id"]: n for n in data.get("nodes", [])}
    edges = [e for e in data.get("edges", [])
             if e.get("from_id") in nodes and e.get("to_id") in nodes]
    if not nodes or not edges:
        return {"nodes": [], "edges": []}
    matched = terms(topic)
    fact_degree = Counter(endpoint for edge in edges if edge["kind"] == "documented"
                          for endpoint in (edge["from_id"], edge["to_id"]))
    degree = Counter(endpoint for edge in edges for endpoint in (edge["from_id"], edge["to_id"]))

    def node_value(identity):
        node = nodes[identity]
        return (10 * fact_degree[identity]
                + (6 if node["kind"] in CORE_KINDS else 0)
                + (2 if node["kind"] in {"person", "organization"} else 0)
                + min(4, 2 * len(terms(node["label"]) & matched))
                + degree[identity]
                - (6 if node["kind"] in SOURCE_KINDS else 0))

    def edge_value(edge):
        a, b = edge["from_id"], edge["to_id"]
        return (EDGE_VALUE.get(edge["kind"], 0) * 20
                + node_value(a) + node_value(b)
                + len(set(edge.get("source_ids", []))))

    # Nella lettura iniziale prevalgono le triple relative alla vicenda.
    factual = sorted((e for e in edges if e["kind"] == "documented"),
                     key=edge_value, reverse=True)
    thematic = sorted((e for e in edges if e["kind"] == "thematic"),
                      key=edge_value, reverse=True)
    mentions = sorted((e for e in edges if e["kind"] == "mention"),
                      key=edge_value, reverse=True)
    selected = set()
    chosen_edges = []

    def take(edge, *, max_sources=2):
        endpoints = {edge["from_id"], edge["to_id"]}
        if len(selected | endpoints) > limit:
            return False
        if edge["kind"] == "mention":
            sources = {identity for identity in selected | endpoints
                       if nodes[identity]["kind"] in SOURCE_KINDS}
            if len(sources) > max_sources:
                return False
            # Le fonti non sono la parte dominante del grafo.
            if factual and not any(nodes[identity]["kind"] in CORE_KINDS
                                   for identity in selected | endpoints):
                return False
        selected.update(endpoints)
        chosen_edges.append(edge)
        return True

    for edge in factual:
        take(edge)
    for edge in thematic:
        if edge["from_id"] in selected or edge["to_id"] in selected or not factual:
            take(edge)
    # Una o due fonti al massimo collegano i protagonisti a documenti
    # selezionati, non diventano automaticamente il centro della lettura.
    for edge in mentions:
        source = next((i for i in (edge["from_id"], edge["to_id"])
                       if nodes[i]["kind"] in SOURCE_KINDS), None)
        target = edge["to_id"] if source == edge["from_id"] else edge["from_id"]
        if source is None:
            continue
        if factual and target not in selected:
            continue
        take(edge, max_sources=1 if factual else 2)

    # Se l'unico contenuto verificabile è una serie di menzioni, mostrale
    # senza attribuire azioni inventate (ma non più di poche per documento).
    if not chosen_edges:
        for edge in mentions[:min(limit - 1, 5)]:
            take(edge)
    shown = {identity for edge in chosen_edges
             for identity in (edge["from_id"], edge["to_id"])}
    order = sorted(shown, key=lambda i: (nodes[i]["kind"] in SOURCE_KINDS,
                                          -node_value(i), i))
    return {"nodes": [nodes[identity] for identity in order],
            "edges": chosen_edges}


def story_focus(data: dict, topic: str) -> str | None:
    """Il centro è un fatto/provvedimento, non un titolo di giornale."""
    nodes = data.get("nodes", [])
    if not nodes:
        return None
    matches = terms(topic)
    factual = Counter(identity for edge in data.get("edges", [])
                      if edge["kind"] == "documented"
                      for identity in (edge["from_id"], edge["to_id"]))
    return max(nodes, key=lambda n: (n["kind"] in CORE_KIN,
                                     factual[n["id"]],
                                     len(terms(n["label"]) & matches),
                                     n["kind"] not in SOURCE_KINDS,
                                     -nodes.index(n)))["id"]
