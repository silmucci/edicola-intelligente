"""Date delle edizioni ricavate dal nome dei PDF locali già acquisiti.

Solo nomi nel formato *_edizione_del_G-M-AAAA_*.pdf. Le date curate
manualmente hanno sempre precedenza e la provenienza resta tracciabile.
Non legge il testo dei PDF, non modifica chunk o vettori, non usa Gemini.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from uuid import uuid4

from edicola.maintenance_store import maintenance_lock, private_directory

_DATE_IN_NAME = re.compile(
    r"(?:^|_)edizione_del_(\d{1,2})-(\d{1,2})-(\d{4})(?=_|\.pdf$)",
    flags=re.IGNORECASE,
)


def date_from_filename(filename: str) -> str | None:
    """Restituisce YYYY-MM-DD solo per date reali nel formato concordato."""
    if not isinstance(filename, str) or Path(filename).name != filename:
        return None
    if not filename.lower().endswith(".pdf"):
        return None
    match = _DATE_IN_NAME.search(filename)
    if match is None:
        return None
    day, month, year = map(int, match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def sync_filename_dates(root: Path, documents) -> list[str]:
    """Completa le date mancanti nel catalogo locale, con backup atomico.

    Funziona anche sui PDF già acquisiti prima dell'introduzione della regola.
    Non inventa la testata, non sovrascrive date già compilate e non altera i
    12 PDF, i chunk o gli embedding dello snapshot.
    """
    root = Path(root).resolve()
    incoming = root / "data/incoming"
    target = root / "data/editions.json"
    if (incoming.is_symlink() or not incoming.is_dir()
            or not incoming.resolve().is_relative_to(root)
            or target.is_symlink() or not target.resolve().is_relative_to(root)):
        raise ValueError("Cartelle o catalogo delle edizioni non consentiti.")

    proposed = {}
    for document in documents:
        name = document.filename
        if not getattr(document, "sha256", None):
            continue
        published = date_from_filename(name)
        if published is None:
            continue
        path = incoming / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != incoming.resolve():
            continue
        proposed[name] = published
    if not proposed:
        return []

    with maintenance_lock(root):
        raw = target.read_bytes() if target.is_file() else b"{}"
        catalog = json.loads(raw)
        if not isinstance(catalog, dict):
            raise ValueError("Catalogo delle edizioni non valido.")
        changed = []
        for filename, published in sorted(proposed.items()):
            previous = catalog.get(filename, {})
            if not isinstance(previous, dict):
                raise ValueError("Voce non valida nel catalogo delle edizioni.")
            existing = previous.get("date")
            if existing is not None and (not isinstance(existing, str) or existing.strip()):
                continue
            catalog[filename] = {**previous, "date": published, "date_source": "filename"}
            changed.append(filename)
        if not changed:
            return []

        # Backup privato del catalogo originale (anche per il primo inserimento).
        backup = private_directory(root) / ("editions-before-filename-" + uuid4().hex + ".json")
        backup.write_bytes(raw)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, mode="w", encoding="utf-8",
                suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(catalog, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return changed
