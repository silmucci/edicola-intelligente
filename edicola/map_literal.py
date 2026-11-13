"""Completa archi letterali fra soli nodi già validati, dopo JSON AI valido."""

import re
from edicola.map_context import contiguous, joined_proofs
from edicola.map_relations import documented_relation, PARTY
from edicola.archive import IndexChunk

# Denominazione identificabile nella stessa citazione, non inferita dalla domanda.
# Richiede maiuscola iniziale reale per evitare 'disegno di legge sul ...'.
_NAMED_BILL = re.compile(
    r"(?<!\w)(?:disegno|proposta)\s+di\s+legge\s+"
    r"(?P<name>(?:[«“\"][A-ZÀ-ÖØ-Þ][\w’'-]*(?:\s+[A-ZÀ-ÖØ-Þ][\w’'-]*){0,3}[»”\"]"
    r"|[A-ZÀ-ÖØ-Þ][\w’'-]*(?:\s+[A-ZÀ-ÖØ-Þ][\w’'-]*){0,3}))"
)


def named_bill_in_evidence(evidence):
    """Espande solo 'disegno di legge' quando una citazione ne contiene
    un'unica denominazione completa, letterale e non ambigua.
    """
    names = set()
    for proof in evidence:
        if not isinstance(proof, dict) or not isinstance(proof.get("quote"), str):
            continue
        for match in _NAMED_BILL.finditer(proof["quote"]):
            names.add(match.group())
    return next(iter(names)) if len(names) == 1 else None


def refine_proposal_nodes(raw):
    """Distingue le leggi per nome senza alterare prove o identificativi."""
    for node in raw.get("nodes", []):
        if not isinstance(node, dict) or node.get("kind") not in {"proposal", "measure"}:
            continue
        label = node.get("label")
        if not isinstance(label, dict) or not isinstance(label.get("text"), str):
            continue
        if label["text"].casefold().strip() not in {"disegno di legge", "proposta di legge"}:
            continue
        specific = named_bill_in_evidence(label.get("evidence", []))
        if specific:
            label["text"] = specific
    return raw


PREDICATES = re.compile(r"\b(?:(?:ha|hanno)\s+(?:presentato|sostenuto|criticato|dichiarato\s+inammissibile)|"
                        r"(?:(?:è|sono)\s+stat[oaie]\s+)?(?:presentat[oaie]|sostenut[oaie]|dichiarat[oaie]\s+inammissibil[ei])\s+(?:anche\s+)?(?:dal|dalla|dai|dalle|da)|"
                        r"(?:ha\s+esaminato|esamina|riguarda|riguardano|propone|sostiene|critica|è\s+esponente\s+di|deputato\s+del|senatore\s+del)|"
                        r"(?:(?:ha|hanno)\s+(?:approvato|annunciato|proposto|finanziato|stanziato|deciso|varato|presentato|incontrato|chiesto|commentato|illustrato|promosso|difeso|sollecitato|discusso)|"
                        r"approva|annuncia|finanzia|guida|presiede|convoca|incontra|commenta|illustra|promuove|difende|sollecita|discute|"
                        r"(?:è|sono)\s+(?:guidat[oaie]|presiedut[oaie])\s+da(?:l|lla|i|lle)?)|"
                        r"presentat[oaie]\s+per\s+(?:garantire|assicurare|tutelare)\s+la\s+(?:salvaguardia|sopravvivenza|tutela)\s+(?:dei|degli)(?:\s+(?:quattro|tre|due))?)\b", re.I)


