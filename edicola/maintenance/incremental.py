"""Batch locali espliciti e riprendibili, sul piano d’indicizzazione esistente."""

import hashlib
import json
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from edicola.archive import read_active_chunks
from edicola.embeddings import DIMENSIONS, MODEL, FORMAT_VERSION, EmbeddingError, GeminiEmbedder, api_key, validate_vector
from edicola.indexing import IndexPlan, apply_plan, plan_index
from edicola.maintenance_store import MaintenanceStore, maintenance_lock
from edicola.settings import setting
from edicola.vectorstore import open_collection


def require_local_manager(root):
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    if get_script_run_ctx(suppress_warning=True) is not None or setting("EDICOLA_CLOUD_DEMO", "0", root=Path(root)) == "1":
        raise PermissionError("La manutenzione è riservata alla console locale del gestore.")


@dataclass
class BatchPreview:
    token: str
    total: int
    indexed: int
    missing: int
    chunks: list
    stale_preserved: int
    source_token: str = ""


def preview_batch(root, limit=10, filenames=()):
    return _preview(root, limit, filenames)


def preview_all(root, batch_size=50):
    return _preview(root, batch_size, (), all_missing=True)


def _preview(root, limit, filenames, *, all_missing=False):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Scegliere un batch da 1 a 50 chunk.")
    root = Path(root)
    chunks, warnings = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    if warnings:
        raise ValueError("Preparare prima i documenti nuovi o modificati e verificare le anomalie.")
    available = {name for chunk in chunks for name in json.loads(chunk.metadata["filenames_json"])}
    if set(filenames) - available:
        raise ValueError("Edizione selezionata senza chunk attivi.")
    plan = plan_index(chunks, open_collection(root / "data/chroma"), filenames)
    all_plan = plan if not filenames else plan_index(chunks, open_collection(root / "data/chroma"))
    selected = plan.pending if all_missing else plan.pending[:limit]
    source_token = hashlib.sha256(json.dumps([(c.id, c.fingerprint, c.metadata) for c in chunks], sort_keys=True).encode()).hexdigest()
    token = hashlib.sha256(json.dumps({"model": MODEL, "dimensions": DIMENSIONS, "format": FORMAT_VERSION,
        "limit": limit, "files": sorted(filenames), "all_missing": all_missing,
        "source_token": source_token if all_missing else None,
        "chunks": [(c.id, c.fingerprint, c.metadata) for c in selected]}, sort_keys=True).encode()).hexdigest()
    return BatchPreview(token, len(chunks), len(chunks) - len(all_plan.pending), len(plan.pending), selected, len(plan.stale_ids), source_token)


class DurableEmbedder:
    def __init__(self, root, store, job, factory):
        self.root, self.store, self.job, self.factory = root, store, job, factory
        self.client, self.chunk, self.reused = None, None, False

    def embed(self, prompt):
        require_local_manager(self.root)
        if prompt != self.chunk.prompt:
            raise ValueError("Passaggio diverso dall’anteprima autorizzata.")
        saved = self.store.load_vector(self.chunk)
        self.reused = saved is not None
        if saved is not None:
            return validate_vector(saved)
        if self.client is None:
            def before_attempt():
                require_local_manager(self.root)
                self.store.attempt(self.job)
            self.client = self.factory(api_key(self.root), max_attempts=3,
                                       on_attempt=before_attempt)
        vector = validate_vector(self.client.embed(prompt))
        self.store.stage(self.chunk, vector)  # Durevole PRIMA dell’upsert Chroma.
        return vector

    def close(self):
        if self.client is not None:
            self.client.close()


def reconcile_progress(root, store):
    """Riconcilia anche un crash fra commit Chroma e aggiornamento del diario."""
    root = Path(root)
    chunks, warnings = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    if warnings:
        store.recover()
        return
    pending = {c.id for c in plan_index(chunks, open_collection(root / "data/chroma")).pending}
    store.recover({c.id: c.fingerprint for c in chunks if c.id not in pending})


def run_batch(root, *, limit=10, filenames=(), token, authorize_external=False,
              factory=GeminiEmbedder, progress=None):
    require_local_manager(root)
    if authorize_external is not True:
        raise PermissionError("Autorizzare esplicitamente l’invio del batch a Google Gemini.")
    root = Path(root)
    with maintenance_lock(root), closing(MaintenanceStore(root)) as store:
        reconcile_progress(root, store)
        return _run_locked_batch(root, store, limit=limit, filenames=filenames, token=token,
                                 factory=factory, progress=progress)


def _run_locked_batch(root, store, *, limit, filenames, token, factory, progress=None, source_token=None):
    """Esecuzione condivisa; il chiamante mantiene il lock per tutta l’operazione."""
    latest = store.latest()
    if latest and latest["next_allowed"] > time.time():
        raise RuntimeError("Quota o servizio temporaneamente indisponibili: attendere prima di autorizzare un nuovo batch.")
    preview = preview_batch(root, limit, filenames)
    if token != preview.token or source_token is not None and source_token != preview.source_token:
        raise ValueError("Il piano è cambiato: controllare e autorizzare una nuova anteprima.")
    if not preview.chunks:
        return {"status": "nothing_pending", "completed": 0, "attempts": 0, "reused": 0}
    job = store.start(preview.token, len(preview.chunks), preview.chunks)
    adapter = DurableEmbedder(root, store, job, factory)
    try:
        collection = open_collection(root / "data/chroma", create=True)
        chunks, _ = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
        updates = plan_index(chunks, collection).metadata_updates
        apply_plan(IndexPlan([], updates, [], 0), collection, adapter, limit, prune_stale=False)
        for chunk in preview.chunks:
            require_local_manager(root)
            current = preview_batch(root, limit, filenames)
            if (source_token is not None and current.source_token != source_token
                    or not any(c.id == chunk.id and c.fingerprint == chunk.fingerprint for c in current.chunks)):
                raise ValueError("Le fonti o l’indice sono cambiati durante l’operazione.")
            adapter.chunk = chunk
            apply_plan(IndexPlan([chunk], [], [], 0), collection, adapter, 1, prune_stale=False)
            store.completed(job, adapter.reused, chunk.id)
            store.unstage(chunk)
            if progress:
                progress(store.latest())
        store.finish(job, "completed")
    except EmbeddingError as exc:
        code = str(exc.http_status) if exc.http_status else "network_or_vector"
        temporary = exc.http_status in {408, 429, 500, 502, 503, 504} or exc.http_status is None
        store.finish(job, "paused" if temporary else "failed", code,
                     60 if exc.http_status == 429 else 15 if temporary else 0)
    except KeyboardInterrupt:
        store.finish(job, "interrupted", "manual_stop")
    except Exception:
        store.finish(job, "interrupted", "local_or_source_error")
    finally:
        try:
            adapter.close()
        except Exception:
            pass
    return store.latest()
