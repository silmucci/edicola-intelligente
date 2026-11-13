"""Misure quantificate descritte nello stesso articolo verificato di una vicenda.

Non inventa relazioni dirette: CONTEXTUAL significa che un intervento è
descritto nell'articolo relativo al provvedimento, non che la fonte riporti
una tripla attiva letterale. Nomi, importi e prove restano verificabili.
"""
from __future__ import annotations

import re
from collections import defaultdict

from edicola.map_facts import original_sentences
from edicola.map_retrieval import request_focus


AMOUNT = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:miliard[oi]|milion[ei]|mila)(?:\s+di\s+euro)?\b", re.I)
MEASURE = re.compile(r"\b(?:previst[oaie]|stanziat[oaie]|destinat[oaie]|rifinanziat[oaie]|finanziat[oaie]|investiment[oi]|stanziament[oi])\b", re.I)
SECTION = re.compile(r"^(.{6,55}?):\s+")


def article_scope(sources, verified):
    """Passa il titolo alle continuazioni solo con una singola attribuzione
    dichiarata nei metadati delle pagine dello stesso PDF.
    """
    known = {s.id: verified[s.id] for s in sources if s.id in verified}
    pages = defaultdict(set)
    for source in sources:
        article = known.get(source.id)
        if article:
            for page in article.get("pages", []):
                if type(page) is int:
                    pages[(source.filename, page)].add(article["title"])
    for source in sources:
        if source.id not in known and len(pages[(source.filename, source.page)]) == 1:
            known[source.id] = {"title": next(iter(pages[(source.filename, source.page)])), "pages": []}
    return known


PROVISION_NEAR_FOCUS = re.compile(
    r"(?<!\w)(?:disegno\s+di\s+legge|proposta\s+di\s+legge|ddl|"
    r"decreto|programma|piano|progetto|provvedimento)\s+"
    r"(?:[«“\"])?$", re.I
)


def verified_initiative_hub(data, sources, articles, topic):
    """Riconosce un'iniziativa letterale citata in un articolo verificato.

    Non attribuisce al nodo azioni o ruoli: le misure rimangono
    dichiaratamente contestuali e verificabili nei passaggi originali.
    """
    focus = request_focus(topic)
    if not focus:
        return None
    expression = re.compile(r"(?<!\w)" + re.escape(focus) + r"(?!\w)", re.I)
    scope = article_scope(sources, articles)
    found = []
    for source in sources:
        if not expression.search(scope.get(source.id, {}).get("title", "")):
            continue
        for occurrence in expression.finditer(source.text):
            before = source.text[max(0, occurrence.start() - 75):occurrence.start()]
            match = PROVISION_NEAR_FOCUS.search(before)
            if not match:
                continue
            end = occurrence.end()
            if end < len(source.text) and source.text[end] in '»”"':
                end += 1
            label = " ".join((before[match.start():] + source.text[occurrence.start():end]).split())
            found.append((source, label))
    if not found or len({name.casefold() for _, name in found}) != 1:
        return None
    label = found[0][1]
    next_id = max((int(n["id"][1:]) for n in data.get("nodes", [])
                   if re.fullmatch(r"N\d+", n["id"])), default=0) + 1
    return {"id": f"N{next_id}", "kind": "proposal", "label": label,
            "source_ids": list(dict.fromkeys(source.id for source, _ in found)),
            "origin": "verified_article_literal"}


def article_measure_facts(data: dict, sources: list, articles: dict, topic: str, *, limit=7):
    """Collega importi a una sola iniziativa nominata nell'articolo verificato.

    Quote e frammenti di etichetta sono SEMPRE letterali. Niente inventati
    fatti economici: la relazione è dichiaratamente contestuale.
    """
    focus = request_focus(topic)
    if not focus or not 1 <= limit <= 12:
        return data
    pattern = re.compile(r"(?<!\w)" + re.escape(focus) + r"(?!\w)", re.I)
    hubs = [node for node in data.get("nodes", [])
            if node.get("kind") in {"proposal", "event"} and pattern.search(node.get("label", ""))]
    if len(hubs) > 1:
        return data
    created_hub = verified_initiative_hub(data, sources, articles, topic) if not hubs else None
    if not hubs and created_hub is None:
        return data
    hub = hubs[0] if hubs else created_hub
    by_id = {s.id: s for s in sources}
    hub_files = {by_id[identity].filename for identity in hub.get("source_ids", []) if identity in by_id}
    metadata = article_scope(sources, articles)
    candidates = [s for s in sources if s.filename in hub_files
                  and s.id in metadata and pattern.search(metadata[s.id].get("title", ""))]
    nodes, edges, seen = list(data["nodes"]), list(data["edges"]), set()
    if created_hub is not None:
        nodes.append(created_hub)
    next_id = max((int(n["id"][1:]) for n in nodes if re.fullmatch(r"N\d+", n["id"])), default=0) + 1
    for source in candidates:
        for sentence in original_sentences(source.text):
            if len(seen) >= limit or len(nodes) >= 24:
                break
            if not 25 <= len(sentence) <= 1200 or not MEASURE.search(sentence):
                continue
            amount = AMOUNT.search(sentence)
            if not amount or sentence not in " ".join(source.text.split()):
                continue
            header = SECTION.match(sentence)
            section = header.group(1).strip() if header else ""
            if section.casefold() in {"il provvedimento", "il ddl", "la legge", "il programma", "il piano"}:
                section = ""
            label = amount.group(0)
            if section:
                label = section + " · " + label
            else:
                trailing = re.match(r"\s+per\s+([^,.!?;]{8,52})", sentence[amount.end():], re.I)
                if trailing:
                    label += " per " + trailing.group(1).strip()
            key = (source.filename, label.casefold())
            if key in seen:
                continue
            seen.add(key)
            nid = f"N{next_id}"
            next_id += 1
            nodes.append({"id": nid, "kind": "measure", "label": label,
                          "source_ids": [source.id], "section": section, "amount": amount.group(0)})
            edges.append({"from_id": hub["id"], "to_id": nid, "kind": "contextual",
                          "label": "misura descritta", "source_ids": [source.id],
                          "evidence": [{"source_id": source.id, "quote": sentence}],
                          "context_scope": "same_verified_article"})
        if len(seen) >= limit:
            break
    return {**data, "nodes": nodes, "edges": edges} if len(edges) > len(data["edges"]) else data
