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
    + r"\s+(?:(?:definitivamente|formalmente|ufficialmente)\s+)?"
    + r"(?:(?:il|lo|la|i|gli|le|un|una|l['’])\s*)?"
    + r"(?P<object>"
    + r"(?:(?:disegno|proposta)\s+di\s+legge|ddl|decreto|riforma|"
    + r"piano|progetto|programma|finanziamento|investimento|"
    + r"stanziamento|intervento|misura|accordo|emendamento|legge)"
    + r"(?:\s+(?:[«“\"][^»”\"]{3,60}[»”\"]|(?-i:[A-ZÀ-ÖØ-Þ])[\w’'-]+|"
    + r"(?:sul|sulla|dei|delle|del|della|per)\s+\w+)){1,4}"
    + r")",
    re.I,
)
# Collegamento fra un provvedimento specifico e risorse quantificate.
# Solo se soggetto, azione e importo sono tutti nella stessa frase originale.
FUNDS_PATTERN = re.compile(
    r"(?<!\w)(?:(?:il|la|lo|l['’])\s*)?"
    r"(?P<actor>(?:(?:disegno|proposta)\s+di\s+legge|ddl|decreto|"
    r"programma|piano|progetto)\s+"
    r"(?:[«“\"][^»”\"]{3,60}[»”\"]|(?-i:[A-ZÀ-ÖØ-Þ])[\w’'-]+))"
    r"\s+(?P<verb>prevede|stanzia|destina|assegna|finanzia)"
    r"\s+(?P<object>(?:oltre|circa|fino\s+a)?\s*"
    r"\d+(?:[.,]\d+)?\s*(?:milion\w*|miliard\w*|euro)"
    r"(?:\s+di\s+euro)?"
    r"(?:\s+per\s+(?:l['’]|il\s+|la\s+|le\s+|gli\s+)?"
    r"[\w’'-]+(?:\s+[\w’'-]+){0,3})?)",
    re.I,
)


# Formulazioni passive frequenti nelle cronache parlamentari.
# "Il disegno di legge X, [apposizione], è stato approvato dal Senato".
# Conserva l'ordine e la voce effettivamente presenti nella citazione.
PASSIVE_PATTERN = re.compile(
    r"(?<!\w)(?P<object>(?:disegno|proposta)\s+di\s+legge\s+"
    r"(?:[«“\"][^»”\"]{3,70}[»”\"]|(?-i:[A-ZÀ-ÖØ-Þ])[\w’'-]+"
    r"(?:\s+(?-i:[A-ZÀ-ÖØ-Þ])[\w’'-]+){0,2}))"
    r"(?:\s*,\s*[^,.;!?]{3,140}\s*,)?"
    r"\s+(?P<verb>è\s+stato\s+(?:approvato|varato|presentato|respinto)\s+d(?:al|alla))"
    r"\s+(?P<actor>(?:Senato|Camera|Parlamento|Governo|"
    r"Consiglio\s+(?:dei\s+ministri|regionale|comunale)|"
    r"Commissione\s+\w+))\b",
    re.I,
)


# Senza questi nomi non sappiamo a quale provvedimento si riferisca l'azione.
GENERIC_OBJECT = re.compile(
    r"^(?:disegno\s+di\s+legge|proposta\s+di\s+legge|decreto|riforma|"
    r"piano|progetto|programma|finanziamento|investimento|"
    r"stanziamento|intervento|misura|accordo|emendamento|legge)$",
    re.I,
)


