"""Montaggio editoriale della sola Mappa.

Il grafo principale dà precedenza a eventi/provvedimenti e relazioni
fattuali; articoli e menzioni restano navigabili, ma non sostituiscono
gli avvenimenti. Non aggiunge mai archi o fatti.
"""
from collections import Counter
import re

from edicola.knowledge_relevance import terms


CORE_KINDS = {"event", "measure", "proposal"}
SOURCE_KINDS = {"article", "source"}
EDGE_VALUE = {"documented": 7, "contextual": 5, "thematic": 4, "mention": 1}



def informative_theme(edge: dict) -> bool:
    """Un tema di una parola non può essere un semplice settore o aggettivo.

    Denominazioni specifiche composte sono ammesse. Un nome singolo passa
    solo se appare come nome distintivo CamelCase o sigla nella prova.
    """
    label = (edge.get("topic") or edge.get("label") or "").strip()
    distinct = terms(label)
    if len(distinct) >= 2:
        return True
    if len(distinct) != 1:
        return False
    for item in edge.get("evidence", []):
        quote = item.get("quote", "") if isinstance(item, dict) else ""
        for token in re.findall(r"\b[A-ZÀ-ÖØ-Þ][\w'-]+\b", quote):
            if (terms(token) == distinct and (
                    re.search(r"[a-zà-öø-ÿ][A-ZÀ-ÖØ-Þ]", token)
                    or (len(token) >= 3 and token.isupper()))):
                return True
    return False



def _entity_key(label: str) -> str:
    """Equivalenze tipografiche senza sinonimi o deduzioni tematiche."""
    return " ".join(label.strip().strip('«»“”"').casefold().split())


def _same_story_entity(first: dict, second: dict) -> bool:
    """Unisce solo denominazioni compatibili, evitando co-referenze supposte."""
    if first["id"] == second["id"]:
        return False
    if first["kind"] in SOURCE_KINDS or second["kind"] in SOURCE_KINDS:
        return False
    a, b = _entity_key(first["label"]), _entity_key(second["label"])
    overlap = bool(set(first.get("source_ids", [])) & set(second.get("source_ids", [])))
    kinds = {first["kind"], second["kind"]}
    if first["kind"] != second["kind"] and "concept" not in kinds:
        return False
    if first["kind"] == "person" or second["kind"] == "person":
        # Nomi incompleti od omonimi richiedono disambiguazione a monte.
        return False
    if a == b:
        # A parità di testo, una denominazione distinta condivisa da una
        # fonte non identifica un altro soggetto. Nomi propri distintivi
        # (CamelCase) sono riutilizzabili anche fra edizioni diverse.
        named = any(re.search(r"[a-zà-öø-ÿ][A-ZÀ-ÖØ-Þ]", n["label"])
                    for n in (first, second))
        return overlap or named
    if first["kind"] == second["kind"] == "organization" and overlap:
        short, full = sorted((a, b), key=len)
        # Solo forma breve e qualifica istituzionale nello stesso documento,
        # senza dedurre equivalenze dalla semplice appartenenza geografica.
        suffix = full[len(short):] if full.startswith(short + " ") else ""
        return bool(re.fullmatch(
            r"\s+(?:della|del|dei|degli)\s+[a-zà-öø-ÿ]+", suffix
        ) and not any(
            n in {"ministero", "regione", "comune", "provincia", "consiglio", "commissione"}
            for n in (short,)
        ))
    return False


