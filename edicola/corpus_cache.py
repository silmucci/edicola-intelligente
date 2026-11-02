"""Audit read-only delle cache: distingue fonti obsolete da copertura storica."""

import json
import sqlite3
from collections import Counter
from contextlib import closing


def product_status(product, current, coverage, *, require_text=True):
    sources = product.get("sources", [])
    for source in sources:
        chunk = current.get(source.get("chunk_id"))
        if (chunk is None or source.get("filename") != chunk.metadata["filename"]
                or source.get("page") != chunk.metadata["page"]
                or (require_text and (not isinstance(source.get("text"), str) or not source["text"]
                                      or not chunk.text.startswith(source["text"])))):
            return "obsolete_sources"
    previous = product.get("coverage", {})
    if previous.get("corpus_version") != coverage.get("corpus_version"):
        return "historical_coverage"
    if any(previous.get(key) != coverage.get(key) for key in ("indexed", "total", "files")):
        return "historical_coverage"
    return "current_sources"


def audit_caches(root, chunks, coverage):
    """Le chiavi dei generatori invalidano logicamente i vecchi snapshot.

    Nessuna cancellazione: i prodotti con fonti valide rimangono consultabili
    come storici; una fonte obsoleta non riottiene la chiave del corpus corrente.
    """
    current = {chunk.id: chunk for chunk in chunks}
    counts = {"editorial": Counter(), "knowledge": Counter(), "audio": Counter()}
    path = root / "data/editorial.sqlite3"
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            for (raw,) in db.execute("SELECT result_json FROM products"):
                try:
                    counts["editorial"][product_status(json.loads(raw), current, coverage)] += 1
                except (ValueError, TypeError, KeyError, AttributeError):
                    counts["editorial"]["unreadable"] += 1
    for path in (root / "data/knowledge_cache").glob("*.json"):
        try:
            product = json.loads(path.read_text(encoding="utf-8"))
            counts["knowledge"][product_status(product, current, coverage)] += 1
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            counts["knowledge"]["unreadable"] += 1
    for path in (root / "data/podcast_cache").glob("*.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            counts["audio"][product_status(manifest["script"], current, coverage, require_text=False)] += 1
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            counts["audio"]["unreadable"] += 1
    return {name: dict(counter) for name, counter in counts.items()}


def render_history_notice(coverage, archive):
    """Segnala risultati RAM precedenti; non li cancella e non genera API."""
    if archive is None:
        return
    historical = coverage.get("total") != len(archive.chunk_references)
    try:
        from edicola.editorial_selection import read_catalog
        current = read_catalog(archive.root).coverage
        historical |= coverage.get("corpus_version") != current.get("corpus_version")
    except (OSError, ValueError, RuntimeError):
        pass
    if historical:
        import streamlit as st
        st.caption("Risultato storico o di una copertura precedente dell’archivio. Per includere gli aggiornamenti serve un nuovo invio esplicito.")
