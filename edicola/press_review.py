"""Filtri editoriali locali: nessuna classificazione geografica inferita o API."""

import re
from dataclasses import asdict, dataclass
from datetime import date

from edicola.editorial_selection import Catalog, topic_clusters
from edicola.corpus_versions import source_version


@dataclass(frozen=True)
class ReviewSelection:
    keyword: str = ""
    filenames: tuple[str, ...] = ()
    scope: str = ""
    date_from: str = ""
    date_to: str = ""
    latest: bool = False


def filter_catalog(catalog, selection):
    terms = re.findall(r"\w+", selection.keyword.casefold())
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
    available = {chunk.metadata["filename"] for chunk in catalog.chunks if included(chunk.metadata["filename"])}
    latest = max((files[name].get("date", "") for name in available), default="")
    chunks = [chunk for chunk in catalog.chunks
              if (not selection.keyword.strip() or terms)
              and chunk.metadata["filename"] in available
              and (not selection.latest or latest and files[chunk.metadata["filename"]].get("date") == latest)
              and all(term in chunk.text.casefold() for term in terms)]
    coverage = {**catalog.coverage, "selection": {
        "keyword": selection.keyword, "files": sorted(selection.filenames), "scope": selection.scope,
        "date_from": selection.date_from, "date_to": selection.date_to, "latest": selection.latest,
        "passages": len(chunks), "editions": len({c.metadata["filename"] for c in chunks})}}
    selected_names = {c.metadata["filename"] for c in chunks}
    coverage["selection_version"] = source_version(chunks, metadata=[files[name] for name in selected_names], selection=asdict(selection))
    return Catalog(chunks, {c.id: catalog.vectors[c.id] for c in chunks if c.id in catalog.vectors}, coverage)


def review_groups(catalog):
    """Gruppi per affinità dei vettori esistenti, senza inventare nomi di temi."""
    assignments = topic_clusters(catalog.chunks, catalog.vectors, .82)
    groups = {}
    for chunk in catalog.chunks:
        groups.setdefault(assignments[chunk.id], []).append(chunk)
    return list(groups.values())
