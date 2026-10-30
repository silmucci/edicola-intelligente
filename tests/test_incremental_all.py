"""Piano completo finito: consenso unico, batch <=50, API sempre simulate."""

from unittest.mock import Mock, patch

import httpx
import pytest
from google.genai import errors, types

from edicola.archive_manager import interactive, show_all_preview
from edicola.corpus_update import inspect_corpus
from edicola.embeddings import GeminiEmbedder
from edicola.incremental import preview_all
from edicola.incremental_all import run_all_missing
from edicola.maintenance_store import maintenance_lock, recent_batches
from test_corpus_update import corpus, VECTOR
from test_incremental_manager import prepared, simulated_factory
from test_ingestion import make_pdf


def execute(root, factory, size=50, **kwargs):
    preview = preview_all(root, size)
    return run_all_missing(root, token=preview.token, batch_size=size,
                           authorize_external=True, factory=factory, **kwargs)


def test_confirmation_required_and_console_cancel_makes_no_calls(prepared):
    root, _ = prepared
    factory = Mock(side_effect=AssertionError("Non inviare"))
    with pytest.raises(PermissionError):
        run_all_missing(root, token=preview_all(root).token, factory=factory)
    factory.assert_not_called()
    answers = iter(["6", "", "0"])
    messages = []
    with patch("edicola.archive_manager.run_all_missing") as run:
        interactive(root, read=lambda _: next(answers), write=messages.append)
    run.assert_not_called()
    assert any("3 richieste previste" in text for text in messages)
    assert any("new.pdf: 1" in text for text in messages)
    assert any("Nessun invio" in text for text in messages)


def test_all_continues_automatically_in_batches_of_at_most_50(prepared):
    root, collection = prepared
    original = collection.get(include=["documents", "metadatas", "embeddings"])
    (root / "data/incoming/many.pdf").write_bytes(make_pdf(tuple(f"Notizia trasporti numero {i}." for i in range(49))))
    inspect_corpus(root, refresh=True)
    preview = preview_all(root)
    assert preview.missing == 52
    client = Mock()
    client.models.embed_content.return_value = types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=VECTOR)])
    def factory(key, **kwargs):
        return GeminiEmbedder(key, client=client, sleep=lambda _: None, **kwargs)
    progress = []
    result = execute(root, factory, progress=progress.append)
    assert result["status"] == "completed" and result["completed"] == 52 and result["remaining"] == 0
    assert result["batches_completed"] == 2 and result["attempts"] == 52
    assert [job["planned"] for job in reversed(recent_batches(root))] == [50, 2]
    assert progress[-1]["indexed"] == 53 and progress[-1]["remaining"] == 0
    after = collection.get(ids=original["ids"], include=["documents", "metadatas", "embeddings"])
    assert original["documents"] == after["documents"] and original["metadatas"] == after["metadatas"]
    assert (original["embeddings"] == after["embeddings"]).all()
    unused = Mock(side_effect=AssertionError("Non ripetere embedding"))
    assert execute(root, unused)["status"] == "nothing_pending"
    unused.assert_not_called()


@pytest.mark.parametrize("failure", [429, 503, "timeout", 404])
def test_error_stops_entire_operation_and_resume_skips_saved_chunks(prepared, failure):
    root, _ = prepared
    error = httpx.ReadTimeout("private-text") if failure == "timeout" else errors.APIError(failure, {"error": {"code": failure, "message": "private-text"}})
    good = types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=VECTOR)])
    repetitions = 1 if failure == 404 else 3
    factory, client, _ = simulated_factory([good] + [error] * repetitions)
    result = execute(root, factory, size=2)
    assert result["completed"] == 1 and result["remaining"] == 2
    assert result["status"] == ("failed" if failure == 404 else "paused")
    assert client.models.embed_content.call_count == 1 + repetitions
    assert len(recent_batches(root)) == 1  # Nessun altro batch, nessuna ripartenza automatica.
    allowed_at = recent_batches(root)[0]["next_allowed"] + 1
    if failure != 404:
        with pytest.raises(RuntimeError):
            execute(root, factory)
    with patch("edicola.incremental.time.time", return_value=max(allowed_at, 2_000_000_000)):
        resumed = execute(root, factory)
    assert resumed["completed"] == 2 and resumed["remaining"] == 0
    assert client.models.embed_content.call_count == 3 + repetitions


def test_interrupt_and_lock_cover_the_whole_operation(prepared):
    root, _ = prepared
    factory, client, _ = simulated_factory()
    def stop(state):
        with pytest.raises(RuntimeError), maintenance_lock(root):
            pass
        raise KeyboardInterrupt
    result = execute(root, factory, size=2, progress=stop)
    assert result["status"] == "interrupted" and result["remaining"] == 2
    assert client.models.embed_content.call_count == 1
    assert execute(root, factory)["completed"] == 2
    assert client.models.embed_content.call_count == 3


def test_stale_plan_or_new_sources_are_never_silently_authorized(prepared):
    root, _ = prepared
    old = preview_all(root)
    (root / "data/incoming/added.pdf").write_bytes(make_pdf(("Una fonte aggiunta successivamente.",)))
    inspect_corpus(root, refresh=True)
    factory = Mock(side_effect=AssertionError("Conferma non valida"))
    with pytest.raises(ValueError):
        run_all_missing(root, token=old.token, authorize_external=True, factory=factory)
    factory.assert_not_called()
    factory, client, _ = simulated_factory()
    def change_source(state):
        if state["completed"] == 1:
            (root / "data/incoming/third.pdf").write_bytes(make_pdf(("Una fonte modificata durante il batch.",)))
    result = execute(root, factory, progress=change_source)
    assert result["status"] == "interrupted"
    assert client.models.embed_content.call_count == 1


def test_console_exact_confirmation_passes_approved_plan(prepared):
    root, _ = prepared
    answers = iter(["6", "AUTORIZZO TUTTI 3", "0"])
    expected = preview_all(root)
    with patch("edicola.archive_manager.run_all_missing", return_value={"status": "completed", "completed": 3, "remaining": 0}) as run:
        interactive(root, read=lambda _: next(answers), write=lambda _: None)
    run.assert_called_once()
    assert run.call_args.kwargs["token"] == expected.token
    assert run.call_args.kwargs["authorize_external"] is True


def test_index_drift_does_not_resend_completed_chunks_or_extend_grant(prepared):
    root, collection = prepared
    original = preview_all(root, 2)
    factory, client, _ = simulated_factory()
    def drift(state):
        if state["completed"] == 2:
            collection.delete(ids=[original.chunks[0].id])  # Solo indice sintetico del test.
    result = execute(root, factory, size=2, progress=drift)
    assert result["status"] == "interrupted" and result["error_code"] == "local_or_source_error"
    assert client.models.embed_content.call_count == 2


@pytest.mark.parametrize("size", [0, 51])
def test_invalid_batch_size_is_rejected(prepared, size):
    with pytest.raises(ValueError):
        preview_all(prepared[0], size)
