"""Date, concetti e relazioni verificati prima di costruire le visualizzazioni."""

import json
import re
import textwrap
from collections import Counter

from edicola.map_relations import documented_relation, relation_failure, thematic_support
from edicola.map_context import joined_proofs
from edicola.rag import Source, validate_response
from edicola.timeline_dates import documented_dates, event_status, resolve_date
from edicola.knowledge_presentation import development_kind, short_text, deadline_reference
from edicola.design_tokens import COLORS
from edicola.map_presentation import GROUPS, node_captions, node_groups
from edicola.proposal_extraction import ITEM as NOMINAL_PROPOSAL


CAUSAL = re.compile(r"\b(causa|causato|causata|provoca|provocato|provocata|determina|comporta)\b|a causa di|per effetto", re.I)


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def literal_present(label: str, quote: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(normalized(label)) + r"(?!\w)", normalized(quote)))


def checked_claim(claim, sources: list[Source]):
    return validate_response(json.dumps({"sufficient": True, "claims": [claim]}), sources)


def validate_timeline(data: dict, sources: list[Source], coverage: dict) -> tuple[dict, dict]:
    if not isinstance(data, dict) or set(data) != {"events"} or not isinstance(data["events"], list) or len(data["events"]) > 12:
        raise ValueError("invalid_structure")
    source_map = {source.id: source for source in sources}
    editions = {}
    for item in coverage["files"]:
        editions.setdefault(item["pdf"], set()).add(item.get("date", ""))
    publications = {pdf: next(iter(dates)) if len(dates) == 1 else "" for pdf, dates in editions.items()}
    events, rejected, unverified = [], 0, 0
    for item in data["events"]:
        if not isinstance(item, dict) or set(item) != {"title", "description", "event_date", "date_evidence"}:
            rejected += 1
            continue
        title, description = checked_claim(item["title"], sources), checked_claim(item["description"], sources)
        if not title.sufficient or not description.sufficient:
            rejected += 1
            continue
        # Non mostrare neanche nel testo una data completa assente dalle evidenze.
        if any(not documented_dates(item[key]["text"]).issubset(
            set().union(*(documented_dates(evidence["quote"]) for evidence in item[key]["evidence"])))
               for key in ("title", "description")):
            rejected += 1
            continue
        used = list(dict.fromkeys(title.used_source_ids + description.used_source_ids))
        temporal_quote, anchor = "", None
        temporal = {"event_date": None, "date_status": "missing", "date_origin": "undetermined",
                    "date_reason": "missing_evidence", "date_rule": ""}
        evidence = item["date_evidence"]
        proposed = item["event_date"]
        if proposed is not None or evidence is not None:
            temporal["date_status"] = "unverified"
            if isinstance(evidence, dict) and set(evidence) == {"source_id", "quote"}:
                check = checked_claim({"text": "Riferimento temporale documentato.", "evidence": [evidence]}, sources)
                if check.sufficient and evidence["source_id"] in used:
                    temporal_quote = evidence["quote"]
                    identity = evidence["source_id"]
                    filename = source_map[identity].filename
                    published = publications.get(filename, "")
                    if deadline_reference(temporal_quote):
                        temporal.update(date_status="deadline_reference", date_reason="deadline_reference")
                    else:
                        temporal = resolve_date(temporal_quote, proposed, published)
                    if temporal["date_origin"] == "edition_metadata":
                        anchor = {"source_id": identity, "pdf": filename, "publication_date": published,
                                  "rule": temporal["date_rule"]}
            if temporal["event_date"] is None:
                unverified += 1
        temporal_source = evidence.get("source_id") if isinstance(evidence, dict) else None
        published = publications.get(source_map[temporal_source].filename, "") if temporal_source in source_map else ""
        proof_quotes = list(dict.fromkeys(e["quote"] for key in ("title", "description") for e in item[key]["evidence"]))
        # Anche senza data conserviamo lo stato documentato; gli stati discordanti
        # restano indeterminati, senza usare la data editoriale per colmare il vuoto.
        status_quotes = [temporal_quote] if temporal_quote else proof_quotes
        states = {event_status(q, temporal["event_date"], published) for q in status_quotes}
        lifecycle = states.pop() if len(states) == 1 else "conflicting"
        category = development_kind(status_quotes, lifecycle)
        # Per annunci e futuro mostrare il passo letterale, non una parafrasi al passato.
        if lifecycle in {"announced", "future", "conflicting"} or category == "proposal":
            title_text = short_text(temporal_quote or proof_quotes[0], 90)
            description_text = temporal_quote or "\n".join(proof_quotes)
            if category == "proposal" and NOMINAL_PROPOSAL.match(item["title"]["text"]) and all(
                    any(item[key]["text"] in e["quote"] for e in item[key]["evidence"]) for key in ("title", "description")):
                title_text, description_text = title.answer, description.answer
        else:
            title_text, description_text = title.answer, description.answer
        events.append({"title": title_text, "description": description_text,
                       **temporal, "date_anchor": anchor, "event_status": lifecycle, "development_kind": category,
                       "evidence": list({(e["source_id"], e["quote"]): e for key in ("title", "description") for e in item[key]["evidence"]}.values()),
                       "temporal_quote": temporal_quote,
                       "source_ids": used, "publication_dates": [
                           {"source_id": identity, "date": publications.get(source_map[identity].filename, "")}
                           for identity in used]})
    dated = sorted((event for event in events if event["event_date"]), key=lambda event: event["event_date"])
    undated = [event for event in events if event["event_date"] is None]
    return {"events": dated, "undated_events": undated}, {
        "candidate_events": len(data["events"]),
        "rejected_events": rejected, "unverified_dates": unverified,
        "dated_events": len(dated), "undated_events": len(undated),
    }


