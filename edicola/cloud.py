"""Snapshot dimostrativi espliciti e ripristino locale, senza API o estrazioni."""

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
from contextlib import closing
from pathlib import Path

from edicola.chunking import ChunkConfig

_LOCK = threading.Lock()
VERSION = 1


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def registered_files(root):
    """Controllo read-only: impedisce nuove estrazioni/preprocessing nel cloud."""
    data = root / "data"
    with closing(sqlite3.connect((data / "archive.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = dict(db.execute("SELECT filename, sha256 FROM sources"))
        paths = sorted((data / "incoming").glob("*"))
        pdfs = [p for p in paths if p.suffix.lower() == ".pdf"]
        if not pdfs or set(rows) != {p.name for p in pdfs}:
            raise ValueError("Lo snapshot deve contenere esattamente i PDF registrati.")
        for path in pdfs:
            if path.is_symlink() or not path.is_file() or rows[path.name] != digest(path):
                raise ValueError("PDF dello snapshot assente, modificato o non consentito.")
            sha = rows[path.name]
            if not db.execute("SELECT 1 FROM extractions WHERE sha256=?", (sha,)).fetchone():
                raise ValueError("Estrazione persistente mancante.")
            config = db.execute("SELECT config_signature FROM chunk_sets WHERE sha256=?", (sha,)).fetchone()
            if not config or config[0] != ChunkConfig().signature:
                raise ValueError("Preprocessing assente o incompatibile: preparare lo snapshot localmente.")
    return rows


def export_seed(root, destination, filenames, *, authorize_distribution=False):
    """Esporta SOLO PDF nominati e dati derivati; mai profili, .env o cache."""
    if not authorize_distribution:
        raise ValueError("Occorre autorizzare esplicitamente la distribuzione dei PDF e dei dati derivati.")
    if not filenames or len(set(filenames)) != len(filenames):
        raise ValueError("Specificare un elenco non vuoto di PDF autorizzati, senza duplicati.")
    if any(Path(name).name != name or any(c in name for c in "/\\:") or not name.lower().endswith(".pdf") for name in filenames):
        raise ValueError("Usare soltanto nomi PDF, senza percorsi.")
    if destination.exists():
        raise ValueError("La destinazione deve essere nuova: nessun dato viene sovrascritto.")
    from edicola.archive import read_active_chunks
    from edicola.storage import open_registry
    from edicola.vectorstore import open_collection

    incoming = root / "data/incoming"
    # Non aprire/esportare un PDF fuori dall'archivio, neppure tramite symlink.
    for name in filenames:
        path = incoming / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != incoming.resolve():
            raise ValueError("PDF autorizzato non presente nell'archivio.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary) / "seed"
        (stage / "data/incoming").mkdir(parents=True)
        for name in filenames:
            shutil.copyfile(incoming / name, stage / "data/incoming" / name)
        # Copia selettiva tramite transazione SQLite: esclude anche dati storici privati.
        with closing(sqlite3.connect((root / "data/archive.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as source:
            source.execute("BEGIN")
            with open_registry(stage / "data/archive.sqlite3") as target:
                for name in filenames:
                    sha = digest(stage / "data/incoming" / name)
                    if source.execute("SELECT sha256 FROM sources WHERE filename=?", (name,)).fetchone() != (sha,):
                        raise ValueError("PDF nuovo/modificato: aggiornare prima l'archivio locale.")
                    target.execute("INSERT INTO sources(filename,sha256) VALUES (?,?)", (name, sha))
                    for table, column in (("extractions", "sha256"), ("chunk_sets", "sha256"), ("chunks", "pdf_sha256")):
                        for row in source.execute(f"SELECT * FROM {table} WHERE {column}=?", (sha,)):
                            target.execute(f"INSERT OR IGNORE INTO {table} VALUES ({','.join('?' for _ in row)})", row)
                target.commit()
        registered_files(stage)
        editions = root / "data/editions.json"
        if editions.is_file():
            metadata = json.loads(editions.read_text(encoding="utf-8"))
            (stage / "data/editions.json").write_text(json.dumps({n: metadata[n] for n in filenames if n in metadata}, ensure_ascii=False), encoding="utf-8")
        chunks, warnings = read_active_chunks(stage / "data/archive.sqlite3", stage / "data/incoming")
        if warnings:
            raise ValueError("Snapshot SQLite non coerente.")
        collection = open_collection(root / "data/chroma")
        records = []
        if collection is not None:
            for offset in range(0, len(chunks), 100):
                selected = {c.id: c for c in chunks[offset:offset + 100]}
                batch = collection.get(ids=list(selected), include=["documents", "metadatas", "embeddings"])
                for identity, text, meta, vector in zip(batch["ids"], batch["documents"], batch["metadatas"], batch["embeddings"]):
                    chunk = selected[identity]
                    if text != chunk.text or (meta or {}).get("input_sha256") != chunk.fingerprint:
                        raise ValueError("Embedding obsoleto: esportazione interrotta, nessuna reindicizzazione.")
                    records.append({"id": identity, "text": text, "metadata": chunk.chroma_metadata, "embedding": vector.tolist()})
        (stage / "vectors.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        from edicola.vectorstore import COLLECTION_METADATA
        manifest = {"version": VERSION, "collection": COLLECTION_METADATA,
                    "pdfs": len(filenames), "chunks": len(chunks), "indexed": len(records),
                    "files": {p.relative_to(stage).as_posix(): digest(p) for p in stage.rglob("*") if p.is_file()}}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        stage.rename(destination)
    return manifest


def validate_seed(seed):
    """Manifest locale controllato: nessun file arbitrario o credenziale."""
    from edicola.vectorstore import COLLECTION_METADATA
    manifest = json.loads((seed / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != VERSION or manifest.get("collection") != COLLECTION_METADATA:
        raise ValueError("Versione snapshot o configurazione embeddings incompatibile.")
    files = manifest.get("files", {})
    required = {"data/archive.sqlite3", "vectors.json"}
    if not required <= set(files):
        raise ValueError("Snapshot incompleto.")
    for name, sha in files.items():
        parts = name.split("/")
        allowed = name in required | {"data/editions.json"} or (len(parts) == 3 and parts[:2] == ["data", "incoming"] and parts[-1].lower().endswith(".pdf"))
        path = seed / name
        if not allowed or "\\" in name or ":" in name or path.resolve().parent != (seed / Path(name).parent).absolute() or path.is_symlink() or not path.is_file() or digest(path) != sha:
            raise ValueError("File dello snapshot non consentito o hash non valido.")
    actual = {p.relative_to(seed).as_posix() for p in seed.rglob("*") if p.is_file()}
    if actual != set(files) | {"manifest.json"}:
        raise ValueError("Lo snapshot contiene file inattesi.")
    registered_files(seed)
    return manifest


def prepare_cloud(root):
    """Ripristino una volta per snapshot; mai modifica dell'archivio di sviluppo."""
    from edicola.archive import read_active_chunks
    from edicola.embeddings import validate_vector
    from edicola.vectorstore import open_collection
    seed = root / "deployment/seed"
    manifest = validate_seed(seed)
    identity = digest(seed / "manifest.json")
    runtime = root / ".cloud-runtime" / identity
    if (not runtime.resolve().is_relative_to(root.resolve())
            or (root / ".cloud-runtime").is_symlink() or runtime.is_symlink()
            or (runtime / "data").is_symlink()):
        raise ValueError("Percorso runtime non consentito.")
    with _LOCK:
        if not (runtime / "ready.json").is_file():
            # Percorso definitivo: non spostare file nativi Chroma ancora aperti.
            # Un ripristino interrotto può riprendere con upsert degli stessi vettori.
            runtime.mkdir(parents=True, exist_ok=True)
            shutil.copytree(seed / "data", runtime / "data", dirs_exist_ok=True)
            chunks, warnings = read_active_chunks(runtime / "data/archive.sqlite3", runtime / "data/incoming")
            current = {c.id: c for c in chunks}
            records = json.loads((seed / "vectors.json").read_text(encoding="utf-8"))
            if warnings or len(chunks) != manifest["chunks"] or len(records) != manifest["indexed"] or len({r["id"] for r in records}) != len(records):
                raise ValueError("Conteggi dello snapshot incoerenti.")
            for record in records:
                chunk = current.get(record["id"])
                if chunk is None or record["text"] != chunk.text or record["metadata"] != chunk.chroma_metadata:
                    raise ValueError("Riferimenti degli embeddings incoerenti.")
                validate_vector(record["embedding"])
            collection = open_collection(runtime / "data/chroma", create=True)
            for offset in range(0, len(records), 100):
                batch = records[offset:offset + 100]
                collection.upsert(ids=[r["id"] for r in batch], documents=[r["text"] for r in batch], metadatas=[r["metadata"] for r in batch], embeddings=[r["embedding"] for r in batch])
            (runtime / "ready.json").write_text(json.dumps({"seed": identity}), encoding="utf-8")
        registered_files(runtime)
    return runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--export", type=Path, help="Nuova cartella destinazione; nessuna pubblicazione")
    parser.add_argument("--pdf", action="append", default=[])
    parser.add_argument("--authorize-distribution", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.export:
            result = export_seed(args.root, args.export, args.pdf, authorize_distribution=args.authorize_distribution)
            print(f"Snapshot locale: {result['pdfs']} PDF, {result['chunks']} chunk, {result['indexed']} embeddings esistenti.")
        else:
            result = validate_seed(args.root / "deployment/seed")
            print(f"Snapshot verificato: {result['pdfs']} PDF, {result['indexed']}/{result['chunks']} chunk indicizzati. Nessuna API.")
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        parser.exit(1, "Snapshot non disponibile/coerente. Verificare DEPLOYMENT.md; nessuna API eseguita.\n")


if __name__ == "__main__":
    main()