# Predicati frequenti nella cronaca nazionale e locale. La forma mostrata
# nel grafo viene sempre copiata dalla frase originale e rivalidata: questa
# lista serve solo a trovare candidati, non a inventare sinonimi o relazioni.
_GENERIC_VERBS = (
    r"(?:approvat[oaie]|respint[oaie]|annunciat[oaie]|presentat[oaie]|"
    r"finanziat[oaie]|stanziat[oaie]|firmat[oaie]|chiest[oaie]|avviat[oaie]|"
    r"inaugurat[oaie]|apert[oaie]|chius[oaie]|sospes[oaie]|annullat[oaie]|"
    r"organizzat[oaie]|realizzat[oaie]|completat[oaie]|pubblicat[oaie]|"
    r"denunciat[oaie]|conquistat[oaie]|vint[oaie]|scopert[oaie]|rilevat[oaie]|"
    r"ottenut[oaie]|lanciat[oaie]|propost[oaie]|adottat[oaie]|sostenut[oaie]|"
    r"confermat[oaie]|bloccat[oaie]|convocat[oaie]|segnalat[oaie]|raggiunt[oaie]|"
    r"ridott[oaie]|aumentat[oaie]|rilanciat[oaie]|selezionat[oaie]|votat[oaie]|"
    r"sottolineat[oaie]|illustrat[oaie]|registrat[oaie]|cresciut[oaie]|calat[oaie]|"
    r"fallit[oaie]|riuscit[oaie]|rimast[oaie]|evidenziat[oaie]|indicat[oaie]|"
    r"contestat[oaie]|criticat[oaie]|rinviat[oaie]|comunicat[oaie])"
)
_GENERIC_PRESENT_VERBS = (
    r"(?:approva|approvano|respinge|respingono|annuncia|annunciano|"
    r"presenta|presentano|prevede|prevedono|stanzia|stanziano|"
    r"destina|destinano|finanzia|finanziano|chiede|chiedono|"
    r"sollecita|sollecitano|dichiara|dichiarano|sostiene|sostengono|"
    r"critica|criticano|contesta|contestano|denuncia|denunciano|"
    r"segnala|segnalano|rileva|rilevano|registra|registrano|"
    r"conferma|confermano|indica|indicano|evidenzia|evidenziano|"
    r"dimostra|dimostrano|apre|aprono|apra|chiude|chiudono|"
    r"coinvolge|coinvolgono|colpisce|colpiscono|vince|vincono|"
    r"conquista|conquistano|ottiene|ottengono|propone|propongono|"
    r"firma|firmano|vota|votano|discute|discutono|rinvia|rinviano|"
    r"sospende|sospendono|blocca|bloccano|avvia|avviano|"
    r"inaugura|inaugurano|lancia|lanciano|rafforza|rafforzano|"
    r"riduce|riducono|aumenta|aumentano|cresce|crescono|"
    r"cala|calano|sale|salgono|scende|scendono|organizza|organizzano|"
    r"realizza|realizzano|completa|completano|pubblica|pubblicano|"
    r"scopre|scoprono|risulta|risultano|fallisce|falliscono)"
)
_GENERIC_AUXILIARY = (
    r"(?:(?:ha|hanno|aveva|avevano)\s+" + _GENERIC_VERBS + r"|"
    r"(?:è|sono|era|erano)\s+(?:(?:stato|stata|stati|state)\s+)?"
    + _GENERIC_VERBS + r")"
)
_DETERMINER = r"(?:(?:il|lo|la|i|gli|le|un|una|uno|questo|questa|questi|queste|tale|suddetto|suddetta)\s+|l['’])?"
_POSTVERB_ADJUNCT = (
    r"(?:senza\s+(?:nessun[oa]?|alcun[oa]?)\s+"
    r"(?:(?!(?:il|lo|la|i|gli|le|un|una|uno)\b)[\w’'-]+\s+){1,3})?"
)
GENERIC_ACTION_PATTERN = re.compile(
    r"^\s*" + _DETERMINER
    + r"(?P<actor>[\wÀ-ÿ’'-]+(?:\s+(?!(?:ha|hanno|aveva|avevano|è|sono|era|erano|non)\b)[\wÀ-ÿ’'-]+){0,6})"
    + r"\s+(?P<verb>(?:" + _GENERIC_AUXILIARY + r"|" + _GENERIC_PRESENT_VERBS + r"))"
    + r"\s+(?:(?:oggi|ieri|poi|già|ufficialmente|definitivamente)\s+)?"
    + _POSTVERB_ADJUNCT + _DETERMINER
    + r"(?P<object>(?:[^,.;!?]|\d,\d){6,150}?)\s*[.?!]?\s*$",
    re.I,
)
_GENERIC_CLAUSE = re.compile(r"^(?:che|se|come)\b|\b(?:sarebbe|avrebbe|potrebbe|dovrebbe)\b", re.I)
_GENERIC_TAIL = re.compile(r"\s+(?:durante|davanti\s+(?:a|al|allo|alla|ai|agli|alle)|presso|dopo|grazie\s+a|in\s+occasione\s+di)\b", re.I)


