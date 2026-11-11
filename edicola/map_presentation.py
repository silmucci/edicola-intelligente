"""Etichette e gruppi solo visuali; nessuna modifica a concetti o prove salvati."""

import re
from collections import Counter, deque

from edicola.design_tokens import COLORS

# Solo tipi ammessi dal validatore; i gruppi vuoti non vengono visualizzati.
GROUPS = {
    "measure": ("Misura", "Misure", "box", "#EAF4F5"),
    "proposal": ("Proposta", "Proposte", "box", "#FFF5E6"),
    "person": ("Persona", "Persone", "ellipse", "#F1F0FC"),
    "organization": ("Organizzazione", "Organizzazioni", "box", "#E6F0FF"),
    "event": ("Evento", "Eventi", "box", "#FFF1F2"),
    "place": ("Luogo", "Luoghi", "hexagon", "#EDF5FF"),
    "concept": ("Concetto", "Concetti", "ellipse", COLORS["surface"]),
}
NOMINAL = re.compile(r"^(?:proroga|sospensione|modifica|credito|contributo|ristoro|proposta|piano|programma|intervento|richiesta|riduzione|aumento)\b", re.I)


def node_caption(node):
    """Compressione nominale conservativa, mai taglio a numero di caratteri.

    Non eliminare date, importi, beneficiari, negazioni, modalità, scopi o agenti.
    Nomi propri e frasi non riconosciute rimangono completi e vanno a capo.
    """
    text = " ".join(node["label"].split())
    if node["kind"] in {"measure", "proposal", "concept"} and NOMINAL.match(text):
        text = re.sub(r"\bcredito di imposta\b", "credito d’imposta", text, flags=re.I)
        text = re.sub(r"\s+(?:del|della|dello|dei|degli|delle)\s+", " ", text, flags=re.I)
    return text


def node_captions(nodes):
    captions = {n["id"]: node_caption(n) for n in nodes}
    repeated = Counter(c.casefold() for c in captions.values())
    # Se la compressione rende indistinguibili denominazioni differenti,
    # mostrare gli originali; non assegnare nomi o metadati nuovi.
    for node in nodes:
        if repeated[captions[node["id"]].casefold()] > 1:
            captions[node["id"]] = " ".join(node["label"].split())
    return captions


def node_groups(nodes):
    return [(kind, [n for n in nodes if n["kind"] == kind]) for kind in GROUPS
            if any(n["kind"] == kind for n in nodes)]


def informative_nodes(data, limit):
    """Mantiene ponti documentati fra nodi pertinenti, entro lo stesso limite."""
    nodes = data["nodes"]
    if len(nodes) <= limit:
        return nodes
    neighbors = {n["id"]: [] for n in nodes}
    for edge in data["edges"]:
        if edge["kind"] == "documented":
            neighbors[edge["from_id"]].append(edge["to_id"])
            neighbors[edge["to_id"]].append(edge["from_id"])
    chosen = [nodes[0]["id"]]
    for node in nodes[1:limit]:
        queue = deque([[chosen[0]]])
        seen = {chosen[0]}
        path = []
        while queue:
            candidate = queue.popleft()
            if candidate[-1] == node["id"]:
                path = candidate
                break
            for other in neighbors[candidate[-1]]:
                if other not in seen:
                    seen.add(other)
                    queue.append(candidate + [other])
        additions = [identity for identity in path if identity not in chosen]
        if len(chosen) + len(additions) <= limit:
            chosen.extend(additions)
    for node in nodes:
        if len(chosen) < limit and node["id"] not in chosen:
            chosen.append(node["id"])
    return [node for node in nodes if node["id"] in chosen]


def focused_map(data, node_id):
    if not node_id or node_id not in {node["id"] for node in data["nodes"]}:
        return {"nodes": data["nodes"], "edges": data["edges"]}
    edges = [edge for edge in data["edges"] if node_id in (edge["from_id"], edge["to_id"])]
    neighbors = {node_id} | {endpoint for edge in edges for endpoint in (edge["from_id"], edge["to_id"])}
    nodes = [node for node in data["nodes"] if node["id"] in neighbors]
    if len(nodes) > 10:
        nodes.sort(key=lambda node: node["id"] != node_id)
    return {"nodes": nodes, "edges": edges}

