"""Completa archi letterali fra soli nodi già validati, dopo JSON AI valido."""

import re
from edicola.map_context import contiguous, joined_proofs
from edicola.map_relations import documented_relation, PARTY
from edicola.archive import IndexChunk

PREDICATES = re.compile(r"\b(?:(?:ha|hanno)\s+(?:presentato|sostenuto|criticato|dichiarato\s+inammissibile)|"
                        r"(?:(?:è|sono)\s+stat[oaie]\s+)?(?:presentat[oaie]|sostenut[oaie]|dichiarat[oaie]\s+inammissibil[ei])\s+(?:anche\s+)?(?:dal|dalla|dai|dalle|da)|"
                        r"(?:ha\s+esaminato|esamina|riguarda|riguardano|propone|sostiene|critica|è\s+esponente\s+di|deputato\s+del|senatore\s+del)|"
                        r"presentat[oaie]\s+per\s+(?:garantire|assicurare|tutelare)\s+la\s+(?:salvaguardia|sopravvivenza|tutela)\s+(?:dei|degli)(?:\s+(?:quattro|tre|due))?)\b", re.I)


def complete_nodes(nodes, sources, *, accepted_ids=None):
    """Candidati nominali da frasi con un'entità già estratta: tutti rivalidati."""
    result = list(nodes)
    labels = {n["label"]["text"].casefold() for n in nodes if isinstance(n, dict) and (accepted_ids is None or n.get("id") in accepted_ids) and isinstance(n.get("label"), dict) and isinstance(n["label"].get("text"), str)}
    anchors = set(labels)
    name = r"(?!Il\b|La\b|Lo\b|Un\b|Una\b)[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ’'-]+"
    person = re.compile(r"\b(?i:deputato|senatore|senatrice|consigliere|consigliera)(?:\s+(?i:di|del|della)\s+(?i:" + PARTY + r"))?\s+(" + name + r"(?:\s+" + name + r"){1,2})\b")
    institution = re.compile(r"\b(?:Commissione|Ministero|Consiglio)\s+(?:(?:dei|delle|di|del)\s+)?(?:[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+|ministri|giustizia|bilancio)(?:\s+(?:di|del|dei)\s+[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+)?\b")
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
            candidates += [(m[0], kind) for pattern, kind in ((proposal, "proposal"), (topic, "concept")) for m in pattern.finditer(quote)]
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
