"""Etichette e gruppi solo visuali; nessuna modifica a concetti o prove salvati."""

import re
from collections import Counter

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
