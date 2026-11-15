"""Ontologia di consultazione per le Mappe: entità, fatti e provenienza.

Non inferisce azioni da somiglianze. Un arco MENTIONA è strutturale:
il testo indicizzato contiene letteralmente l'entità e identifica la fonte.
Gli articoli sono tali solo quando il titolo è stato verificato a monte.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date
from pathlib import Path
import re


def _key(value: str) -> str:
    return " ".join(value.casefold().replace("’", "'").split())


def link_entities(raw: dict, sources: list) -> dict:
    """Entity linking prudente: cognome abbreviato solo con nome univoco
    e fonte comune. Non dedurre un'identità dal mestiere ('il ministro').
    """
    result = deepcopy(raw)
    items = [n for n in result.get("nodes", []) if isinstance(n, dict)]
    persons = [n for n in items if n.get("kind") == "person"
               and isinstance(n.get("label"), dict)]
    valid_sources = {source.id for source in sources}
    redirects = {}
    for short in persons:
        short_label = short["label"].get("text", "")
        if not isinstance(short_label, str) or len(short_label.split()) != 1:
            continue
        candidates = [full for full in persons if full is not short
                      and len(str(full["label"].get("text", "")).split()) >= 2
                      and _key(full["label"]["text"]).split()[-1] == _key(short_label)]
        if len(candidates) != 1:
            continue
        full = candidates[0]
        left_ids = {p["source_id"] for p in short["label"].get("evidence", [])
                    if isinstance(p, dict) and p.get("source_id") in valid_sources}
        right_ids = {p["source_id"] for p in full["label"].get("evidence", [])
                     if isinstance(p, dict) and p.get("source_id") in valid_sources}
        if not left_ids & right_ids:
            continue
        # L'identità non è attribuita a un altro omonimo della stessa fonte.
        redirects[short["id"]] = full["id"]
        existing = full["label"].get("evidence", [])
        for proof in short["label"].get("evidence", []):
            if proof not in existing and len(existing) < 5:
                existing.append(proof)
    if not redirects:
        return result
    result["nodes"] = [n for n in items if n.get("id") not in redirects]
    cleaned = []
    for edge in result.get("edges", []):
        if not isinstance(edge, dict):
            continue
        item = dict(edge)
        item["from_id"] = redirects.get(item.get("from_id"), item.get("from_id"))
        item["to_id"] = redirects.get(item.get("to_id"), item.get("to_id"))
        if item["from_id"] != item["to_id"]:
            cleaned.append(item)
    result["edges"] = cleaned
    return result


def _sentence_with_name(text: str, name: str) -> str | None:
    found = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.I)
    for passage in re.split(r"(?<=[.!?;])\s+|\n+", text):
        passage = passage.strip()
        if found.search(passage) and len(passage) >= 20:
            return passage
    # Il chunk completo è una fonte originale verificabile, non testo generato.
    return text if len(text) >= 20 and found.search(text) else None


def _edition_metadata(source, coverage: dict) -> tuple[str, str]:
    for item in coverage.get("files", []):
        if not isinstance(item, dict) or item.get("pdf") != source.filename:
            continue
        publication = item.get("publication")
        date_value = item.get("date")
        edition = publication.strip() if isinstance(publication, str) and publication.strip() else "Quotidiano"
        if "verificar" in edition.casefold() or edition.casefold() in {"sconosciuta", "unknown", "n.d."}:
            edition = "Quotidiano"
        dated = date_value if isinstance(date_value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value) else ""
        if dated:
            try:
                date.fromisoformat(dated)
            except ValueError:
                dated = ""
        return edition, dated
    return "Quotidiano", ""


def enrich_map_with_provenance(data: dict, sources: list, article_details: dict,
                               coverage: dict, *, max_articles: int = 2) -> dict:
    """Aggiunge nodi Articolo/Fonte e archi MENTIONA, senza modificare i fatti.

    Solo titoli articolo verificati sono promossi a nodi di tipo 'article'.
    Altrimenti un chunk rimane 'source': non inventiamo identità editoriali.
    Si scelgono passaggi con più entità pertinenti per evitare un catalogo di
    pagine scollegate. Ogni menzione mantiene fonte e citazione originali.
    """
    output = deepcopy(data)
    nodes = output.get("nodes", [])
    if not nodes or not sources or max_articles <= 0:
        return output
    valid_sources = {s.id: s for s in sources}
    factual = {identity for edge in output.get("edges", []) if edge.get("kind") == "documented"
               for identity in (edge["from_id"], edge["to_id"])}
    grouped = defaultdict(list)
    for source in sources:
        article = article_details.get(source.id) if isinstance(article_details, dict) else None
        verified = isinstance(article, dict) and isinstance(article.get("title"), str) and bool(article["title"].strip())
        group_key = (source.filename, article["title"].casefold().strip()) if verified else (source.id,)
        grouped[(group_key, verified)].append((source, article if verified else None))
    candidates = []
    for (_identity, verified), members in grouped.items():
        mention_map = {}
        for node in nodes:
            if node.get("kind") not in {"person", "organization", "place", "event", "concept", "measure", "proposal"}:
                continue
            for source, _article in members:
                if source.id not in node.get("source_ids", []):
                    continue
                quote = _sentence_with_name(source.text, node["label"])
                if quote and node["id"] not in mention_map:
                    mention_map[node["id"]] = {"source_id": source.id, "quote": quote}
        if len(mention_map) < 2:
            continue
        # Una pagina con soli due macrotemi non forma una vicenda editoriale.
        meaningful = sum(n.get("kind") in {"person", "organization", "event", "measure", "proposal"}
                         for n in nodes if n["id"] in mention_map)
        if meaningful < 1:
            continue
        rank = (sum(n in factual for n in mention_map), len(mention_map), int(verified))
        candidates.append((rank, members, mention_map, verified))
    candidates.sort(key=lambda entry: entry[0], reverse=True)
    additions, added_edges = [], []
    used = set()
    for _rank, members, mention_map, verified in candidates:
        if len(additions) >= max_articles:
            break
        source, article = members[0]
        edition, published = _edition_metadata(source, coverage)
        if verified:
            label = article["title"].strip()
            kind = "article"
        else:
            label = f"Fonte · {edition} · p. {source.page}"
            kind = "source"
        identity = "A" + str(len(additions) + 1)
        all_ids = [s.id for s, _ in members]
        additions.append({"id": identity, "label": label, "kind": kind,
                          "source_ids": all_ids, "publication_date": published,
                          "publication": edition, "pdf_filename": source.filename,
                          "pages": article.get("pages", []) if verified else [source.page],
                          "verified_title": bool(verified)})
        for node in nodes:
            proof = mention_map.get(node["id"])
            if not proof or (identity, node["id"]) in used:
                continue
            used.add((identity, node["id"]))
            added_edges.append({"from_id": identity, "to_id": node["id"],
                                "kind": "mention", "label": "menziona",
                                "topic": "", "evidence": [proof],
                                "source_ids": [proof["source_id"]],
                                "adjacent_evidence": False})
    if not added_edges:
        return output
    # Le relazioni fattuali restano al centro; le fonti servono da ponti
    # documentali fra entità e da accesso al PDF.
    output["nodes"] = nodes[:3] + additions + nodes[3:]
    output["edges"] = output.get("edges", []) + added_edges
    return output
