"""Un’autorizzazione per un insieme finito di mancanti, elaborato in batch <=50."""

from contextlib import closing
from pathlib import Path

from edicola.embeddings import GeminiEmbedder
from edicola.incremental import (_run_locked_batch, preview_all, preview_batch,
                                 reconcile_progress, require_local_manager)
from edicola.maintenance_store import MaintenanceStore, maintenance_lock


def run_all_missing(root, *, token, authorize_external=False, batch_size=50,
                    factory=GeminiEmbedder, progress=None):
    require_local_manager(root)
    if authorize_external is not True:
        raise PermissionError("Autorizzare esplicitamente tutti i chunk del riepilogo.")
    root = Path(root)
    with maintenance_lock(root), closing(MaintenanceStore(root)) as store:
        reconcile_progress(root, store)
        approved = preview_all(root, batch_size)
        if token != approved.token:
            raise ValueError("Il corpus o i mancanti sono cambiati: confermare un nuovo riepilogo.")
        result = {"status": "nothing_pending", "planned": approved.missing, "completed": 0,
                  "remaining": approved.missing, "attempts": 0, "batches_completed": 0, "error_code": ""}
        allowed = {chunk.id for chunk in approved.chunks}
        try:
            # Insieme chiuso: nessuna fonte aggiunta successivamente viene autorizzata.
            while result["remaining"]:
                require_local_manager(root)
                next_batch = preview_batch(root, batch_size)
                if next_batch.source_token != approved.source_token or any(c.id not in allowed for c in next_batch.chunks):
                    result.update(status="interrupted", error_code="local_or_source_error")
                    break
                if not next_batch.chunks:
                    result.update(status="completed", remaining=0)
                    break
                def on_progress(job):
                    if progress:
                        done = result["completed"] + job["completed"]
                        progress({"completed": done, "planned": approved.missing,
                                  "remaining": approved.missing - done,
                                  "indexed": approved.indexed + done, "total": approved.total,
                                  "batch": result["batches_completed"] + 1,
                                  "attempts": result["attempts"] + job["attempts"]})
                job = _run_locked_batch(root, store, limit=batch_size, filenames=(), token=next_batch.token,
                    source_token=approved.source_token, factory=factory, progress=on_progress)
                if not 0 <= job["completed"] <= len(next_batch.chunks):
                    result.update(status="interrupted", error_code="local_or_source_error")
                    break
                allowed.difference_update(c.id for c in next_batch.chunks[:job["completed"]])
                result["completed"] += job["completed"]
                result["remaining"] = approved.missing - result["completed"]
                result["attempts"] += job["attempts"]
                result.update(status=job["status"], error_code=job.get("error_code", ""))
                if job["status"] != "completed":
                    break  # Nessuna attesa/riattivazione automatica dopo quota o errore.
                if not job["completed"]:
                    result.update(status="interrupted", error_code="local_or_source_error")
                    break  # Evita cicli e nuovi invii se l’indice non avanza.
                result["batches_completed"] += 1
        except KeyboardInterrupt:
            result.update(status="interrupted", error_code="manual_stop")
        return result
