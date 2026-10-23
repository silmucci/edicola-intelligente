"""Ricerca semantica senza generazione di risposte LLM."""

import argparse
import logging
from pathlib import Path
from uuid import uuid4

from edicola.archive import read_active_chunks
from edicola.embeddings import MODEL, EmbeddingError, GeminiEmbedder, api_key, question_prompt
from edicola.indexing import ROOT, plan_index
from edicola.vectorstore import open_collection


logger = logging.getLogger(__name__)


def semantic_search(question: str, *, authorize_external=False, root: Path = ROOT, embedder=None,
                    top_k: int = 5, request_id: str | None = None, diversify_by_pdf=False) -> list[dict]:
    """Invia solo la domanda a Gemini e restituisce fino a 5 chunk indicizzati attuali."""
    if not question.strip():
        raise ValueError("Inserire una domanda non vuota.")
    if not authorize_external:
        raise ValueError("Autorizzare esplicitamente l'invio della domanda con authorize_external=True.")
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("top_k deve essere un intero da 1 a 5.")
    request_id = request_id or uuid4().hex[:12]
    chunks, warnings = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    if warnings:
        raise RuntimeError("Archivio non aggiornato: aprire Streamlit prima della ricerca.")
    collection = open_collection(root / "data/chroma")
    if collection is None or not collection.count():
        return []
    plan = plan_index(chunks, collection)
    excluded = set(plan.stale_ids) | {chunk.id for chunk in plan.pending}
    # Esclude anche vettori diventati obsoleti dopo modifiche non ancora sincronizzate.
    eligible = [chunk for chunk in chunks if chunk.id not in excluded]
    if not eligible:
        return []
    own_client = embedder is None
    embedder = embedder or GeminiEmbedder(api_key(root))
    try:
        logger.info("request_id=%s phase=query_embedding model=%r event=start", request_id, MODEL)
        try:
            vector = embedder.embed(question_prompt(question))
        except EmbeddingError as exc:
            logger.error("request_id=%s phase=query_embedding model=%r event=error http_status=%s",
                         request_id, MODEL, exc.http_status if exc.http_status is not None else "-")
            raise
        logger.info("request_id=%s phase=query_embedding model=%r event=success", request_id, MODEL)
        if diversify_by_pdf:
            # Opzione editoriale: una sola embedding della domanda, ricerca per edizione.
            # Il percorso del chatbot rimane invariato.
            editions = {}
            for chunk in eligible:
                editions.setdefault(chunk.metadata["pdf_sha256"], []).append(chunk)
            queues = []
            current = {chunk.id: chunk for chunk in eligible}
            for digest, edition in sorted(editions.items()):
                batch = collection.query(
                    query_embeddings=[vector], n_results=min(top_k, len(edition)),
                    where={"$and": [
                        {"pdf_sha256": digest},
                        {"input_sha256": {"$in": [chunk.fingerprint for chunk in edition]}},
                    ]}, include=["documents", "distances"],
                )
                items = [{"id": identity, "text": text, **current[identity].metadata, "distance": distance}
                         for identity, text, distance in zip(batch["ids"][0], batch["documents"][0], batch["distances"][0])]
                if items:
                    queues.append(items)
            queues.sort(key=lambda items: (items[0]["distance"], items[0]["id"]))
            hits = []
            while queues and len(hits) < top_k:
                for items in queues:
                    hits.append(items.pop(0))
                    if len(hits) == top_k:
                        break
                queues = [items for items in queues if items]
            return hits
        result = collection.query(
            query_embeddings=[vector], n_results=min(top_k, len(eligible)),
            where={"input_sha256": {"$in": [chunk.fingerprint for chunk in eligible]}},
            include=["documents", "metadatas", "distances"],
        )
        current = {chunk.id: chunk for chunk in eligible}
        return [
            {"id": identity, "text": text, **current[identity].metadata, "distance": distance}
            for identity, text, distance in zip(result["ids"][0], result["documents"][0], result["distances"][0])
        ]
    finally:
        if own_client:
            embedder.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cerca fino a cinque chunk nell'indice semantico esistente.")
    parser.add_argument("question", help="Domanda da cercare, racchiusa tra virgolette.")
    parser.add_argument("--authorize-external", action="store_true", help="Autorizza l'invio della sola domanda a Gemini.")
    args = parser.parse_args(argv)
    if not args.question.strip():
        parser.error("Inserire una domanda non vuota.")
    if not args.authorize_external:
        parser.error("Usare --authorize-external per autorizzare l'invio della domanda a Gemini.")
    try:
        hits = semantic_search(args.question, authorize_external=True, root=ROOT)
    except EmbeddingError as exc:
        print(f"Ricerca interrotta: {exc}")
        return 1
    except Exception:
        # Non esporre errori SDK grezzi, URL o credenziali.
        print("Ricerca interrotta: verificare archivio, indice, chiave API e connessione.")
        return 1
    if not hits:
        print("Nessun chunk indicizzato attuale disponibile. Eseguire prima l'indicizzazione esplicita.")
    for rank, hit in enumerate(hits, start=1):
        print(f"\n{rank}. PDF: {hit['filename']} | Pagina: {hit['page']} | Distanza: {hit['distance']:.6f}")
        print(f"Chunk: {hit['id']}")
        print(hit["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