def _consolidate_story_entities(data: dict) -> dict:
    """Accorpa alias verificati soltanto nella vista, mantenendo ogni prova.

    Non aggiunge relazioni, non identifica genericamente 'provvedimento'
    con una legge e non modifica il grafo originale salvato in cache.
    """
    original = data.get("nodes", [])
    if len(original) < 2:
        return data
    aliases = {node["id"]: node["id"] for node in original}

    def root(identity):
        while aliases[identity] != identity:
            identity = aliases[identity]
        return identity

    rank_kind = {"proposal": 7, "measure": 6, "organization": 5,
                 "event": 4, "place": 3, "person": 2, "concept": 1}

    def priority(node):
        return (rank_kind.get(node["kind"], 0),
                len(_entity_key(node["label"])), len(node.get("source_ids", [])))

    for i, first in enumerate(original):
        for second in original[i+1:]:
            if not _same_story_entity(first, second):
                continue
            a, b = root(first["id"]), root(second["id"])
            if a == b:
                continue
            representative = {node["id"]: node for node in original}
            best = max((a, b), key=lambda x: priority(representative[x]))
            aliases[a if best == b else b] = best

    if all(root(identity) == identity for identity in aliases):
        return data

    merged_nodes = {}
    for node in original:
        identity = root(node["id"])
        if identity not in merged_nodes:
            representative = next(n for n in original if n["id"] == identity)
            merged_nodes[identity] = {**representative,
                                      "source_ids": list(representative.get("source_ids", []))}
        target = merged_nodes[identity]
        target["source_ids"] = list(dict.fromkeys(
            [*target.get("source_ids", []), *node.get("source_ids", [])]))

    grouped_edges = {}
    for edge in data.get("edges", []):
        start, end = root(edge["from_id"]), root(edge["to_id"])
        if start == end:
            continue
        signature = (start, end, edge["kind"], edge["label"], edge.get("topic"),
                     edge.get("context_scope"))
        if signature not in grouped_edges:
            grouped_edges[signature] = {**edge, "from_id": start, "to_id": end,
                                        "source_ids": list(edge.get("source_ids", [])),
                                        "evidence": list(edge.get("evidence", []))}
            continue
        saved = grouped_edges[signature]
        saved["source_ids"] = list(dict.fromkeys(
            [*saved["source_ids"], *edge.get("source_ids", [])]))
        for proof in edge.get("evidence", []):
            if proof not in saved["evidence"]:
                saved["evidence"].append(proof)
    return {**data, "nodes": list(merged_nodes.values()),
            "edges": list(grouped_edges.values())}


