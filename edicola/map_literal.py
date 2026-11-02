"""Completa archi letterali fra soli nodi già validati, dopo JSON AI valido."""

import re
from edicola.map_context import contiguous, joined_proofs
from edicola.map_relations import documented_relation
from edicola.archive import IndexChunk

PREDICATES = re.compile(r"\b(?:(?:ha|hanno)\s+(?:presentato|sostenuto|criticato|dichiarato\s+inammissibile)|"
                        r"(?:(?:è|sono)\s+stat[oaie]\s+)?(?:presentat[oaie]|sostenut[oaie]|dichiarat[oaie]\s+inammissibil[ei])\s+(?:anche\s+)?(?:dal|dalla|dai|dalle|da))\b", re.I)


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
