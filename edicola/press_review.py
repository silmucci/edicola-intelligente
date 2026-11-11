"""Filtri editoriali locali: nessuna classificazione geografica inferita o API."""

import re
from dataclasses import asdict, dataclass
from datetime import date

from edicola.editorial_selection import Catalog, topic_clusters
from edicola.corpus_versions import source_version
from edicola.knowledge_relevance import Topic, terms as topic_terms
from edicola.context_selection import edition_order
import unicodedata
import logging

VERSION = "press-review-v2"
logger = logging.getLogger(__name__)


def folded(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def ranked_chunks(chunks, query, semantic_hits=()):
    """Ranking offline; eventuali hit già autorizzati devono appartenere al catalogo."""
    normalized_query = "".join(c for c in unicodedata.normalize("NFKD", query) if not unicodedata.combining(c))
    query = folded(query)
    topic = Topic(normalized_query, chunks)
    words = topic_terms(query)
    current = {c.id: c for c in chunks}
    hits = {h["id"]: h for h in semantic_hits if h.get("id") in current and h.get("text") == current[h["id"]].text}
    scored = []
    title_terms_cache = {}
    for chunk in chunks:
        text = folded(chunk.text)
        score = topic.score(text, context_required=False) if words else 0
        title = chunk.metadata.get("article_title", "")
        if chunk.metadata.get("article_title_verified") is True and title and title in chunk.text:
            if title not in title_terms_cache:
                title_terms_cache[title] = topic_terms(folded(title))
            score += 4 * len(words & title_terms_cache[title])
        if chunk.id in hits and hits[chunk.id].get("distance", 1) <= .35:
            score += max(0, 1 - hits[chunk.id].get("distance", 1))
        if not query or score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda row: (-row[0], row[1].metadata.get("position", 0), row[1].id))
    logger.info("phase=press_ranking candidates=%d accepted=%d discarded=%d reason=relevance", len(chunks), len(scored), len(chunks)-len(scored))
    return list(edition_order([c for _, c in scored], filename=lambda c: c.metadata["filename"]))


def article_groups(chunks):
    """Raggruppa solo identità articolo esplicite nella stessa versione del PDF."""
    groups = {}
    for chunk in chunks:
        meta = chunk.metadata
        key = (meta["filename"], meta["pdf_sha256"], meta["chunk_config"], meta["article_id"]) if all(meta.get(k) for k in ("article_id", "pdf_sha256", "chunk_config")) else (chunk.id,)
        groups.setdefault(key, []).append(chunk)
    return list(groups.values())


@dataclass(frozen=True)
class ReviewSelection:
    keyword: str = ""
    filenames: tuple[str, ...] = ()
    scope: str = ""
    date_from: str = ""
    date_to: str = ""
    latest: bool = False


def filter_catalog(catalog, selection):
    files = {item["pdf"]: item for item in catalog.coverage["files"]}
    for value in (selection.date_from, selection.date_to):
        if value:
            date.fromisoformat(value)
    def included(name):
        info = files.get(name, {})
        published = info.get("date", "")
        return ((not selection.filenames or name in selection.filenames)
                and (not selection.scope or info.get("scope") == selection.scope)
                and (not selection.date_from or published and published >= selection.date_from)
                and (not selection.date_to or published and published <= selection.date_to))
    filenames = {chunk.metadata["filename"] for chunk in catalog.chunks}
    available = {name for name in filenames if included(name)}
    latest = max((files[name].get("date", "") for name in available), default="")
    chunks = [chunk for chunk in catalog.chunks
              if chunk.metadata["filename"] in available
              and (not selection.latest or latest and files[chunk.metadata["filename"]].get("date") == latest)
              ]
    chunks = ranked_chunks(chunks, selection.keyword)
    coverage = {**catalog.coverage, "selection": {
        "keyword": selection.keyword, "files": sorted(selection.filenames), "scope": selection.scope,
        "date_from": selection.date_from, "date_to": selection.date_to, "latest": selection.latest,
        "passages": len(chunks), "editions": len({c.metadata["filename"] for c in chunks})}}
    selected_names = {c.metadata["filename"] for c in chunks}
    coverage["selection_version"] = source_version(chunks, metadata=[files[name] for name in selected_names], selection={**asdict(selection), "strategy": VERSION})
    return Catalog(chunks, {c.id: catalog.vectors[c.id] for c in chunks if c.id in catalog.vectors}, coverage)


def review_groups(catalog):
    """Gruppi per affinità dei vettori esistenti, senza inventare nomi di temi."""
    assignments = topic_clusters(catalog.chunks, catalog.vectors, .82)
    groups = {}
    for chunk in catalog.chunks:
        groups.setdefault(assignments[chunk.id], []).append(chunk)
    return list(groups.values())
