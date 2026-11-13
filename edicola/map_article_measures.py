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


_GENERIC_SECTIONS = {
    "il provvedimento", "il ddl", "la legge", "il programma", "il piano",
    "la misura", "le misure", "le risorse", "le novità", "il senato",
}
_PURPOSE_AFTER = re.compile(
    r"\bper\s+((?:l['’]|il\s+|la\s+|le\s+|gli\s+|i\s+)?[^,.;!?]{7,85})",
    re.I,
)


def described_purpose(sentence: str, amount) -> tuple[str, str] | None:
    """Richiede destinatario/obiettivo esplicito nella stessa citazione.

    '1 milione' senza indicazioni non è una misura consultabile e non va
    automaticamente attribuito all'iniziativa soltanto per la pagina.
    """
    header = SECTION.match(sentence)
    if header:
        title = " ".join(header.group(1).split()).strip(" «»“”\"")
        if title.casefold() not in _GENERIC_SECTIONS and len(title.split()) >= 2:
            return title, "section"
    match = _PURPOSE_AFTER.search(sentence, amount.end())
    if match:
        purpose = " ".join(match.group(1).split()).strip(" «»“”\"")
        if len(purpose) >= 8 and len(purpose.split()) <= 15:
            return purpose, "beneficiary"
    return None


def article_measure_facts(data: dict, sources: list, articles: dict, topic: str, *, limit=7):
    """Espone interventi leggibili: iniziativa -> scopo -> importo.

    Il legame col provvedimento è di contesto, mai una decisione o una
    responsabilità inferita. Ogni scopo e ogni cifra è letterale nella
    stessa citazione originale e appartiene a una fonte verificata.
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
    nodes, edges = list(data["nodes"]), list(data["edges"])
    if created_hub is not None:
        nodes.append(created_hub)
    next_id = max((int(n["id"][1:]) for n in nodes
                   if re.fullmatch(r"N\d+", n["id"])), default=0) + 1
    purposes = {}
    seen_amounts = set()
    for source in candidates:
        for sentence in original_sentences(source.text):
            if len(seen_amounts) >= limit or len(nodes) + 2 > 24:
                break
            if not 25 <= len(sentence) <= 1200 or not MEASURE.search(sentence):
                continue
            amount = AMOUNT.search(sentence)
            if not amount or sentence not in " ".join(source.text.split()):
                continue
            described = described_purpose(sentence, amount)
            if not described:
                continue
            purpose, scope = described
            amount_text = " ".join(amount.group(0).split())
            # Mai unire due importi uguali destinati a interventi differenti.
            identity = (source.filename, purpose.casefold(), amount_text.casefold())
            if identity in seen_amounts:
                continue
            seen_amounts.add(identity)
            evidence = [{"source_id": source.id, "quote": sentence}]
            purpose_key = (source.filename, purpose.casefold())
            if purpose_key not in purposes:
                purpose_id = f"N{next_id}"
                next_id += 1
                purposes[purpose_key] = purpose_id
                nodes.append({"id": purpose_id, "kind": "concept", "label": purpose,
                              "source_ids": [source.id], "origin": "literal_purpose"})
                edges.append({"from_id": hub["id"], "to_id": purpose_id,
                              "kind": "contextual", "label": "ambito dell'intervento",
                              "source_ids": [source.id], "evidence": evidence,
                              "context_scope": "same_verified_article"})
            else:
                purpose_id = purposes[purpose_key]
            measure_id = f"N{next_id}"
            next_id += 1
            nodes.append({"id": measure_id, "kind": "measure", "label": amount_text,
                          "source_ids": [source.id], "section": purpose if scope == "section" else "",
                          "purpose": purpose, "amount": amount_text})
            relation = ("risorse stanziate" if re.search(r"\bstanziat[oaie]\b", sentence, re.I)
                        else "risorse previste" if re.search(r"\bprevist[oaie]\b", sentence, re.I)
                        else "importo riportato")
            edges.append({"from_id": purpose_id, "to_id": measure_id,
                          "kind": "contextual", "label": relation,
                          "source_ids": [source.id], "evidence": evidence,
                          "context_scope": "same_verified_article"})
        if len(seen_amounts) >= limit:
            break
    # Se non sono emersi interventi attribuibili, non mostrare neanche
    # un hub recuperato automaticamente e privo di relazioni.
    return {**data, "nodes": nodes, "edges": edges} if len(edges) > len(data["edges"]) else data
