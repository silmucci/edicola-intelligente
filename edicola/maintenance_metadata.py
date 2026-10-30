"""Metadati curati dal gestore dopo verifica del PDF, senza inferenze o AI."""

import hashlib
import json
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import date
from pathlib import Path
from uuid import uuid4

from edicola.incremental import require_local_manager
from edicola.maintenance_store import maintenance_lock, private_directory


def confirm_metadata(root, filename, publication, published, *, confirmed=False):
    require_local_manager(root)
    if confirmed is not True:
        raise PermissionError("Verificare prima testata e data nel PDF originale.")
    root = Path(root).resolve()
    if Path(filename).name != filename or any(c in filename for c in "/\\:"):
        raise ValueError("Nome PDF non consentito.")
    publication, published = publication.strip(), published.strip()
    if len(publication) > 200 or published and (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published)):
        raise ValueError("Metadati non validi.")
    if published:
        date.fromisoformat(published)
    with maintenance_lock(root):
        incoming = root / "data/incoming"
        registry = root / "data/archive.sqlite3"
        if incoming.is_symlink() or not incoming.resolve().is_relative_to(root) or registry.is_symlink():
            raise ValueError("Archivio non consentito.")
        path = root / "data/incoming" / filename
        if path.is_symlink() or not path.is_file() or path.resolve().parent != (root / "data/incoming").resolve():
            raise ValueError("PDF non consentito.")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        with closing(sqlite3.connect(registry.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT result_json FROM extractions JOIN sources ON extractions.sha256=sources.sha256 WHERE filename=? AND sources.sha256=?", (filename, sha)).fetchone()
        if row is None:
            raise ValueError("Preparare il PDF prima di verificare i metadati.")
        pages = json.loads(row[0]).get("pages", [])
        text = pages[0]["text"][:500] if pages else ""
        header = re.search(r"Edizione del (\d{2}/\d{2}/\d{4})", text)
        if published and header and header[1] != date.fromisoformat(published).strftime("%d/%m/%Y"):
            raise ValueError("La data non corrisponde all’intestazione dell’edizione.")
        target = root / "data/editions.json"
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError("Catalogo metadati non consentito.")
        raw = target.read_bytes() if target.exists() else b"{}"
        catalog = json.loads(raw)
        if not isinstance(catalog, dict):
            raise ValueError("Catalogo metadati non valido.")
        previous = catalog.get(filename, {})
        if not isinstance(previous, dict):
            raise ValueError("Voce dei metadati non valida.")
        item = {**previous, "publication": publication, "date": published}
        if item == previous:
            return False
        backup = private_directory(root) / ("editions-before-" + uuid4().hex + ".json")
        backup.write_bytes(raw)
        catalog[filename] = item
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp") as stream:
                temporary = Path(stream.name)
                json.dump(catalog, stream, ensure_ascii=False, indent=2)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return True