def generic_action(passage: str):
    """Conserva triple letterali anche dopo brevi incisi introduttivi.

    Un inciso non deve attraversare un'altra proposizione: si accetta
    soltanto un breve complemento iniziale senza verbo finito.
    """
    # Non dividere i decimali degli importi (1,1 milioni). L'inciso
    # iniziale si separa solo quando dopo la virgola comincia un soggetto.
    clauses = re.split(r",\s+(?=[A-ZÀ-ÖØ-Þ])", passage, maxsplit=1)
    candidates = [clauses[0].strip()]
    if (len(clauses) > 1 and 1 <= len(clauses[0].split()) <= 8
            and not re.search(
                r"\b(?:ha|hanno|aveva|avevano|è|sono|era|erano|"
                r"chiede|annuncia|dichiara|approva|nega|ritiene)\b",
                clauses[0], re.I)
            and re.match(
                r"^(?:per|in|nel|nella|dopo|prima|durante|"
                r"intanto|inoltre|tuttavia|così|quindi|pertanto)\b",
                clauses[0], re.I)):
        candidates.append(clauses[1])
    for candidate in candidates:
        # Aperture frequenti nei quotidiani, senza alterare la citazione
        # verificata usata dal validatore.
        candidate = candidate.strip(' \t«»“”"')
        candidate = re.sub(r"^(?:oggi|ieri|stamani|stamattina)\s+",
                           "", candidate, flags=re.I)
        match = GENERIC_ACTION_PATTERN.match(candidate)
        if match is None:
            continue
        actor, verb = match.group("actor", "verb")
        object_name = _GENERIC_TAIL.split(match.group("object"), maxsplit=1)[0].strip(' \t«»“”"')
        if (_GENERIC_CLAUSE.search(object_name) or len(object_name) < 7
                or len(actor) < 3 or actor.casefold() == object_name.casefold()
                or re.match(r"^(?:nei|nelle|nella|nel|durante|dopo|prima|oggi|ieri|"
                            r"secondo|per|in)\b", actor, re.I)):
            continue
        # Anche con inciso, il validatore controlla l'intera citazione.
        if documented_relation(actor, verb, object_name, passage):
            return actor, verb, object_name
    return None


def original_sentences(text: str):
    """Ricompone le righe tipografiche senza attraversare i paragrafi.

    I PDF giornalistici spezzano una frase su più righe: dividerla ad
    ogni newline elimina soggetto, verbo e complemento. I passaggi
    restano contigui nel testo originale a spazi normalizzati.
    """
    for paragraph in re.split(r"\n\s*\n+", text):
        normalized = " ".join(paragraph.split())
        if not normalized:
            continue
        for sentence in re.split(r"(?<=[.!?;])\s+", normalized):
            if sentence:
                yield sentence


def complete_salient_facts(raw: dict, sources: list, topic: str, *,
                           max_nodes: int = 16, max_edges: int = 24,
                           article_titles=None) -> dict:
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
        title = (article_titles or {}).get(source.id, {}).get("title", "")
        if not matcher.score(source.text) and not matcher.score(title):
            continue
        for passage in original_sentences(source.text):
            passage = passage.strip()
            if len(passage) < 30 or len(passage) > 1400 or len(edges) >= max_edges:
                continue
            # Prima le azioni/proposte già riconosciute. Per le altre
            # rubriche, prova una tripla soggetto-verbo-oggetto conservativa.
            matches = (list(ACTION_PATTERN.finditer(passage))
                       + list(FUNDS_PATTERN.finditer(passage))
                       + list(PASSIVE_PATTERN.finditer(passage)))
            generic = generic_action(passage) if not matches else None
            for match in (matches if matches else [None] if generic else []):
                actor, verb, object_name = (
                    (match.group(key).strip() for key in ("actor", "verb", "object"))
                    if match is not None else generic)
                passive = match is not None and match.re is PASSIVE_PATTERN
                if passive:
                    # La frase cita il provvedimento (soggetto grammaticale)
                    # e poi l'istituzione agente. Non invertire il predicato.
                    actor, object_name = object_name, actor
                if GENERIC_OBJECT.fullmatch(object_name) or actor.casefold() == object_name.casefold():
                    continue
                if not documented_relation(actor, verb, object_name, passage):
                    continue
                missing = [v for v in (actor, object_name) if v.casefold() not in labels]
                if len(items) + len(missing) > max_nodes or len(edges) >= max_edges:
                    continue
                evidence = [{"source_id": source.id, "quote": passage}]
                # La qualifica esplicita distingue una persona da
                # un'istituzione; senza prova non indovinare il ruolo.
                role = (re.search(
                    r"\b(?:ministro|ministra|senatore|senatrice|sindaco|sindaca|"
                    r"presidente|deputato|deputata)\s+" + re.escape(actor) + r"\b",
                    match.group(0), re.I) if match is not None else None)
                if match is None:
                    if re.search(r"\b(?:senato|camera|parlamento|governo|comune|regione|"
                                 r"ministero|commissione|sindacat|confartigianato|"
                                 r"associazione|comitato|azienda|impresa|società|"
                                 r"università|museo|squadra|club|vigili\s+del\s+fuoco)\b",
                                 actor, re.I):
                        actor_kind = "organization"
                    elif re.search(r"\b(?:provvedimento|disegno\s+di\s+legge|proposta|"
                                   r"decreto|riforma|piano|progetto|programma|"
                                   r"accordo|contratto|legge)\b", actor, re.I):
                        actor_kind = "proposal"
                    elif re.search(r"\b(?:incidente|scontro|alluvione|incendio|"
                                   r"manifestazione|protesta|vittime)\b", actor, re.I):
                        actor_kind = "event"
                    else:
                        actor_kind = "concept"
                else:
                    actor_kind = ("proposal" if match.re in {FUNDS_PATTERN, PASSIVE_PATTERN}
                                  else "person" if role else "organization")
                measure = re.match(
                    r"(?:finanziamento|stanziamento|investimento|intervento|misura)\b",
                    object_name, re.I)
                if passive:
                    object_kind = "organization"
                elif measure or (match is not None and match.re is FUNDS_PATTERN):
                    object_kind = "measure"
                elif re.match(r"(?:disegno\s+di\s+legge|proposta|decreto|riforma|"
                              r"piano|progetto|programma|accordo|contratto|legge)\b",
                              object_name, re.I):
                    object_kind = "proposal"
                elif match is None:
                    object_kind = "concept"
                else:
                    object_kind = "proposal"
                for label, kind in ((actor, actor_kind), (object_name, object_kind)):
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


