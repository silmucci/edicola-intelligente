"""Identità deterministiche di corpus e selezioni; nessuna invalidazione distruttiva."""

import hashlib
import json


def source_version(chunks, *, metadata=(), selection=None):
    payload = {"version": 1, "chunks": sorted((c.id, c.fingerprint, c.metadata) for c in chunks),
               "metadata": sorted(metadata, key=lambda item: item["pdf"]), "selection": selection}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
