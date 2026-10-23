"""CLI esplicita per sincronizzare i chunk SQLite con l'indice locale."""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from edicola.archive import read_active_chunks
from edicola.embeddings import DIMENSIONS, MODEL, EmbeddingError, GeminiEmbedder, api_key
from edicola.vectorstore import open_collection, stored_records


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class IndexPlan:
    pending: list
    metadata_updates: list
    stale_ids: list[str]
    unchanged: int


def plan_index(chunks, collection, filenames=None) -> IndexPlan:
    stored = stored_records(collection)
    desired = {chunk.id: chunk for chunk in chunks}
    pending, updates = [], []
    unchanged = 0
    for chunk in chunks:
        record = stored.get(chunk.id)
        if record is None or record["metadata"].get("input_sha256") != chunk.fingerprint or record["text"] != chunk.text:
            if not filenames or set(filenames).intersection(json.loads(chunk.metadata["filenames_json"])):
                pending.append(chunk)
        elif record["metadata"] != chunk.chroma_metadata:
            updates.append(chunk)
        else:
            unchanged += 1
    return IndexPlan(pending, updates, sorted(set(stored) - set(desired)), unchanged)


def apply_plan(plan: IndexPlan, collection, embedder, limit: int) -> int:
    if limit <= 0:
        raise ValueError("Il limite deve essere positivo.")
    # La riconciliazione locale non genera richieste Gemini.
    for offset in range(0, len(plan.stale_ids), 500):
        collection.delete(ids=plan.stale_ids[offset:offset + 500])
    for chunk in plan.metadata_updates:
        collection.update(ids=[chunk.id], metadatas=[chunk.chroma_metadata])
    completed = 0
    for chunk in plan.pending[:limit]:
        vector = embedder.embed(chunk.prompt)
        collection.upsert(ids=[chunk.id], documents=[chunk.text],
                          metadatas=[chunk.chroma_metadata], embeddings=[vector])
        completed += 1
    return completed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Numero massimo di chunk nuovi/modificati da inviare.")
    parser.add_argument("--dry-run", action="store_true", help="Controllo locale senza chiamate API o modifiche ai vettori.")
    parser.add_argument("--authorize-external", action="store_true", help="Autorizza l'invio a Gemini dei chunk selezionati.")
    parser.add_argument("--pdf", action="append", help="Limita gli invii a questo nome PDF; ripetibile.")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit deve essere positivo")
    if not args.dry_run and (args.limit is None or not args.authorize_external):
        parser.error("Usare --dry-run oppure --limit N --authorize-external per un invio autorizzato.")
    embedder = None
    try:
        key = api_key(ROOT)
        chunks, warnings = read_active_chunks(ROOT / "data/archive.sqlite3", ROOT / "data/incoming")
        if args.pdf:
            available = {name for chunk in chunks for name in json.loads(chunk.metadata["filenames_json"])}
            if set(args.pdf) - available:
                raise RuntimeError("Un PDF selezionato non ha chunk attivi disponibili.")
        collection = open_collection(ROOT / "data/chroma", create=False)
        plan = plan_index(chunks, collection, args.pdf)
        print(json.dumps({
            "model": MODEL, "dimensions": DIMENSIONS, "api_key_configured": bool(key),
            "active_chunks": len(chunks), "already_indexed": plan.unchanged,
            "pending_selected": len(plan.pending), "metadata_updates": len(plan.metadata_updates),
            "stale_to_delete": len(plan.stale_ids),
            "new_chunks_this_run": min(args.limit or len(plan.pending), len(plan.pending)),
            "warnings": warnings, "dry_run": args.dry_run,
        }, ensure_ascii=False, indent=2))
        if args.dry_run:
            return 0
        # Non cancellare un indice sulla base di uno snapshot non ancora preparato.
        if warnings:
            raise RuntimeError("Aggiornare i PDF segnalati tramite Streamlit prima di sincronizzare l'indice.")
        if plan.pending:
            embedder = GeminiEmbedder(key)
        collection = collection or open_collection(ROOT / "data/chroma", create=True)
        completed = apply_plan(plan, collection, embedder, args.limit)
        print(f"Chunk indicizzati in questa esecuzione: {completed}.")
        return 0
    except EmbeddingError as exc:
        print(f"Indicizzazione interrotta: {exc} I chunk già salvati restano persistenti.")
        return 1
    except Exception:
        # Errori SDK/Chroma possono contenere URL, credenziali o testo: non stamparli.
        print("Indicizzazione interrotta. Verificare archivio, compatibilità della collezione, chiave, quota e connessione. I chunk già salvati restano persistenti.")
        return 1
    finally:
        if embedder is not None:
            try:
                embedder.close()
            except Exception:
                print("Chiusura del client Gemini non completata.")


if __name__ == "__main__":
    raise SystemExit(main())