def complete_verified_relations(data: dict, sources: list, topic: str, *,
                                article_titles=None, contexts=None) -> dict:
    """Completa i soli archi fattuali dopo la validazione della mappa AI.

    La quota di 16 nodi dello schema Gemini non deve cancellare una tripla
    esplicita nelle fonti. Ogni aggiunta passa separatamente dagli stessi
    controlli di citazione e pertinenza; non crea fatti dalla vicinanza.
    """
    from edicola.knowledge_validation import validate_map
    from edicola.knowledge_relevance import relevant_map

    # I chunk già coinvolti in una relazione verificata tra passaggi
    # adiacenti non vengono riesaminati singolarmente: si evitano triple
    # parziali che duplicano o spezzano il fatto già ricostruito.
    protected = {source_id for edge in data.get("edges", [])
                 if edge.get("kind") == "documented" and edge.get("adjacent_evidence")
                 for source_id in edge.get("source_ids", [])}
    candidates = [source for source in sources if source.id not in protected]
    if not candidates:
        return data
    candidate_contexts = ({source.id: contexts[source.id] for source in candidates
                           if contexts and source.id in contexts}
                          if contexts is not None else None)
    raw = complete_salient_facts({"nodes": [], "edges": []}, candidates, topic,
                                 article_titles=article_titles)
    if not raw["edges"]:
        return data
    checked, _ = validate_map(raw, candidates, contexts=candidate_contexts)
    relevant, _ = relevant_map(checked, raw, candidates, Topic(topic),
                               contexts=candidate_contexts)
    if not relevant["edges"]:
        return data

    nodes, edges = list(data.get("nodes", [])), list(data.get("edges", []))
    by_id = {node["id"]: node for node in relevant["nodes"]}
    next_id = max((int(node["id"][1:]) for node in nodes
                   if re.fullmatch(r"N\d+", node["id"])), default=0) + 1
    mappings = {}
    for edge in relevant["edges"]:
        ends = []
        for identity in (edge["from_id"], edge["to_id"]):
            if identity not in mappings:
                node = by_id[identity]
                # Lo stesso nome in articoli diversi può rappresentare
                # soggetti distinti: unisci soltanto con una fonte comune.
                reusable = next((old for old in nodes
                                 if old["label"].casefold() == node["label"].casefold()
                                 and set(old.get("source_ids", []))
                                 & set(node.get("source_ids", []))), None)
                if reusable is None:
                    reusable = {**node, "id": f"N{next_id}"}
                    nodes.append(reusable)
                    next_id += 1
                mappings[identity] = reusable["id"]
            ends.append(mappings[identity])
        signature = (ends[0], ends[1], edge["kind"], edge["label"].casefold())
        if any((old["from_id"], old["to_id"], old["kind"],
                old["label"].casefold()) == signature for old in edges):
            continue
        edges.append({**edge, "from_id": ends[0], "to_id": ends[1]})
    return {**data, "nodes": nodes, "edges": edges}