def story_graph(data: dict, topic: str, *, limit: int = 14, sources=()) -> dict:
    """Presenta relazioni informative, non un catalogo di menzioni.

    Solo gli archi documentati rappresentano azioni. Un nesso tematico
    non può ripetere altre cinque volte la stessa parola sullo stesso
    gruppo di nodi: entra solo come ponte fra notizie distinte.
    Articoli e PDF restano disponibili dai dettagli e dalle fonti.
    """
    if not 2 <= limit <= 20:
        raise ValueError("Numero di nodi del grafo fuori intervallo.")
    # La stessa entità può ricomparire in diverse frasi e con virgolette
    # differenti. Consolidamento esclusivamente nella vista editoriale.
    display = _consolidate_story_entities(data)
    nodes = {n["id"]: n for n in display.get("nodes", [])}
    edges = [e for e in display.get("edges", [])
             if e.get("from_id") in nodes and e.get("to_id") in nodes]
    if not nodes or not edges:
        return {"nodes": [], "edges": []}
    matched = terms(topic)
    source_files = {source.id: source.filename for source in sources}
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
        return (EDGE_VALUE.get(edge["kind"], 0) * 20
                + node_value(edge["from_id"]) + node_value(edge["to_id"])
                + len(set(edge.get("source_ids", []))))

    factual = sorted((e for e in edges if e["kind"] == "documented"),
                     key=edge_value, reverse=True)
    contextual = sorted((e for e in edges if e["kind"] == "contextual"),
                        key=edge_value, reverse=True)
    thematic = sorted((e for e in edges if e["kind"] == "thematic"),
                      key=edge_value, reverse=True)
    chosen, selected, used_themes = [], set(), set()
    parent = {identity: identity for identity in nodes}

    def root(identity):
        while parent[identity] != identity:
            identity = parent[identity]
        return identity

    def take(edge):
        endpoints = {edge["from_id"], edge["to_id"]}
        if len(selected | endpoints) > limit:
            return False
        chosen.append(edge)
        selected.update(endpoints)
        parent[root(edge["from_id"])] = root(edge["to_id"])
        return True

    for edge in factual:
        take(edge)
    # Un intervento con importo forma un'unica unità editoriale:
    # proposta -> obiettivo -> cifra. Evita di occupare il limite con
    # soli obiettivi lasciando fuori i dettagli quantitativi.
    used_context = set()
    for detail in contextual:
        child = nodes[detail["to_id"]]
        origin_node = nodes[detail["from_id"]]
        if child["kind"] != "measure" or origin_node["kind"] != "concept":
            continue
        introductory = next((edge for edge in contextual
                             if edge["to_id"] == detail["from_id"]
                             and nodes[edge["from_id"]]["kind"] in {"proposal", "event"}),
                            None)
        if introductory is None:
            continue
        required = {introductory["from_id"], introductory["to_id"], detail["to_id"]}
        if len(selected | required) > limit:
            continue
        if id(introductory) not in used_context:
            take(introductory)
            used_context.add(id(introductory))
        if id(detail) not in used_context:
            take(detail)
            used_context.add(id(detail))
    # I fatti narrativi di un articolo verificato possono formare una
    # componente indipendente anche se esiste già una tripla fattuale:
    # altrimenti una mappa come "Senato -> disegno di legge" nasconde
    # tutti gli approfondimenti documentati sull'argomento.
    independent_stories = {}
    for edge in contextual:
        if id(edge) in used_context:
            continue
        connected = edge["from_id"] in selected or edge["to_id"] in selected
        scope = edge.get("context_scope")
        story = (scope in {"same_verified_article", "same_source_paragraph"}
                 and nodes[edge["from_id"]]["kind"] == "event")
        if not factual or connected:
            take(edge)
        elif story:
            independent_stories.setdefault(edge["from_id"], []).append(edge)
    # Non limitare a due vicende: prima un fatto per ogni articolo, poi
    # gli approfondimenti, sempre entro il numero massimo di nodi.
    while any(independent_stories.values()):
        progressed = False
        for group in independent_stories.values():
            if group and take(group.pop(0)):
                progressed = True
        if not progressed:
            break

    for edge in thematic:
        # La co-menzione nella stessa edizione non basta per un rapporto
        # giornalisticamente interessante fra due protagonisti.
        source_ids = edge.get("source_ids", [])
        if source_files and len({source_files.get(sid, sid) for sid in source_ids}) < 2:
            continue
        name = (edge.get("topic") or edge["label"]).strip().casefold()
        if not informative_theme(edge) or not name or name in used_themes:
            continue
        left, right = edge["from_id"], edge["to_id"]
        if root(left) == root(right):
            continue  # Nessuna diagonale che ripeta una vicenda già collegata.
        if factual and left not in selected and right not in selected:
            continue
        if take(edge):
            used_themes.add(name)
        if len(used_themes) >= 2:
            break

    # Menziona e i titoli degli articoli sono metadati utili per la lettura,
    # non collegamenti salienti da mostrare come struttura principale.
    # Se mancano fatti o ponti indipendenti, evitare una finta Mappa.
    identities = {identity for edge in chosen
                  for identity in (edge["from_id"], edge["to_id"])}
    order = sorted(identities, key=lambda i: (nodes[i]["kind"] in SOURCE_KINDS,
                                             -node_value(i), i))
    return {"nodes": [nodes[identity] for identity in order],
            "edges": chosen}


def story_focus(data: dict, topic: str) -> str | None:
    """Il centro è un fatto/provvedimento, non un titolo di giornale."""
    nodes = data.get("nodes", [])
    if not nodes:
        return None
    matches = terms(topic)
    factual = Counter(identity for edge in data.get("edges", [])
                      if edge["kind"] == "documented"
                      for identity in (edge["from_id"], edge["to_id"]))
    return max(nodes, key=lambda n: (n["kind"] in CORE_KINDS,
                                     factual[n["id"]],
                                     len(terms(n["label"]) & matches),
                                     n["kind"] not in SOURCE_KINDS,
                                     -nodes.index(n)))["id"]
