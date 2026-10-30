"""Batch persistenti e autorizzazione locale: tutte le API sono simulate."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from unittest.mock import Mock, patch

import httpx
import pytest
from google.genai import errors, types

from edicola.archive import read_active_chunks
from edicola.archive_manager import interactive, main, prepare_changes, show_status
from edicola.corpus_update import inspect_corpus
from edicola.editorial import EditorialConfig, cache_key
from edicola.editorial_selection import read_catalog
from edicola.embeddings import GeminiEmbedder
from edicola.incremental import preview_batch, run_batch
from edicola.maintenance_store import MaintenanceStore, maintenance_lock, recent_batches
from edicola.press_review import ReviewSelection, filter_catalog
from test_corpus_update import corpus, VECTOR, OLD, NEW
from test_ingestion import make_pdf


@pytest.fixture
def prepared(corpus):
    root, collection, _ = corpus
    (root / "data/incoming/third.pdf").write_bytes(make_pdf(("Un altro piano trasporti nel 2026.", "Una misura per trasporti e viabilita.")))
    inspect_corpus(root, refresh=True)
    return root, collection


def simulated_factory(outcomes=()):
    client = Mock()
    good = types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=VECTOR)])
    client.models.embed_content.side_effect = list(outcomes) + [good] * 50
    delays = []
    def factory(key, **kwargs):
        return GeminiEmbedder(key, client=client, sleep=delays.append, **kwargs)
    return factory, client, delays


def run(root, factory, limit=2, **kwargs):
    preview = preview_batch(root, limit)
    return run_batch(root, limit=limit, token=preview.token, authorize_external=True, factory=factory, **kwargs)


def test_unauthorized_and_cloud_or_web_requests_never_create_client(prepared, monkeypatch):
    root, _ = prepared
    factory = Mock(side_effect=AssertionError("Invio vietato"))
    preview = preview_batch(root)
    with pytest.raises(PermissionError):
        run_batch(root, token=preview.token, factory=factory)
    monkeypatch.setenv("EDICOLA_CLOUD_DEMO", "1")
    with pytest.raises(PermissionError):
        run_batch(root, token=preview.token, authorize_external=True, factory=factory)
    monkeypatch.setenv("EDICOLA_CLOUD_DEMO", "0")
    with patch("streamlit.runtime.scriptrunner.get_script_run_ctx", return_value=object()), pytest.raises(PermissionError):
        run_batch(root, token=preview.token, authorize_external=True, factory=factory)
    factory.assert_not_called()
    assert not (root / "data/corpus_updates/manager.sqlite3").exists()


def test_preview_then_batch_preserves_old_vectors_and_resumes_only_missing(prepared):
    root, collection = prepared
    old = collection.get(include=["embeddings", "documents", "metadatas"])
    factory, client, _ = simulated_factory()
    first = run(root, factory, limit=2)
    assert first["status"] == "completed" and first["completed"] == first["attempts"] == 2
    assert preview_batch(root).indexed == 3
    old_after = collection.get(ids=old["ids"], include=["embeddings", "documents", "metadatas"])
    assert old["documents"] == old_after["documents"] and old["metadatas"] == old_after["metadatas"]
    assert (old["embeddings"] == old_after["embeddings"]).all()
    second = run(root, factory, limit=2)
    assert second["completed"] == 1 and preview_batch(root).missing == 0
    assert client.models.embed_content.call_count == 3
    factory_unused = Mock(side_effect=AssertionError("Nessun nuovo invio"))
    assert run(root, factory_unused)["status"] == "nothing_pending"
    factory_unused.assert_not_called()


@pytest.mark.parametrize("code", [429, 503])
def test_temporary_errors_retry_bounded_and_pause_with_cooldown(prepared, code):
    root, _ = prepared
    error = errors.APIError(code, {"error": {"message": "PRIVATE_KEY request-text", "code": code}})
    factory, client, delays = simulated_factory([error] * 3)
    result = run(root, factory)
    assert result["status"] == "paused" and result["error_code"] == str(code)
    assert result["completed"] == 0 and result["attempts"] == 3 and delays == [1, 2]
    with pytest.raises(RuntimeError):
        run(root, factory)
    assert client.models.embed_content.call_count == 3
    # Solo un nuovo invio esplicito dopo il raffreddamento può ripartire.
    with patch("edicola.incremental.time.time", return_value=result["next_allowed"] + 1):
        resumed = run(root, factory)
    assert resumed["status"] == "completed" and resumed["completed"] == 2
    raw = (root / "data/corpus_updates/manager.sqlite3").read_bytes()
    assert b"PRIVATE_KEY" not in raw and b"request-text" not in raw


def test_timeout_is_bounded_and_permanent_model_error_does_not_retry(prepared):
    root, _ = prepared
    factory, client, delays = simulated_factory([httpx.ReadTimeout("private-secret")] * 3)
    result = run(root, factory)
    assert result["status"] == "paused" and result["attempts"] == 3 and delays == [1, 2]
    error = errors.APIError(404, {"error": {"message": "private-secret", "code": 404}})
    factory, client, delays = simulated_factory([error])
    with patch("edicola.incremental.time.time", return_value=result["next_allowed"] + 1):
        result = run(root, factory)
    assert result["status"] == "failed" and result["error_code"] == "404"
    assert client.models.embed_content.call_count == 1 and not delays


def test_interrupted_batch_keeps_commits_and_requires_new_authorization(prepared):
    root, collection = prepared
    factory, client, _ = simulated_factory()
    def interrupt_after_first(job):
        raise KeyboardInterrupt
    result = run(root, factory, progress=interrupt_after_first)
    assert result["status"] == "interrupted" and result["completed"] == 1
    assert collection.count() == 2
    assert recent_batches(root)[0]["status"] == "interrupted"
    result = run(root, factory)
    assert result["status"] == "completed" and result["completed"] == 2
    assert client.models.embed_content.call_count == 3


def test_vector_staged_before_upsert_is_reused_after_storage_failure(prepared):
    root, _ = prepared
    factory, client, _ = simulated_factory()
    from edicola.incremental import apply_plan
    def failing_upsert(plan, *args, **kwargs):
        if plan.pending:
            args[1].embed(plan.pending[0].prompt)  # Risposta già ricevuta e salvata nella coda.
            raise OSError("local failure")
        return apply_plan(plan, *args, **kwargs)
    with patch("edicola.incremental.apply_plan", side_effect=failing_upsert):
        result = run(root, factory, limit=1)
    assert result["status"] == "interrupted" and result["completed"] == 0
    assert client.models.embed_content.call_count == 1
    unused = Mock(side_effect=AssertionError("Il vettore durevole evita una seconda API"))
    result = run(root, unused, limit=1)
    assert result["completed"] == result["reused"] == 1 and result["attempts"] == 0
    unused.assert_not_called()


def test_process_lock_and_stale_preview_prevent_duplicate_sends(prepared):
    root, _ = prepared
    factory = Mock(side_effect=AssertionError("Non inviare"))
    with maintenance_lock(root), pytest.raises(RuntimeError):
        run(root, factory)
    preview = preview_batch(root, 2)
    with pytest.raises(ValueError):
        run_batch(root, limit=1, token=preview.token, authorize_external=True, factory=factory)
    factory.assert_not_called()


def test_dead_run_is_marked_interrupted_on_restart_without_sending(prepared):
    root, _ = prepared
    with maintenance_lock(root), closing(MaintenanceStore(root)) as store:
        store.start("old-plan", 2)
    messages = []
    show_status(root, messages.append)
    assert recent_batches(root)[0]["status"] == "interrupted"
    assert any("interrotto" in message for message in messages)


def test_crash_after_chroma_commit_reconciles_count_without_resending(prepared):
    from edicola.indexing import IndexPlan, apply_plan
    root, collection = prepared
    preview = preview_batch(root, 1)
    chunk = preview.chunks[0]
    with maintenance_lock(root), closing(MaintenanceStore(root)) as store:
        store.start(preview.token, 1, preview.chunks)
        store.stage(chunk, VECTOR)
        apply_plan(IndexPlan([chunk], [], [], 0), collection, Mock(embed=Mock(return_value=VECTOR)), 1, prune_stale=False)
        # Simula l’arresto prima dell’aggiornamento del diario.
    show_status(root, lambda _: None)
    assert recent_batches(root)[0]["completed"] == 1
    assert chunk.id not in {c.id for c in preview_batch(root).chunks}


def test_prepare_skips_already_processed_corpus_and_recognizes_duplicate(prepared):
    root, _ = prepared
    with patch("edicola.corpus_update.ingest_directory", side_effect=AssertionError("Non ripetere acquisizione")), patch(
        "edicola.corpus_update.prepare_documents", side_effect=AssertionError("Non ripetere preprocessing")):
        assert prepare_changes(root)["chunks"] == 4
    (root / "data/incoming/copy.pdf").write_bytes((root / "data/incoming/old.pdf").read_bytes())
    before = inspect_corpus(root)
    assert "copy.pdf" in before["changes"]["duplicates"]
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("Non estrarre duplicati")), patch(
        "edicola.chunking.build_chunks", side_effect=AssertionError("Non rielaborare duplicati")):
        after = prepare_changes(root)
    assert after["chunks"] == 4 and after["unique_contents"] == 3
    assert after["metadata_updates"] == 0  # Alias sincronizzati localmente, senza API.


def test_console_cancel_never_calls_run_and_readonly_cli_is_keyless(prepared, capsys):
    root, _ = prepared
    answers = iter(["3", "10", "", "", "", "0"])
    with patch("edicola.archive_manager.run_batch") as execute, patch("edicola.embeddings.api_key", side_effect=AssertionError("Nessuna chiave")):
        assert interactive(root, read=lambda _: next(answers), write=lambda _: None) == 0
        assert main(["--root", str(root), "--preview"]) == 0
    execute.assert_not_called()
    assert "Nessun invio" in capsys.readouterr().out


def test_dates_latest_and_scoped_cache_ignore_unselected_editions(prepared):
    root, collection = prepared
    catalog = read_catalog(root)
    assert not filter_catalog(catalog, ReviewSelection(date_from="2026-10-20")).chunks
    # Indicizzazione simulata: l’ultima edizione verificata entra senza deduzioni.
    factory, _, _ = simulated_factory()
    run(root, factory, limit=10)
    catalog = read_catalog(root)
    latest = filter_catalog(catalog, ReviewSelection(latest=True))
    assert {c.metadata["filename"] for c in latest.chunks} == {"new.pdf"}
    assert not filter_catalog(catalog, ReviewSelection(date_from="2026-10-24", date_to="2026-10-16")).chunks
    chosen = ReviewSelection(filenames=("old.pdf",), date_to="2026-10-16")
    first = filter_catalog(catalog, chosen)
    changed = replace(catalog, coverage={**catalog.coverage, "total": 100, "corpus_version": "other-corpus"})
    second = filter_catalog(changed, chosen)
    assert cache_key("briefing", "", "test", EditorialConfig(), first) == cache_key("briefing", "", "test", EditorialConfig(), second)
    assert first.coverage["selection_version"] == second.coverage["selection_version"]
    assert inspect_corpus(root)["corpus_version"] == read_catalog(root).coverage["corpus_version"]


def test_curated_metadata_require_confirmation_and_preserve_other_editions(prepared):
    from edicola.maintenance_metadata import confirm_metadata
    root, _ = prepared
    path = root / "data/editions.json"
    original = json.loads(path.read_text())
    with pytest.raises(PermissionError):
        confirm_metadata(root, "new.pdf", "Testata verificata", "2026-10-23")
    assert confirm_metadata(root, "new.pdf", "Testata verificata", "2026-10-23", confirmed=True)
    changed = json.loads(path.read_text())
    assert changed["old.pdf"] == original["old.pdf"]
    assert changed["new.pdf"]["publication"] == "Testata verificata"
    assert list((root / "data/corpus_updates").glob("editions-before-*.json"))
    assert not confirm_metadata(root, "new.pdf", "Testata verificata", "2026-10-23", confirmed=True)
    with pytest.raises(ValueError):
        confirm_metadata(root, "new.pdf", "Testata", "2026-02-30", confirmed=True)
    with pytest.raises(ValueError):
        confirm_metadata(root, "../new.pdf", "Testata", "2026-10-23", confirmed=True)


def test_source_version_changes_even_with_equal_counts(prepared):
    from edicola.corpus_versions import source_version
    root, _ = prepared
    chunks = read_catalog(root).chunks
    changed = [replace(chunks[0], text=chunks[0].text + " Una correzione documentata.")]
    assert len(chunks) == len(changed)
    assert source_version(chunks) != source_version(changed)


def test_local_permission_is_rechecked_before_retry(prepared, monkeypatch):
    root, _ = prepared
    client = Mock()
    def quota_then_revoke(**kwargs):
        monkeypatch.setenv("EDICOLA_CLOUD_DEMO", "1")
        raise errors.APIError(503, {"error": {"message": "service unavailable", "code": 503}})
    client.models.embed_content.side_effect = quota_then_revoke
    def factory(key, **kwargs):
        return GeminiEmbedder(key, client=client, sleep=lambda _: None, **kwargs)
    result = run(root, factory)
    assert result["status"] == "interrupted"
    client.models.embed_content.assert_called_once()


def test_console_snapshot_only_authorized_selection_without_overwriting_existing(prepared):
    from edicola.maintenance_snapshot import prepare_snapshot
    root, _ = prepared
    with pytest.raises(PermissionError):
        prepare_snapshot(root, ["old.pdf"])
    first, manifest = prepare_snapshot(root, ["old.pdf"], authorize_distribution=True)
    assert manifest["pdfs"] == 1 and manifest["indexed"] == 1
    assert not (first / "data/incoming/new.pdf").exists()
    assert not (first / "data/corpus_updates").exists()
    second, _ = prepare_snapshot(root, ["old.pdf"], authorize_distribution=True)
    assert first != second and first.exists() and second.exists()
