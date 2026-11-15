"""Acquisizione automatica locale da data/inbox, senza API esterne.

I file arrivano in data/inbox tramite Explorer o copia locale.
L'app li importa al successivo caricamento, senza modificare PDF precedenti:
- duplicato esatto: non aggiungere una seconda edizione;
- stesso nome, diverso contenuto: salva una nuova versione col suffisso SHA;
- PDF nuovo: registra l'estrazione per SHA, riusata da ingest_directory.

Non scrive né modifica vettori Chroma e non chiama Gemini. Non viene chiamato
nella versione cloud pubblicata, che usa lo snapshot immutabile.
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

from edicola.ingestion import extract_pdf
from edicola.maintenance_store import maintenance_lock
from edicola.storage import open_registry, save_result

_LOG = logging.getLogger(__name__)
MAX_PDF_BYTES = 75 * 1024 * 1024
MAX_PER_PASS = 10


def _report() -> dict:
    return {"added": [], "duplicates": [], "renamed": {}, "rejected": [],
            "pending": 0, "api_calls": 0}


def _checked_dirs(root: Path) -> tuple[Path, Path] | None:
    root = Path(root).resolve()
    data = root / "data"
    inbox, incoming = data / "inbox", data / "incoming"
    if not inbox.exists():
        return None
    for directory in (data, inbox, incoming):
        if directory.is_symlink() or not directory.resolve().is_relative_to(root):
            raise ValueError("Cartella dei quotidiani non consentita.")
    if not inbox.is_dir():
        raise ValueError("La casella di ingresso non è una cartella.")
    incoming.mkdir(parents=True, exist_ok=True)
    return inbox, incoming


def _valid_name(name: str) -> bool:
    return bool(name and len(name) <= 180 and not name.startswith(".")
                and name == Path(name).name and name.lower().endswith(".pdf")
                and not any(c in name for c in ("/", "\\", ":", "\x00"))
                and not any(ord(c) < 32 for c in name))


def _name_for(incoming: Path, name: str, sha: str) -> Path:
    original = incoming / name
    if not original.exists() and not original.is_symlink():
        return original
    stem = name[:-4][:110]
    candidate = incoming / f"{stem}--{sha[:12]}.pdf"
    number = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = incoming / f"{stem}--{sha[:12]}-{number}.pdf"
        number += 1
    return candidate


def _install_atomic(incoming: Path, filename: str, data: bytes) -> None:
    """L'hardlink crea il nome definitivo solo a file completo, senza overwrite."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=incoming, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, incoming / filename)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def process_inbox(root: Path, *, max_files: int = MAX_PER_PASS) -> dict:
    """Importa in sicurezza un gruppo finito di PDF, da rieseguire a ogni apertura.

    I duplicati vengono identificati tramite SHA-256 e rimossi dalla sola inbox
    quando una copia identica è già conservata nell'archivio. I file invalidi
    restano nella inbox per una verifica manuale; non sono pubblicati nell'app.
    """
    if type(max_files) is not int or max_files < 1:
        raise ValueError("max_files deve essere positivo.")
    report = _report()
    dirs = _checked_dirs(root)
    if dirs is None:
        return report
    inbox, incoming = dirs
    candidates = sorted((p for p in inbox.iterdir() if p.suffix.lower() == ".pdf"),
                        key=lambda p: p.name.casefold())
    if not candidates:
        return report
    root = Path(root).resolve()
    # Il lock esclude contemporaneamente altri import e batch di manutenzione.
    with maintenance_lock(root):
        existing = {}
        previous_by_name = {}
        for path in incoming.iterdir():
            if path.suffix.lower() != ".pdf":
                continue
            if path.is_symlink() or not path.is_file() or not _valid_name(path.name):
                continue
            with path.open("rb") as stream:
                existing_sha = hashlib.file_digest(stream, "sha256").hexdigest()
            existing[existing_sha] = path.name
            previous_by_name[path.name] = existing_sha
        for path in candidates[:max_files]:
            if not _valid_name(path.name) or path.is_symlink() or not path.is_file():
                report["rejected"].append({"pdf": path.name, "reason": "file non consentito"})
                continue
            try:
                before = path.stat()
                if not 0 < before.st_size <= MAX_PDF_BYTES:
                    report["rejected"].append({"pdf": path.name, "reason": "dimensione non consentita"})
                    continue
                data = path.read_bytes()
                after = path.stat()
                if (len(data) != before.st_size or
                        (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
                    report["rejected"].append({"pdf": path.name, "reason": "file ancora in trasferimento"})
                    continue
                digest = hashlib.sha256(data).hexdigest()
                if digest in existing:
                    # La copia attiva esiste già: elimina solo il file temporaneo
                    # della inbox, mai il documento originale in incoming.
                    path.unlink()
                    report["duplicates"].append({"pdf": path.name, "existing": existing[digest]})
                    continue
                if b"%PDF-" not in data[:1024]:
                    report["rejected"].append({"pdf": path.name, "reason": "formato non PDF"})
                    continue
                extracted = extract_pdf(data)
                if extracted.get("status") not in {"ok", "partial", "no_text"}:
                    report["rejected"].append({"pdf": path.name, "reason": "PDF non leggibile"})
                    continue
                destination = _name_for(incoming, path.name, digest)
                _install_atomic(incoming, destination.name, data)
                # Cache persistente della stessa estrazione: nessuna seconda
                # lettura con pypdf al successivo ingest_directory dell'app.
                with open_registry(root / "data/archive.sqlite3") as connection:
                    save_result(connection, digest, extracted)
                    # Solo i conflitti di nome identificano con certezza
                    # una revisione della stessa edizione: niente associazioni
                    # arbitrarie per data, nome della testata o similarità.
                    parent = previous_by_name.get(path.name)
                    if parent and destination.name != path.name:
                        with connection:
                            connection.execute(
                                """INSERT OR IGNORE INTO edition_lineage
                                (sha256, parent_sha256, original_filename)
                                VALUES (?, ?, ?)""",
                                (digest, parent, path.name),
                            )
                existing[digest] = destination.name
                previous_by_name[destination.name] = digest
                if destination.name != path.name:
                    report["renamed"][path.name] = destination.name
                path.unlink()
                report["added"].append(destination.name)
            except (OSError, ValueError, RuntimeError) as exc:
                _LOG.warning("Importazione PDF non riuscita: %s", type(exc).__name__)
                report["rejected"].append({"pdf": path.name, "reason": "impossibile importare"})
        report["pending"] = sum(
            p.suffix.lower() == ".pdf" for p in inbox.iterdir()
        )
    return report
