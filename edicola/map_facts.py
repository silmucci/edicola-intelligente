"""Candidati di fatti salienti per il Knowledge Graph, indipendenti dai nomi propri.

Estrae soltanto costruzioni soggetto–azione–provvedimento esplicite. Tutto
passa comunque da validate_map: non interpreta da solo relazioni causali,
date, ruoli impliciti o posizioni contraddittorie.
"""
from __future__ import annotations

import re

from edicola.map_relations import documented_relation
from edicola.knowledge_relevance import Topic


SUBJECT = (
    r"(?:(?:il|lo|la|l['’]|i|gli|le)\s*)?"
    r"(?:(?:ministro|ministra|presidente|senatore|senatrice|sindaco|sindaca)"
    r"\s+)?"
    r"(?P<actor>[A-ZÀ-ÖØ-Þ][\w’'-]+(?:\s+[A-ZÀ-ÖØ-Þ][\w’'-]+){0,2})"
)
ACTION = (
    r"(?P<verb>(?:(?:ha|hanno|aveva|avevano)\s+"
    r"(?:approvato|annunciato|presentato|finanziato|stanziato|illustrato|"
    r"proposto|discusso|esaminato|promosso|sostenuto|varato|firmato|"
    r"votato|adottato|respinto|chiesto|confermato)|"
    r"(?:approva|annuncia|presenta|finanzia|stanzia|illustra|propone|"
    r"discute|esamina|promuove|sostiene|vara|firma|vota|adotta|respinge)))"
)
ACTION_PATTERN = re.compile(
    r"(?<!\w)" + SUBJECT + r"\s+" + ACTION
    + r"\s+(?:(?:il|lo|la|i|gli|le|un|una|l['’])\s*)?"
    + r"(?P<object>"
    + r"(?:(?:disegno|proposta)\s+di\s+legge|(?:decreto|riforma|"
    + r"piano|progetto|programma|finanziamento|investimento|"
    + r"stanziamento|intervento|misura|accordo|emendamento|legge)"
    + r"(?:\s+(?:[A-ZÀ-ÖØ-Þ][\w’'-]+|(?:sul|sulla|dei|delle|per)\s+\w+)){1,4})"
    + r")",
    re.I,
)
# Senza questi nomi non sappiamo a quale provvedimento si riferisca l'azione.
GENERIC_OBJECT = re.compile(
    r"^(?:disegno\s+di\s+legge|proposta\s+di\s+legge|decreto|riforma|"
    r"piano|progetto|programma|finanziamento|investimento|"
    r"stanziamento|intervento|misura|accordo|emendamento|legge)$",
    re.I,
)


def complete_salient_facts(raw: dict, sources: list, topic: str, *,
                           max_nodes: int = 16, max_edges: int = 24) -> dict:
    """Arricchisce l'estrazione LLM senza riformulare le prove originali.

    Richiede sempre identità, predicato e oggetto nella stessa proposizione.
    Non rimuove nodi originali, non crea archi basati su co-occorrenza.
    """
    matcher = Topic(topic)
    items = list(raw.get("nodes", []))
    edges = list(raw.get("edges", []))
    labels = {item["label"]["text"].strip().casefold(): item["id"]
              for item in items if isinstance(item, dict)
              and isinstance(item.get("label"), dict)
              and isinstance(item["label"].get("text"), str)}
    existing = {(e.get("from_id"), e.get("to_id"), e.get("predicate")
                 or e.get("label", {}).get("text"))
                for e in edges if isinstance(e, dict)}
    next_id = max((int(item["id"][1:]) for item in items if isinstance(item, dict)
                   and re.fullmatch(r"N\d+", str(item.get("id", "")))), default=0) + 1
    for source in sources:
        if len(items) >= max_nodes and len(edges) >= max_edges:
            break
        if not matcher.score(source.text):
            continue
        sentences = re.split(r"(?<=[.!?;])\s+|\n+", source.text)
        for passage in sentences:
            passage = passage.strip()
            if len(passage) < 30 or len(passage) > 1400 or len(edges) >= max_edges:
                continue
            # Non trattare titoli isolati come fatti: serve una proposizione.
            for match in ACTION_PATTERN.finditer(passage):
                actor, verb, object_name = (match.group(key).strip() for key in ("actor", "verb", "object"))
                if GENERIC_OBJECT.fullmatch(object_name) or actor.casefold() == object_name.casefold():
                    continue
                if not documented_relation(actor, verb, object_name, passage):
                    continue
                missing = [v for v in (actor, object_name) if v.casefold() not in labels]
                if len(items) + len(missing) > max_nodes or len(edges) >= max_edges:
                    continue
                evidence = [{"source_id": source.id, "quote": passage}]
                for label, kind in ((actor, "organization"), (object_name, "proposal")):
                    key = label.casefold()
                    if key not in labels:
                        labels[key] = f"N{next_id}"
                        next_id += 1
                        items.append({"id": labels[key], "kind": kind,
                                      "label": {"text": label, "evidence": evidence}})
                signature = (labels[actor.casefold()], labels[object_name.casefold()], verb)
                if signature in existing:
                    continue
                edges.append({"from_id": signature[0], "to_id": signature[1],
                              "kind": "documented", "predicate": verb,
                              "label": {"text": verb, "evidence": evidence}})
                existing.add(signature)
    return {"nodes": items, "edges": edges}
