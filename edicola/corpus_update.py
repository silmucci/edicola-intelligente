"""Manutenzione locale del corpus: acquisizione opzionale e piano senza API."""

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from edicola.archive import read_active_chunks
from edicola.chunking import ChunkConfig, prepare_documents
from edicola.corpus_cache import audit_caches
from edicola.corpus_versions import source_version
from edicola.indexing import plan_index
from edicola.ingestion import ingest_directory
from edicola.vectorstore import open_collection, stored_records


def registry_rows(path):
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return dict(db.execute("SELECT filename, sha256 FROM sources"))


def metadata_report(root, names, hashes):
    path = root / "data/editions.json"
    editions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(editions, dict):
        raise ValueError("Il catalogo delle edizioni deve essere un oggetto JSON.")
    with closing(sqlite3.connect((root / "data/archive.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        reports, files = {}, []
        for name in names:
            item = editions.get(name, {})
            item = item if isinstance(item, dict) else {}
            publication, published = item.get("publication", ""), item.get("date", "")
            issues = []
            if not isinstance(publication, str) or not publication.strip():
                issues.append("missing_publication")
                publication = ""
            if not isinstance(published, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
                issues.append("missing_or_invalid_date")
                published = ""
            else:
                try:
                    date.fromisoformat(published)
                except ValueError:
                    issues.append("invalid_calendar_date")
                    published = ""
            row = db.execute("SELECT result_json FROM extractions WHERE sha256=?", (hashes[name],)).fetchone()
            first = json.loads(row[0]).get("pages", []) if row else []
            header = first[0]["text"][:500] if first else ""
            match = re.search(r"Edizione del (\d{2}/\d{2}/\d{4})", header)
            if match and published:
                if match[1] != date.fromisoformat(published).strftime("%d/%m/%Y"):
                    issues.append("date_conflicts_with_header")
            elif published:
                issues.append("date_requires_manual_verification")
            reports[name] = {"publication": publication, "date": published, "issues": issues,
                             "date_header": match[0] if match else None}
            files.append({"pdf": name, "publication": publication, "date": published})
            if item.get("scope") in {"nazionale", "internazionale"}:
                files[-1]["scope"] = item["scope"]
    return reports, files, sorted(set(editions) - set(names))


def inspect_corpus(root, *, refresh=False):
    root = Path(root).resolve()
    incoming, registry = root / "data/incoming", root / "data/archive.sqlite3"
    if registry.is_symlink() or not registry.resolve().is_relative_to(root):
        raise ValueError("Il registro deve essere interno al progetto.")
    if incoming.is_symlink() or not incoming.resolve().is_relative_to(root):
        raise ValueError("La cartella incoming deve essere interna al progetto.")
    paths = sorted(p for p in incoming.iterdir() if p.suffix.lower() == ".pdf")
    if any(p.is_symlink() or not p.is_file() or p.resolve().parent != incoming.resolve() for p in paths):
        raise ValueError("PDF non regolare o esterno alla cartella incoming.")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    previous = registry_rows(registry)
    changes = {"new": sorted(set(hashes) - set(previous)),
               "modified": sorted(n for n in hashes.keys() & previous.keys() if hashes[n] != previous[n]),
               "unchanged": sorted(n for n in hashes.keys() & previous.keys() if hashes[n] == previous[n]),
               "absent_preserved_in_registry": sorted(set(previous) - set(hashes))}
    aliases = {}
    for name, sha in sorted({**previous, **hashes}.items()):
        aliases.setdefault(sha, []).append(name)
    changes["duplicates"] = {name: [other for other in aliases[sha] if other != name]
                             for name, sha in hashes.items() if len(aliases[sha]) > 1}
    backup = None
    if refresh:
        if registry.is_file():
            directory = root / "data/corpus_updates"
            if directory.is_symlink() or not directory.resolve().is_relative_to(root):
                raise ValueError("Il backup deve restare nell’area dati privata.")
            directory.mkdir(parents=True, exist_ok=True)
            backup = directory / ("archive-before-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3")
            with closing(sqlite3.connect(registry)) as source, closing(sqlite3.connect(backup)) as target:
                source.backup(target)
        prepare_documents(ingest_directory(incoming, registry), registry)
    chunks, warnings = read_active_chunks(registry, incoming)
    collection = open_collection(root / "data/chroma", create=False)
    plan = plan_index(chunks, collection)
    records = stored_records(collection)
    pending_ids = {chunk.id for chunk in plan.pending}
    indexed = [chunk for chunk in chunks if chunk.id not in pending_ids]
    metadata, files, orphan_metadata = metadata_report(root, sorted(hashes), hashes)
    total_counts = Counter(c.metadata["filename"] for c in chunks)
    indexed_counts = Counter(c.metadata["filename"] for c in indexed)
    for item in files:
        item.update(indexed=indexed_counts[item["pdf"]], total=total_counts[item["pdf"]])
    coverage = {"indexed": len(indexed), "total": len(chunks), "files": [f for f in files if f["total"]],
                "partial": len(indexed) < len(chunks), "warnings": warnings}
    coverage["corpus_version"] = source_version(indexed, metadata=coverage["files"])
    documents = []
    with closing(sqlite3.connect(registry.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for name, sha in hashes.items():
            row = db.execute("SELECT result_json FROM extractions WHERE sha256=?", (sha,)).fetchone()
            data = json.loads(row[0]) if row else {}
            config = db.execute("SELECT config_signature,skipped_pages_json FROM chunk_sets WHERE sha256=?", (sha,)).fetchone()
            prepared = config is not None and config[0] == ChunkConfig().signature
            documents.append({"pdf": name, "status": data.get("status", "not_prepared"),
                              "pages": data.get("total_pages", 0), "chunks": total_counts[name],
                              "indexed": indexed_counts[name], "pending": total_counts[name] - indexed_counts[name],
                              "prepared": prepared, "skipped_pages": len(json.loads(config[1])) if config else 0,
                              "change": "modified" if name in changes["modified"] else "duplicate" if name in changes["duplicates"] else "new" if name in changes["new"] else "unchanged"})
    return {"changes": changes, "backup": str(backup) if backup else None,
            "pdfs": len(paths), "unique_contents": len(set(hashes.values())),
            "pages": sum(d["pages"] for d in documents), "chunks": len(chunks),
            "indexed": len(indexed), "pending": len(plan.pending), "metadata_updates": len(plan.metadata_updates),
            "stored_vectors": len(records), "stale_vectors_preserved": len(plan.stale_ids),
            "documents": documents, "metadata": metadata, "orphan_metadata": orphan_metadata,
            "warnings": warnings, "caches": audit_caches(root, chunks, coverage),
            "corpus_version": coverage["corpus_version"],
            "distribution_authorized": False, "api_calls": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--refresh", action="store_true", help="Acquisisce e prepara localmente, con backup preventivo; nessuna API.")
    parser.add_argument("--report", type=Path, help="Scrive un report privato JSON sotto data/corpus_updates.")
    args = parser.parse_args(argv)
    try:
        if args.report:
            report_path = args.report.resolve()
            allowed = (args.root / "data/corpus_updates").resolve()
            if not allowed.is_relative_to(args.root.resolve()) or not report_path.is_relative_to(allowed) or args.report.is_symlink():
                raise ValueError("Il report deve rimanere nell’area dati privata.")
        report = inspect_corpus(args.root, refresh=args.refresh)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error, KeyError, TypeError):
        print("Verifica corpus interrotta: controllare cartella, registro, indice e metadati. Nessuna API eseguita.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