def validate_map(data: dict, sources: list[Source], *, contexts=None) -> tuple[dict, dict]:
    if (not isinstance(data, dict) or set(data) != {"nodes", "edges"}
            or not isinstance(data["nodes"], list) or not isinstance(data["edges"], list)
            or len(data["nodes"]) > 16 or len(data["edges"]) > 24):
        raise ValueError("invalid_structure")
    nodes, edges, rejected_nodes, rejected_edges = {}, [], 0, 0
    for item in data["nodes"]:
        if (not isinstance(item, dict) or set(item) != {"id", "kind", "label"}
                or not isinstance(item["id"], str) or not re.fullmatch(r"N[1-9]\d?", item["id"])
                or item["id"] in nodes or not isinstance(item["kind"], str)
                or item["kind"] not in {"concept", "event", "place", "organization", "person", "measure", "proposal"}):
            rejected_nodes += 1
            continue
        check = checked_claim(item["label"], sources)
        if not check.sufficient or not any(literal_present(item["label"]["text"], e["quote"]) for e in item["label"]["evidence"]):
            rejected_nodes += 1
            continue
        nodes[item["id"]] = {"id": item["id"], "label": item["label"]["text"], "kind": item["kind"],
                             "source_ids": check.used_source_ids}
    seen = set()
    edge_rejections = Counter()
    edge_details = Counter()
    decisions = []
    adjacent_edges = 0
    labels_normalized = 0
    source_ids = {source.id for source in sources}
    def reject(category, detail=None):
        nonlocal rejected_edges
        rejected_edges += 1
        edge_rejections[category] += 1
        edge_details[detail or category] += 1
        decisions.append({"candidate": len(decisions) + 1, "outcome": "rejected", "reason": detail or category})

    raw_node_ids = {n.get("id") for n in data["nodes"] if isinstance(n, dict) and isinstance(n.get("id"), str)}
    for item in data["edges"]:
        required = {"from_id", "to_id", "kind", "label"}
        if (not isinstance(item, dict) or not required <= set(item) or set(item) - required - {"predicate"}
                or not isinstance(item["from_id"], str) or not isinstance(item["to_id"], str)
                or not isinstance(item["kind"], str)):
            reject("invalid_or_missing_endpoint", "invalid_edge_structure")
            continue
        if item["from_id"] not in nodes or item["to_id"] not in nodes:
            detail = "rejected_endpoint" if {item["from_id"], item["to_id"]} <= raw_node_ids else "unknown_endpoint"
            reject("invalid_or_missing_endpoint", detail)
            continue
        if item["from_id"] == item["to_id"] or item["kind"] not in {"documented", "thematic"}:
            reject("invalid_or_missing_endpoint", "self_link" if item["from_id"] == item["to_id"] else "invalid_kind")
            continue
        check = checked_claim(item["label"], sources)
        if not check.sufficient:
            evidence = item["label"].get("evidence", []) if isinstance(item["label"], dict) else []
            unknown = isinstance(evidence, list) and any(isinstance(e, dict) and isinstance(e.get("source_id"), str)
                and e["source_id"] not in source_ids for e in evidence)
            reject("unknown_source" if unknown else "invalid_citation")
            continue
        left, right = (normalized(nodes[item[key]]["label"]) for key in ("from_id", "to_id"))
        evidence = item["label"]["evidence"]
        label = item["label"]["text"]
        topic = ""
        adjacent = False
        if item["kind"] == "documented":
            predicate = item.get("predicate") if item.get("predicate") is not None else label
            if not isinstance(predicate, str) or not predicate.strip():
                reject("relation_not_explicit", "invalid_predicate")
                continue
            proofs = [{"text": e["quote"], "evidence": [e], "adjacent": False} for e in evidence]
            proofs.extend(joined_proofs(evidence, sources, contexts or {}))
            verified = [p for p in proofs if documented_relation(left, predicate, right, p["text"])]
            supporting = []
            for proof in verified:
                for entry in proof["evidence"]:
                    if entry not in supporting:
                        supporting.append(entry)
            valid = bool(verified)
            if valid:
                adjacent = not any(not p["adjacent"] for p in verified)
                labels_normalized += normalized(predicate) != normalized(label)
                label = predicate.strip()  # Nessuna parafrasi non verificata viene mostrata.
            else:
                reasons = [relation_failure(left, predicate, right, p["text"]) for p in proofs]
                # Preferire la spiegazione della prova più completa.
                detail = next((r for r in reasons if r in {"uncertain_or_negated", "unsupported_relation_form"}), None)
                detail = detail or ("endpoints_not_in_evidence" if "endpoints_not_in_evidence" in reasons else "predicate_not_literal")
        else:
            topic = normalized(label)
            left_evidence = [e for e in evidence if thematic_support(left, topic, e["quote"])]
            right_evidence = [e for e in evidence if thematic_support(right, topic, e["quote"])]
            valid = (not CAUSAL.search(label) and len(topic) >= 3
                     and not literal_present(topic, left) and not literal_present(topic, right)
                     and bool(left_evidence) and bool(right_evidence))
            supporting = [e for e in evidence if e in left_evidence or e in right_evidence]
            label = "associazione tematica"  # Nessuna direzione o causalità inferita.
        if not valid:
            reject("relation_not_explicit", detail) if item["kind"] == "documented" else reject("theme_not_supported")
            continue
        identity = (item["from_id"], item["to_id"], item["kind"], normalized(label))
        if identity in seen:
            reject("duplicate")
            continue
        seen.add(identity)
        adjacent_edges += adjacent
        decisions.append({"candidate": len(decisions) + 1, "outcome": "accepted", "reason": "adjacent_evidence" if adjacent else "verified_evidence"})
        edges.append({"from_id": item["from_id"], "to_id": item["to_id"], "kind": item["kind"],
                      "label": label, "topic": topic, "evidence": supporting,
                      "adjacent_evidence": adjacent,
                      "source_ids": list(dict.fromkeys(e["source_id"] for e in supporting))})
    return {"nodes": list(nodes.values()), "edges": edges}, {"rejected_nodes": rejected_nodes,
            "rejected_edges": rejected_edges, "edge_rejections": dict(edge_rejections),
            "candidate_edges": len(data["edges"]), "accepted_edges": len(edges),
            "edge_rejection_details": dict(edge_details), "edge_decisions": decisions,
            "adjacent_edges": adjacent_edges, "labels_normalized": labels_normalized,
            "relations_status": ("none_generated" if not data["edges"] else "all_rejected" if not edges
                                 else "partial" if rejected_edges else "accepted")}


