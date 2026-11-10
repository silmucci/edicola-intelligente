"""Unione locale dei PDF dello snapshot con vettori già salvati, senza Gemini."""
import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from edicola.archive import read_active_chunks
from edicola.chunking import prepare_documents
from edicola.cloud import export_seed, validate_seed
from edicola.ingestion import ingest_directory
from edicola.indexing import plan_index
from edicola.snapshot_union import plan_union, apply_union
from edicola.vectorstore import open_collection
from test_ingestion import make_pdf


VECTOR = [1.] + [0.] * 767


@pytest.fixture
def archives(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    incoming = root / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "new.pdf").write_bytes(make_pdf(("Una notizia nuova dall'archivio.",)))
    registry = root / "data/archive.sqlite3"
    prepare_documents(ingest_directory(incoming, registry), registry)
    old = tmp_path / "old"
    old_incoming = old / "data/incoming"
    old_incoming.mkdir(parents=True)
    (old_incoming / "historic.pdf").write_bytes(make_pdf(("Notizia di uno storico quotidiano.",)))
    older_registry = old / "data/archive.sqlite3"
    prepare_documents(ingest_directory(old_incoming, older_registry), older_registry)
    chunk = read_active_chunks(older_registry, old_incoming)[0][0]
    collection = open_collection(old / "data/chroma", create=True)
    collection.upsert(ids=[chunk.id], documents=[chunk.text],
                      metadatas=[chunk.chroma_metadata], embeddings=[VECTOR])
    (old / "data/editions.json").write_text(json.dumps({
        "historic.pdf": {"publication": "Giornale storico", "date": "2026-10-25"}
    }))
    export_seed(old, root / "deployment/seed", ["historic.pdf"], authorize_distribution=True)
    return root


def test_snapshot_union_dry_run_preserves_files_and_never_calls_gemini(archives):
    root = archives
    before = (root / "data/archive.sqlite3").read_bytes()
    expected = plan_union(root)
    assert expected["snapshot_pdfs"] == 1
    assert expected["new_local_pdfs"] == 1
    assert expected["pdfs_after_union"] == 2
    assert expected["vectors_to_reuse"] == 1
    assert expected["gemini_api_calls"] == 0
    assert expected["new_files_to_copy"] == 1
    assert (root / "data/archive.sqlite3").read_bytes() == before
    assert not (root / "data/incoming/historic.pdf").exists()
    assert not (root / "data/chroma").exists()


def test_union_reuses_embeddings_preserves_new_pdf_and_is_idempotent(archives):
    root = archives
    local_pdf = root / "data/incoming/new.pdf"
    local_digest = hashlib.sha256(local_pdf.read_bytes()).hexdigest()
    seed = root / "deployment/seed"
    seed_manifest_before = (seed / "manifest.json").read_bytes()
    with patch("google.genai.Client", side_effect=AssertionError("API vietata")), patch(
        "edicola.ingestion.extract_pdf", side_effect=AssertionError("nessuna estrazione")
    ):
        plan = plan_union(root)
        actual = apply_union(root)
    assert actual["pdfs_after_union"] == 2
    assert actual["total_chunks_after_union"] == plan["total_chunks_after_union"]
    assert actual["active_chunks"] == 2
    assert actual["already_indexed"] == 1
    assert actual["pending"] == 1
    assert actual["backup"]
    assert (root / actual["backup"] / "archive.sqlite3").exists()
    assert hashlib.sha256(local_pdf.read_bytes()).hexdigest() == local_digest
    assert (seed / "manifest.json").read_bytes() == seed_manifest_before
    assert validate_seed(seed)["indexed"] == 1
    chunks, warnings = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    assert not warnings
    index = open_collection(root / "data/chroma")
    plan = plan_index(chunks, index)
    assert len(plan.pending) == 1
    assert index.count() == 1
    assert index.get(ids=[next(c.id for c in chunks if c.metadata["filename"] == "historic.pdf")],
                     include=["embeddings"])["embeddings"][0].tolist() == VECTOR
    metadata = json.loads((root / "data/editions.json").read_text())
    assert metadata["historic.pdf"]["date"] == "2026-10-25"
    again = apply_union(root)
    assert again["new_files_to_copy"] == 0
    assert again["vectors_to_reuse"] == 0
    assert again["active_chunks"] == actual["active_chunks"]
    assert open_collection(root / "data/chroma").count() == 1


def test_conflicting_name_is_rejected_without_altering_existing(archives):
    root = archives
    original = root / "data/incoming/new.pdf"
    historic = root / "data/incoming/historic.pdf"
    historic.write_bytes(make_pdf(("Versione locale diversa.",)))
    report_before = plan_union  # Verificare che il conflitto si fermi prima delle scritture.
    before = original.read_bytes()
    with pytest.raises(ValueError, match="Conflitto"):
        report_before(root)
    assert original.read_bytes() == before
    assert not (root / "data/chroma").exists()


def test_invalid_seed_blocks_union_without_writes(archives):
    root = archives
    vector_file = root / "deployment/seed/vectors.json"
    vector_file.write_text('{"invalid": true}')
    with pytest.raises(ValueError):
        plan_union(root)
    assert not (root / "data/chroma").exists()
    assert not (root / "data/incoming/historic.pdf").exists()


def test_union_keeps_existing_editions_and_preserves_local_index(archives):
    root = archives
    local = root / "data/editions.json"
    local.write_text(json.dumps({"new.pdf": {"publication": "Nuovo", "date": "2026-11-10"}}))
    chunks, warnings = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    assert not warnings
    c = chunks[0]
    collection = open_collection(root / "data/chroma", create=True)
    collection.upsert(ids=[c.id], documents=[c.text], metadatas=[c.chroma_metadata], embeddings=[VECTOR])
    result = apply_union(root)
    assert result["already_indexed"] == 2
    assert result["pending"] == 0
    assert open_collection(root / "data/chroma").count() == 2
    editions = json.loads(local.read_text())
    assert editions["new.pdf"]["publication"] == "Nuovo"
    assert editions["historic.pdf"]["publication"] == "Giornale storico"


def test_union_rejects_missing_local_registry(tmp_path):
    root = tmp_path
    (root / "data/incoming").mkdir(parents=True)
    with pytest.raises(ValueError, match="registro"):
        plan_union(root)