def complete_nodes(nodes, sources, *, accepted_ids=None):
    """Candidati nominali da frasi con un'entità già estratta: tutti rivalidati."""
    result = list(nodes)
    labels = {n["label"]["text"].casefold() for n in nodes if isinstance(n, dict) and (accepted_ids is None or n.get("id") in accepted_ids) and isinstance(n.get("label"), dict) and isinstance(n["label"].get("text"), str)}
    anchors = set(labels)
    name = r"(?!Il\b|La\b|Lo\b|Un\b|Una\b)[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ’'-]+"
    person = re.compile(r"\b(?i:deputato|senatore|senatrice|consigliere|consigliera)(?:\s+(?i:di|del|della)\s+(?i:" + PARTY + r"))?\s+(" + name + r"(?:\s+" + name + r"){1,2})\b")
    institution = re.compile(
        r"\b(?:(?:Commissione|Ministero)\s+(?:(?:dei|delle|di|del|della)\s+)?(?:[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+|ministri|giustizia|bilancio)"
        r"(?:\s+(?:di|del|dei)\s+[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+)?"
        r"|Consiglio\s+(?:dei\s+ministri|di\s+stato|regionale|comunale|provinciale|superiore\s+della\s+magistratura))\b", re.I)
    party = re.compile(r"\b(?:" + PARTY + r")\b", re.I)
    proposal = re.compile(r"\b(?:emendamento|disegno di legge|proposta di legge)\b", re.I)
    topic = re.compile(r"\b(?:tribunali|presidi giudiziari)\b", re.I)
    next_id = max([int(n.get("id", "N0")[1:]) for n in nodes if isinstance(n, dict) and re.fullmatch(r"N\d+", str(n.get("id", "")))] or [0]) + 1
    for source in sources:
        for quote in re.split(r"(?<=[.!?;])\s+|\n", source.text):
            if not 20 <= len(quote) <= 1800 or not any(re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", quote, re.I) for label in anchors):
                continue
            candidates = [(m[1], "person") for m in person.finditer(quote)]
            candidates += [(m[0], "organization") for m in institution.finditer(quote)]
            candidates += [(m[0], "organization") for m in party.finditer(quote) if m[0][0].isupper() or "partito" in m[0].casefold()]
            candidates += [(named_bill_in_evidence([{"quote": quote}]) or m[0], "proposal")
                           for m in proposal.finditer(quote)]
            candidates += [(m[0], "concept") for m in topic.finditer(quote)]
            for label, kind in candidates:
                if label.casefold() in labels or len(result) >= 16:
                    continue
                result.append({"id": f"N{next_id}", "kind": kind, "label": {"text": label,
                    "evidence": [{"source_id": source.id, "quote": quote}]}})
                next_id += 1
                labels.add(label.casefold())
    return result


def literal_candidates(nodes, sources, contexts):
    proofs = [{"text": source.text, "evidence": [{"source_id": source.id, "quote": source.text}]} for source in sources]
    for left in sources:
        for right in sources:
            if left.id == right.id or left.id not in contexts or right.id not in contexts:
                continue
            if contiguous(IndexChunk(left.chunk_id, left.text, contexts[left.id]), IndexChunk(right.chunk_id, right.text, contexts[right.id])):
                proofs.extend(joined_proofs([{"source_id": s.id, "quote": s.text} for s in (left, right)], sources, contexts))
    candidates, seen = [], set()
    for proof in proofs:
        for match in PREDICATES.finditer(proof["text"]):
            predicate = match[0]
            for left in nodes:
                for right in nodes:
                    identity = (left["id"], right["id"], predicate.casefold())
                    if left is right or identity in seen or not documented_relation(left["label"], predicate, right["label"], proof["text"]):
                        continue
                    seen.add(identity)
                    candidates.append({"from_id": left["id"], "to_id": right["id"], "kind": "documented",
                        "predicate": predicate, "label": {"text": predicate, "evidence": proof["evidence"]}})
    return candidates[:24]



def _named_themes(evidence):
    """Individazioni nominative specifiche, non semplici etichette di settore."""
    names = {}
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        passage = entry.get("quote", "")
        for match in re.finditer(r"\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ\w-]*\b", passage):
            names[match.group().casefold()] = match.group()
        for match in re.finditer(r"(?<!\w)[«“\"]([^»”\"]{6,60})[»”\"]", passage):
            name = match.group(1).strip()
            if len(name.split()) <= 6:
                names[name.casefold()] = name
    return names


def _anchored_evidence(node, raw, sources, *, limit=5):
    """Testi originali in cui compare il nodo, anche in altri articoli recuperati."""
    evidence, seen = [], set()
    pattern = re.compile(r"(?<!\w)" + re.escape(node["label"]) + r"(?!\w)", re.I)
    for entry in raw.get("label", {}).get("evidence", []):
        if not isinstance(entry, dict):
            continue
        key = (entry.get("source_id"), entry.get("quote"))
        if key not in seen:
            seen.add(key)
            evidence.append(entry)
    for source in sources:
        if len(evidence) >= limit:
            break
        for sentence in re.split(r"(?<=[.!?;])\s+|\n+", source.text):
            if len(sentence) < 20 or not pattern.search(sentence):
                continue
            key = (source.id, sentence)
            if key not in seen:
                seen.add(key)
                evidence.append({"source_id": source.id, "quote": sentence})
            if len(evidence) >= limit:
                break
    return evidence[:limit]


def semantic_candidates(nodes, raw_nodes, topic, *, sources=(), vectors=None,
                        existing_edges=(), limit=8):
    """Associazioni tra fatti specifici presenti in prove indipendenti.

    NON ricicla "agricoltura"/"politica"/"lavoro" dalla domanda come
    presunti collegamenti. Cerca un'identità nominativa o un tema preciso
    nei passaggi in cui sono effettivamente citati i due estremi.
    """
    from itertools import combinations
    from edicola.map_relations import contextual_theme, semantic_terms
    from edicola.knowledge_relevance import broad_map_topic

    by_id = {item["id"]: item for item in raw_nodes if isinstance(item, dict)
             and isinstance(item.get("id"), str)}
    requested = [word for word in re.findall(r"[^\W\d_]+", topic)
                 if semantic_terms(word) and not broad_map_topic(word)]
    candidates, already = [], {frozenset((edge["from_id"], edge["to_id"]))
                               for edge in existing_edges}
    for left, right in combinations(nodes, 2):
        # Due protagonisti che citano la stessa legge NON hanno per forza
        # un rapporto fra loro. Servono verbi/azioni documentati.
        if left["kind"] in {"person", "organization"} and right["kind"] in {"person", "organization"}:
            continue
        if frozenset((left["id"], right["id"])) in already:
            continue
        if len(candidates) >= limit:
            break
        first, second = by_id.get(left["id"]), by_id.get(right["id"])
        if not first or not second:
            continue
        if left["label"].casefold() in right["label"].casefold() or right["label"].casefold() in left["label"].casefold():
            continue
        first_evidence = _anchored_evidence(left, first, sources)
        second_evidence = _anchored_evidence(right, second, sources)
        named1 = _named_themes(first_evidence)
        named2 = _named_themes(second_evidence)
        named_shared = [named1[term] for term in named1.keys() & named2.keys()
                        if term not in (left["label"].casefold(), right["label"].casefold())
                        and term not in left["label"].casefold()
                        and term not in right["label"].casefold()]
        themes = list(dict.fromkeys(sorted(named_shared, key=lambda x: (-len(x), x))
                                    + requested))
        for theme in themes:
            if broad_map_topic(theme):
                continue
            found = False
            for a in first_evidence:
                for b in second_evidence:
                    evidence = [a, b]
                    if contextual_theme(left["label"], right["label"], theme, evidence, vectors=vectors):
                        candidates.append({"from_id": left["id"], "to_id": right["id"],
                                           "kind": "thematic",
                                           "label": {"text": theme, "evidence": evidence}})
                        found = True
                        break
                if found:
                    break
            if found:
                break
    return candidates
