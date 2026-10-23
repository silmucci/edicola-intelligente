"""Chroma reale in cartelle temporanee; Gemini e modelli locali disabilitati."""

import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from edicola.archive import read_active_chunks
from edicola.chunking import ChunkConfig, prepare_documents
from edicola.embeddings import EmbeddingError, question_prompt
from edicola.indexing import apply_plan, main, plan_index
from edicola.ingestion import ingest_directory
from edicola.rag import ask_question
from edicola.editorial_selection import read_catalog
from edicola.knowledge import generate_knowledge
from google.genai import types
from edicola.search import main as search_main, semantic_search
from edicola.vectorstore import COLLECTION_METADATA, open_collection
from test_ingestion import make_pdf


VECTOR = [1.0] + [0.0] * 767


@pytest.fixture(autouse=True)
def no_external_embeddings():
    with patch("google.genai.Client", side_effect=AssertionError("Gemini reale vietato nei test")), patch(
        "chromadb.utils.embedding_functions.DefaultEmbeddingFunction.__call__",
        side_effect=AssertionError("Embedding locale vietato nei test"),
    ):
        yield


@pytest.fixture
def archive_root(tmp_path):
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "giornale.pdf").write_bytes(make_pdf(("Una notizia. " * 250, "Altra pagina.")))
    registry = tmp_path / "data/archive.sqlite3"
    prepare_documents(ingest_directory(incoming, registry), registry)
    return tmp_path


def snapshot(root):
    return read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")


def fake_embedder():
    return Mock(embed=Mock(return_value=VECTOR))


def test_sqlite_snapshot_is_read_only_and_does_not_reprocess(archive_root):
    path = archive_root / "data/archive.sqlite3"
    before = path.read_bytes()
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError), patch(
        "edicola.chunking.build_chunks", side_effect=AssertionError
    ):
        chunks, warnings = snapshot(archive_root)
    assert not warnings
    assert len(chunks) > 2
    assert path.read_bytes() == before
    assert chunks[0].metadata["filename"] == "giornale.pdf"
    assert chunks[0].metadata["page"] == 1
    assert chunks[0].metadata["total_pages"] == 2


def test_limit_persistence_and_deduplication_across_processes(archive_root):
    chunks, _ = snapshot(archive_root)
    path = archive_root / "data/chroma"
    collection = open_collection(path, create=True)
    embedder = fake_embedder()
    assert collection._embedding_function is None
    assert apply_plan(plan_index(chunks, collection), collection, embedder, 2) == 2
    assert embedder.embed.call_count == 2
    assert collection.count() == 2
    reopened = open_collection(path)
    pending = plan_index(chunks, reopened)
    assert len(pending.pending) == len(chunks) - 2
    assert pending.unchanged == 2
    stored = reopened.get(ids=[chunks[0].id], include=["embeddings", "documents", "metadatas"])
    assert len(stored["embeddings"][0]) == 768
    assert stored["documents"] == [chunks[0].text]
    assert stored["metadatas"][0]["filename"] == "giornale.pdf"
    script = "from pathlib import Path; import sys; from edicola.vectorstore import open_collection; print(open_collection(Path(sys.argv[1])).count())"
    result = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "2"