def compact_map(data: dict, limit: int = 10) -> dict:
    """Ordine editoriale di pertinenza, inclusi gli isolati; nessun bonus agli archi."""
    if not 2 <= limit <= 10:
        raise ValueError("Il grafico mostra da 2 a 10 nodi.")
    nodes = data["nodes"][:limit]
    chosen = {n["id"] for n in nodes}
    edges = [e for e in data["edges"] if {e["from_id"], e["to_id"]} <= chosen]
    return {"nodes": nodes, "edges": edges}


def map_focus(data, topic=""):
    degree = Counter(endpoint for edge in data["edges"] for endpoint in (edge["from_id"], edge["to_id"]))
    terms = set(re.findall(r"\w+", topic.casefold()))
    return max(data["nodes"], key=lambda node: (len(terms & set(re.findall(r"\w+", node["label"].casefold()))),
                -data["nodes"].index(node), degree[node["id"]]))["id"] if data["nodes"] else None


def map_dot(data: dict, *, topic="", grouping=False) -> str:
    """DOT con identificativi validati e stringhe quotate, senza HTML o URL eseguibili."""
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    data = compact_map(data)
    focus = None if grouping else map_focus(data, topic)
    def wrapped(value, width=24):
        return textwrap.fill(" ".join(value.split()), width=width, break_long_words=False, break_on_hyphens=False)
    captions = node_captions(data["nodes"])
    direction = "TB" if grouping or len(data["nodes"]) > 5 else "LR"
    lines = ['digraph Knowledge {',
             f'graph [rankdir={direction}, pack=true, packmode="array_3", nodesep=0.22, ranksep=0.32, pad=0.08, margin=0];',
             f'node [fontname="Arial", fontsize=12, width=0, height=0, margin="0.10,0.07", style=filled, color="{COLORS["border"]}", fontcolor="{COLORS["ink"]}"];',
             f'edge [fontname="Arial", fontsize=11, arrowsize=0.6, color="{COLORS["primary"]}", fontcolor="{COLORS["muted"]}"];']
    for kind, members in node_groups(data["nodes"]):
        _, title, shape, color = GROUPS[kind]
        lines.append(f'subgraph cluster_{kind} {{')
        lines.append(f'graph [label={quote(title)}, fontname="Arial", fontsize=11, fontcolor="{COLORS["muted"]}", style=rounded, color="{COLORS["border"]}", bgcolor="{COLORS["paper"]}", margin=10];')
        for node in members:
            style = "rounded,filled" if kind in {"organization", "measure", "proposal"} else "filled"
            emphasis = f', penwidth=2, color="{COLORS["primary"]}"' if node["id"] == focus else ''
            lines.append(f'{quote(node["id"])} [label={quote(wrapped(captions[node["id"]]))}, tooltip={quote(node["label"])}, shape={shape}, style="{style}", fillcolor="{color}"{emphasis}];')
        lines.append('}')
    for edge in ([] if grouping else data["edges"]):
        label = edge["label"]
        if edge.get("topic"):
            label = edge["topic"]
        style = "solid" if edge["kind"] == "documented" else "dashed"
        direction = "forward" if edge["kind"] == "documented" else "none"
        lines.append(f'{quote(edge["from_id"])} -> {quote(edge["to_id"])} [label={quote(wrapped(label))}, tooltip={quote(label)}, style={style}, dir={direction}];')
    return "\n".join(lines + ["}"])
