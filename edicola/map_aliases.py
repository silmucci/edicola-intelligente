"""Unifica sigle soltanto quando l'equivalenza è scritta nelle prove correnti."""
import re
from copy import deepcopy


def explicit_aliases(raw, sources, accepted_ids):
    data = deepcopy(raw)
    nodes = {n["id"]: n for n in data["nodes"] if isinstance(n, dict) and n.get("id") in accepted_ids}
    redirects = {}
    for short in list(nodes.values()):
        abbreviation = short["label"]["text"]
        if not re.fullmatch(r"[A-Z][A-Z.]{1,11}", abbreviation):
            continue
        matches = []
        for long in nodes.values():
            if short["id"] == long["id"] or short["kind"] != long["kind"]:
                continue
            pattern = r"(?<!\w)" + re.escape(long["label"]["text"]) + r"\s*\(\s*" + re.escape(abbreviation) + r"\s*\)"
            for source in sources:
                if re.search(pattern, source.text):
                    matches.append((long, source))
        if len({n["id"] for n, _ in matches}) != 1:
            continue
        canonical, source = matches[0]
        touching = [e for e in data["edges"] if isinstance(e, dict) and short["id"] in (e.get("from_id"), e.get("to_id"))]
        if any(not any(canonical["label"]["text"].casefold() in proof.get("quote", "").casefold()
                       for proof in edge.get("label", {}).get("evidence", [])) for edge in touching):
            # Non sacrificare un arco valido per normalizzare soltanto il nome.
            continue
        redirects[short["id"]] = canonical["id"]
        proof = {"source_id": source.id, "quote": source.text}
        if proof not in canonical["label"]["evidence"] and len(canonical["label"]["evidence"]) < 5:
            canonical["label"]["evidence"].append(proof)
    data["nodes"] = [n for n in data["nodes"] if not isinstance(n, dict) or n.get("id") not in redirects]
    data["edges"] = [{**e, "from_id": redirects.get(e["from_id"], e["from_id"]),
                      "to_id": redirects.get(e["to_id"], e["to_id"])} if isinstance(e, dict) and isinstance(e.get("from_id"), str) and isinstance(e.get("to_id"), str) else e for e in data["edges"]]
    return data