def test_already_indexed_chunks_make_no_new_calls(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    embedder = fake_embedder()
    apply_plan(plan_index(chunks, collection), collection, embedder, len(chunks))
    embedder.reset_mock()
    assert apply_plan(plan_index(chunks, collection), collection, embedder, 10) == 0
    embedder.embed.assert_not_called()


def test_duplicate_and_rename_update_metadata_without_api(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    incoming = archive_root / "data/incoming"
    (incoming / "copia.pdf").write_bytes((incoming / "giornale.pdf").read_bytes())
    (incoming / "giornale.pdf").unlink()
    registry = archive_root / "data/archive.sqlite3"
    ingest_directory(incoming, registry)
    renamed, _ = snapshot(archive_root)
    assert {chunk.id for chunk in renamed} == {chunk.id for chunk in chunks}
    plan = plan_index(renamed, collection)
    assert not plan.pending
    assert len(plan.metadata_updates) == len(chunks)
    embedder = fake_embedder()
    apply_plan(plan, collection, embedder, 10)
    embedder.embed.assert_not_called()
    assert collection.get(ids=[chunks[0].id])["metadatas"][0]["filename"] == "copia.pdf"
    (incoming / "dup.pdf").write_bytes((incoming / "copia.pdf").read_bytes())
    ingest_directory(incoming, registry)
    duplicated, _ = snapshot(archive_root)
    assert len(duplicated) == len(chunks)
    assert json.loads(duplicated[0].metadata["filenames_json"]) == ["copia.pdf", "dup.pdf"]


def test_changed_text_with_same_id_is_reembedded(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    changed = [replace(chunks[0], text="Testo cambiato"), *chunks[1:]]
    plan = plan_index(changed, collection)
    assert [chunk.id for chunk in plan.pending] == [chunks[0].id]
    embedder = fake_embedder()
    apply_plan(plan, collection, embedder, 10)
    embedder.embed.assert_called_once()
    assert collection.count() == len(chunks)


def test_rechunking_removes_old_vectors(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    registry = archive_root / "data/archive.sqlite3"
    docs = ingest_directory(archive_root / "data/incoming", registry)
    prepare_documents(docs, registry, ChunkConfig(size=600, overlap=100))
    changed, _ = snapshot(archive_root)
    plan = plan_index(changed, collection)
    assert set(plan.stale_ids) == {chunk.id for chunk in chunks}
    apply_plan(plan, collection, fake_embedder(), 1)
    assert collection.count() == 1


def test_deleted_pdf_removed_even_when_sqlite_retains_history(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    (archive_root / "data/incoming/giornale.pdf").unlink()
    current, _ = snapshot(archive_root)
    assert current == []
    apply_plan(plan_index(current, collection), collection, fake_embedder(), 10)
    assert collection.count() == 0


def test_changed_unprocessed_pdf_is_flagged(archive_root):
    (archive_root / "data/incoming/giornale.pdf").write_bytes(b"changed")
    chunks, warnings = snapshot(archive_root)
    assert not chunks
    assert "modificato" in warnings[0]


@pytest.mark.parametrize("field,value", [("model", "other"), ("dimensions", 3072), ("prompt_format", "other")])
def test_incompatible_collection_rejected(archive_root, field, value):
    path = archive_root / "data/chroma"
    collection = open_collection(path, create=True)
    collection.modify(metadata={**COLLECTION_METADATA, field: value})
    with pytest.raises(RuntimeError, match="incompatibile"):
        open_collection(path)


def test_api_failure_preserves_completed_embeddings(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    embedder = Mock()
    embedder.embed.side_effect = [VECTOR, EmbeddingError("Quota esaurita")]
    with pytest.raises(EmbeddingError):
        apply_plan(plan_index(chunks, collection), collection, embedder, 10)
    assert collection.count() == 1
    assert plan_index(chunks, collection).unchanged == 1


def test_search_top_five_uses_question_prompt_and_returns_origin(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    embedder = fake_embedder()
    hits = semantic_search("Quali notizie?", root=archive_root, authorize_external=True, embedder=embedder)
    assert len(hits) == min(5, len(chunks))
    embedder.embed.assert_called_once_with(question_prompt("Quali notizie?"))
    assert all(hit["filename"] == "giornale.pdf" and hit["page"] >= 1 and hit["text"] for hit in hits)
    assert all(abs(hit["distance"]) < 0.0001 for hit in hits)


def test_search_orders_by_distance(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    special = [0.0, 1.0] + [0.0] * 766
    embedder = Mock()
    embedder.embed.side_effect = [special] + [VECTOR] * (len(chunks) - 1)
    apply_plan(plan_index(chunks, collection), collection, embedder, 100)
    query = Mock(embed=Mock(return_value=special))
    hits = semantic_search("Domanda", root=archive_root, authorize_external=True, embedder=query)
    assert hits[0]["id"] == chunks[0].id
    assert hits[0]["distance"] == pytest.approx(0.0)
    assert hits[-1]["distance"] == pytest.approx(1.0)
    assert [hit["distance"] for hit in hits] == sorted(hit["distance"] for hit in hits)


def test_search_excludes_deleted_chunks_before_sync(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    with sqlite3.connect(archive_root / "data/archive.sqlite3") as connection:
        connection.execute("DELETE FROM chunks WHERE id != ?", (chunks[0].id,))
    hits = semantic_search("Notizie?", root=archive_root, authorize_external=True, embedder=fake_embedder())
    assert [hit["id"] for hit in hits] == [chunks[0].id]


def test_search_empty_index_does_not_call_api(archive_root):
    embedder = fake_embedder()
    assert semantic_search("Notizie?", root=archive_root, authorize_external=True, embedder=embedder) == []
    embedder.embed.assert_not_called()
    with pytest.raises(ValueError, match="Autorizzare"):
        semantic_search("Notizie?", root=archive_root, embedder=embedder)


def test_search_cli_uses_existing_vectors_and_only_embeds_question(archive_root, capsys):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    count_before = collection.count()
    embedder = fake_embedder()
    with patch("edicola.search.ROOT", archive_root), patch(
        "edicola.search.GeminiEmbedder", return_value=embedder
    ), patch("edicola.search.api_key", return_value="test-secret"), patch(
        "edicola.ingestion.extract_pdf", side_effect=AssertionError("Estrazione non consentita")
    ), patch("edicola.chunking.build_chunks", side_effect=AssertionError("Preprocessing non consentito")):
        assert search_main(["Quali notizie?", "--authorize-external"]) == 0
    output = capsys.readouterr().out
    assert output.count("PDF: giornale.pdf | Pagina:") == min(5, len(chunks))
    assert output.count("Distanza:") == min(5, len(chunks))
    assert "Una notizia." in output or "Altra pagina." in output
    assert "test-secret" not in output
    embedder.embed.assert_called_once_with(question_prompt("Quali notizie?"))
    embedder.close.assert_called_once()
    assert collection.count() == count_before


@pytest.mark.parametrize("args", [["Domanda?"], ["  ", "--authorize-external"]])
def test_search_cli_validates_question_and_authorization(args):
    with pytest.raises(SystemExit):
        search_main(args)


def test_search_cli_does_not_log_raw_errors(capsys):
    with patch("edicola.search.semantic_search", side_effect=RuntimeError("private-key")):
        assert search_main(["Domanda?", "--authorize-external"]) == 1
    assert "private-key" not in capsys.readouterr().out


@pytest.mark.parametrize("message", ["Gemini API: errore HTTP 429.", "Gemini API non raggiungibile."])
def test_search_cli_handles_api_errors_without_changing_vectors(archive_root, capsys, message):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    before = collection.get(include=["documents", "metadatas", "embeddings"])
    embedder = Mock()
    embedder.embed.side_effect = EmbeddingError(message)
    with patch("edicola.search.ROOT", archive_root), patch(
        "edicola.search.GeminiEmbedder", return_value=embedder
    ), patch("edicola.search.api_key", return_value="test-secret"):
        assert search_main(["Quali sono le notizie principali?", "--authorize-external"]) == 1
    output = capsys.readouterr().out
    assert message in output
    assert "test-secret" not in output
    embedder.embed.assert_called_once_with(question_prompt("Quali sono le notizie principali?"))
    embedder.close.assert_called_once()
    after = collection.get(include=["documents", "metadatas", "embeddings"])
    assert after["ids"] == before["ids"]
    assert after["documents"] == before["documents"]
    assert after["metadatas"] == before["metadatas"]
    assert (after["embeddings"] == before["embeddings"]).all()


def test_rag_reuses_real_retrieval_without_vector_writes(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    before = collection.get(include=["documents", "metadatas", "embeddings"])
    client = Mock()
    client.models.generate_content.return_value = Mock(
        text=json.dumps({"sufficient": False, "claims": []}),
        candidates=[Mock(finish_reason=types.FinishReason.STOP)],
    )
    embedder = fake_embedder()
    with patch("edicola.search.GeminiEmbedder", return_value=embedder), patch(
        "edicola.search.api_key", return_value="test-key"
    ), patch("edicola.rag.api_key", return_value="test-key"), patch(
        "edicola.ingestion.extract_pdf", side_effect=AssertionError("Estrazione vietata")
    ), patch("edicola.chunking.build_chunks", side_effect=AssertionError("Preprocessing vietato")):
        result = ask_question("Quali notizie?", root=archive_root, authorize_external=True, client=client)
    assert len(result.sources) == min(3, len(chunks))
    embedder.embed.assert_called_once_with(question_prompt("Quali notizie?"))
    client.models.generate_content.assert_called_once()
    after = collection.get(include=["documents", "metadatas", "embeddings"])
    assert after["ids"] == before["ids"]
    assert after["metadatas"] == before["metadatas"]
    assert after["documents"] == before["documents"]
    assert (after["embeddings"] == before["embeddings"]).all()


def test_search_top_k_limits_retrieval_and_logs_embedding_failure(archive_root, caplog):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    embedder = fake_embedder()
    with caplog.at_level("INFO", logger="edicola"):
        hits = semantic_search("Domanda privata", root=archive_root, authorize_external=True,
                               embedder=embedder, top_k=3, request_id="query-test")
    assert len(hits) == 3
    assert "request_id=query-test phase=query_embedding model='gemini-embedding-2' event=success" in caplog.text
    embedder.embed.side_effect = EmbeddingError("Messaggio sicuro", http_status=503)
    caplog.clear()
    with caplog.at_level("INFO", logger="edicola"), pytest.raises(EmbeddingError):
        semantic_search("Domanda privata", root=archive_root, authorize_external=True,
                        embedder=embedder, request_id="failure-test")
    assert "request_id=failure-test phase=query_embedding model='gemini-embedding-2' event=error http_status=503" in caplog.text
    assert "Domanda privata" not in caplog.text


def test_editorial_catalog_counts_only_available_vectors_and_optional_editions(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 2)
    collection.upsert(ids=["historical-id"], documents=["Storico escluso."], embeddings=[VECTOR],
                      metadatas=[{"input_sha256": "old"}])
    catalog = read_catalog(archive_root)
    assert len(catalog.chunks) == 2
    assert catalog.coverage["indexed"] == 2
    assert catalog.coverage["total"] == len(chunks)
    assert catalog.coverage["partial"]
    assert catalog.coverage["warnings"]  # Testata e data non inventate.
    assert catalog.coverage["files"][0]["publication"] == ""
    path = archive_root / "data/editions.json"
    path.write_text(json.dumps({"giornale.pdf": {"publication": "Testata verificata", "date": "2026-10-22"}}))
    catalog = read_catalog(archive_root)
    assert catalog.coverage["files"][0]["date"] == "2026-10-22"
    assert not catalog.coverage["warnings"]
    assert collection.count() == 3  # Nessuna modifica all'indice durante il controllo.


def test_dossier_diverse_search_embeds_topic_only_once(archive_root):
    incoming = archive_root / "data/incoming"
    (incoming / "secondo.pdf").write_bytes(make_pdf(("Altre notizie del quotidiano.",)))
    registry = archive_root / "data/archive.sqlite3"
    prepare_documents(ingest_directory(incoming, registry), registry)
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    before = collection.count()
    embedder = fake_embedder()
    hits = semantic_search("Notizie?", authorize_external=True, root=archive_root,
                           embedder=embedder, top_k=5, diversify_by_pdf=True)
    assert len({hit["filename"] for hit in hits[:2]}) == 2
    assert len(hits) == 5
    embedder.embed.assert_called_once()
    assert collection.count() == before


def test_knowledge_generation_does_not_write_existing_sqlite_or_vectors(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 2)
    registry = archive_root / "data/archive.sqlite3"
    sql_before = registry.read_bytes()
    sql_files = set(archive_root.rglob("*.sqlite3"))
    before = collection.get(include=["documents", "metadatas", "embeddings"])
    def structured(_client, _model, prompt, _schema, *, system_instruction):
        assert "massimo 10" in system_instruction
        source = json.loads(prompt)["sources"][0]
        return json.dumps({"nodes": [{"id": "N1", "kind": "concept", "label": {
            "text": source["text"].split()[0], "evidence": [{"source_id": source["source_id"], "quote": source["text"]}]}}], "edges": []})
    with patch("edicola.search.GeminiEmbedder", return_value=fake_embedder()), patch(
        "edicola.search.api_key", return_value="test-key"
    ), patch("edicola.knowledge.api_key", return_value="test-key"), patch(
        "edicola.knowledge.generate_data", side_effect=structured
    ):
        result = generate_knowledge("map", "Notizie", authorize_external=True, root=archive_root, client=Mock())
    assert result.data["nodes"]
    assert registry.read_bytes() == sql_before
    assert set(archive_root.rglob("*.sqlite3")) == sql_files
    after = collection.get(include=["documents", "metadatas", "embeddings"])
    assert before["ids"] == after["ids"]
    assert before["metadatas"] == after["metadatas"]
    assert before["documents"] == after["documents"]
    assert (before["embeddings"] == after["embeddings"]).all()


def test_dry_run_has_no_api_calls_no_key_or_chroma_creation(archive_root, capsys):
    with patch("edicola.indexing.ROOT", archive_root), patch("edicola.indexing.api_key", return_value=""):
        assert main(["--dry-run", "--limit", "10"]) == 0
    assert not (archive_root / "data/chroma").exists()
    result = json.loads(capsys.readouterr().out)
    assert not result["api_key_configured"]
    assert result["new_chunks_this_run"] == min(10, result["active_chunks"])


@pytest.mark.parametrize("args", [[], ["--limit", "10"], ["--authorize-external"], ["--limit", "0", "--dry-run"]])
def test_cli_requires_limit_and_authorization(args):
    with pytest.raises(SystemExit):
        main(args)


def test_cli_limit_uses_only_mocked_embeddings(archive_root, capsys):
    embedder = fake_embedder()
    with patch("edicola.indexing.ROOT", archive_root), patch("edicola.indexing.api_key", return_value="test-secret"), patch(
        "edicola.indexing.GeminiEmbedder", return_value=embedder
    ):
        assert main(["--limit", "2", "--authorize-external"]) == 0
    assert embedder.embed.call_count == 2
    assert "test-secret" not in capsys.readouterr().out


def test_dry_run_reports_deletions_without_mutating_index(archive_root, capsys):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    (archive_root / "data/incoming/giornale.pdf").unlink()
    with patch("edicola.indexing.ROOT", archive_root), patch("edicola.indexing.api_key", return_value=""):
        assert main(["--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["stale_to_delete"] == len(chunks)
    assert collection.count() == len(chunks)


def test_pdf_filter_does_not_delete_other_documents(archive_root):
    incoming = archive_root / "data/incoming"
    registry = archive_root / "data/archive.sqlite3"
    (incoming / "altro.pdf").write_bytes(make_pdf(("Altre notizie.",)))
    prepare_documents(ingest_directory(incoming, registry), registry)
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    plan = plan_index(chunks, collection, ["giornale.pdf"])
    assert all(chunk.metadata["filename"] == "giornale.pdf" for chunk in plan.pending)
    apply_plan(plan, collection, fake_embedder(), 100)
    plan = plan_index(chunks, collection, ["altro.pdf"])
    assert len(plan.pending) == 1
    assert not plan.stale_ids
    apply_plan(plan, collection, fake_embedder(), 100)
    assert collection.count() == len(chunks)


def test_actual_vector_dimension_is_checked_before_api(archive_root):
    path = archive_root / "data/chroma"
    collection = open_collection(path, create=True)
    collection.add(ids=["invalid"], embeddings=[[1.0] * 3072])
    with pytest.raises(RuntimeError, match="dimensionalità"):
        open_collection(path)


def test_incomplete_snapshot_does_not_delete_existing_index(archive_root, capsys):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    (archive_root / "data/incoming/giornale.pdf").write_bytes(b"changed")
    with patch("edicola.indexing.ROOT", archive_root), patch("edicola.indexing.api_key", return_value=""):
        assert main(["--limit", "10", "--authorize-external"]) == 1
    assert collection.count() == len(chunks)


def test_pdf_content_update_removes_old_embeddings_and_indexes_only_new(archive_root):
    chunks, _ = snapshot(archive_root)
    collection = open_collection(archive_root / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, fake_embedder(), 100)
    incoming = archive_root / "data/incoming"
    (incoming / "giornale.pdf").write_bytes(make_pdf(("Nuova edizione.",)))
    registry = archive_root / "data/archive.sqlite3"
    prepare_documents(ingest_directory(incoming, registry), registry)
    changed, warnings = snapshot(archive_root)
    assert not warnings
    plan = plan_index(changed, collection)
    assert set(plan.stale_ids) == {chunk.id for chunk in chunks}
    assert len(plan.pending) == 1
    embedder = fake_embedder()
    apply_plan(plan, collection, embedder, 10)
    assert collection.count() == 1
    embedder.embed.assert_called_once()
