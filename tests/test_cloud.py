"""Deployment con dati sintetici, Chroma locale e nessuna chiamata Gemini."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola.archive import read_active_chunks
from edicola.chunking import prepare_documents
from edicola.cloud import digest, export_seed, prepare_cloud, registered_files, validate_seed
from edicola.embeddings import api_key
from edicola.ingestion import ingest_directory
from edicola.settings import setting
from edicola.vectorstore import open_collection
from test_ingestion import make_pdf

VECTOR = [1.0] + [0.0] * 767


@pytest.fixture(autouse=True)
def no_gemini():
    with patch("google.genai.Client", side_effect=AssertionError("API vietata")), patch(
        "chromadb.utils.embedding_functions.DefaultEmbeddingFunction.__call__", side_effect=AssertionError("Modello locale vietato")
    ):
        yield


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    incoming = root / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "demo.pdf").write_bytes(make_pdf(("Una notizia dimostrativa. " * 130,)))
    (incoming / "privato.pdf").write_bytes(make_pdf(("Contenuto non autorizzato.",)))
    registry = root / "data/archive.sqlite3"
    prepare_documents(ingest_directory(incoming, registry), registry)
    chunks, _ = read_active_chunks(registry, incoming)
    collection = open_collection(root / "data/chroma", create=True)
    chunk = next(c for c in chunks if c.metadata["filename"] == "demo.pdf")
    collection.upsert(ids=[chunk.id], documents=[chunk.text], metadatas=[chunk.chroma_metadata], embeddings=[VECTOR])
    (root / "data/profiles.sqlite3").write_bytes(b"private-profile")
    (root / ".env").write_text("GEMINI_API_KEY=private-key", encoding="utf-8")
    (root / "data/editions.json").write_text(json.dumps({"demo.pdf": {"publication": "Demo", "date": "2026-10-23"}, "privato.pdf": {"publication": "Privato"}}), encoding="utf-8")
    return root


def seed(source, target):
    destination = target / "deployment/seed"
    export_seed(source, destination, ["demo.pdf"], authorize_distribution=True)
    return destination


def test_export_only_authorized_current_data(source, tmp_path):
    before = (source / "data/archive.sqlite3").read_bytes()
    destination = seed(source, tmp_path / "cloud")
    manifest = validate_seed(destination)
    assert manifest["pdfs"] == 1 and manifest["indexed"] == 1
    assert manifest["chunks"] > manifest["indexed"]  # Archivio parziale conservato.
    assert not (destination / ".env").exists()
    assert not (destination / "data/profiles.sqlite3").exists()
    assert not (destination / "data/incoming/privato.pdf").exists()
    assert "privato.pdf" not in (destination / "data/editions.json").read_text()
    with sqlite3.connect(destination / "data/archive.sqlite3") as db:
        assert db.execute("SELECT filename FROM sources").fetchall() == [("demo.pdf",)]
        assert db.execute("SELECT count(*) FROM extractions").fetchone()[0] == 1
    assert before == (source / "data/archive.sqlite3").read_bytes()


@pytest.mark.parametrize("names,authorized", [(["demo.pdf"], False), ([], True), (["../demo.pdf"], True), (["C:\\demo.pdf"], True), (["demo.pdf", "demo.pdf"], True), (["missing.pdf"], True)])
def test_export_requires_authorization_and_safe_explicit_names(source, tmp_path, names, authorized):
    with pytest.raises(ValueError):
        export_seed(source, tmp_path / "export", names, authorize_distribution=authorized)


def test_restore_persists_vectors_without_extraction_or_embeddings(source, tmp_path):
    root = tmp_path / "cloud"
    seed(source, root)
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError), patch("edicola.chunking.build_chunks", side_effect=AssertionError):
        runtime = prepare_cloud(root)
        registry = runtime / "data/archive.sqlite3"
        documents = ingest_directory(runtime / "data/incoming", registry)
        assert prepare_documents(documents, registry)[0].chunks
        collection = open_collection(runtime / "data/chroma")
        assert collection.count() == 1
        assert collection.get(include=["embeddings"])["embeddings"][0].tolist() == VECTOR
        assert collection._embedding_function is None
        with patch("edicola.vectorstore.open_collection", side_effect=AssertionError("Nessun ripristino al rerun")):
            assert prepare_cloud(root) == runtime
    assert runtime != source
    assert not (runtime / "data/profiles.sqlite3").exists()


def test_restore_missing_seed_fails_closed(tmp_path):
    with pytest.raises(OSError):
        prepare_cloud(tmp_path)
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("kind", ["changed_pdf", "unexpected_secret", "traversal", "wrong_model", "wrong_config"])
def test_reject_invalid_seed(source, tmp_path, kind):
    destination = seed(source, tmp_path / "cloud")
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if kind == "changed_pdf":
        (destination / "data/incoming/demo.pdf").write_bytes(b"changed")
    elif kind == "unexpected_secret":
        (destination / ".env").write_text("private")
    elif kind == "traversal":
        manifest["files"]["../secret.pdf"] = "a" * 64
    elif kind == "wrong_model":
        manifest["collection"]["dimensions"] = 42
    else:
        with sqlite3.connect(destination / "data/archive.sqlite3") as db:
            db.execute("UPDATE chunk_sets SET config_signature='old'")
        manifest["files"]["data/archive.sqlite3"] = digest(destination / "data/archive.sqlite3")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_seed(destination)


def test_cloud_ui_stops_before_ingestion_when_seed_missing(monkeypatch):
    monkeypatch.setenv("EDICOLA_CLOUD_DEMO", "1")
    with patch("edicola.cloud.prepare_cloud", side_effect=FileNotFoundError), patch("edicola.ingestion.ingest_directory", side_effect=AssertionError("Acquisizione non autorizzata")):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
    assert not app.exception
    assert any("Snapshot cloud assente" in message.value for message in app.error)
    assert any("accesso Google e database configurati" in message.value for message in app.info)


def test_settings_precedence_and_local_key(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=local-test", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("streamlit.secrets", {"GEMINI_API_KEY": "cloud-test"}):
        assert api_key(tmp_path) == "cloud-test"
        assert api_key(tmp_path) == "cloud-test"
        monkeypatch.setenv("GEMINI_API_KEY", "env-test")
        assert api_key(tmp_path) == "env-test"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("streamlit.secrets", {}):
        assert api_key(tmp_path) == "local-test"
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert setting("GEMINI_API_KEY", root=tmp_path) == "local-test"


def test_no_overwrite_existing_export(source, tmp_path):
    destination = seed(source, tmp_path / "cloud")
    with pytest.raises(ValueError, match="destinazione"):
        export_seed(source, destination, ["demo.pdf"], authorize_distribution=True)


def test_runtime_changed_pdf_prevents_reprocessing(source, tmp_path):
    root = tmp_path / "cloud"
    seed(source, root)
    runtime = prepare_cloud(root)
    (runtime / "data/incoming/demo.pdf").write_bytes(b"changed")
    with pytest.raises(ValueError):
        registered_files(runtime)


def test_cloud_full_start_and_rerun_make_no_external_calls(source, tmp_path, monkeypatch):
    root = tmp_path / "cloud"
    seed(source, root)
    runtime = prepare_cloud(root)
    monkeypatch.setenv("EDICOLA_CLOUD_DEMO", "1")
    monkeypatch.setenv("EDICOLA_ARCHIVE_DIAGNOSTICS", "0")
    with patch("edicola.cloud.prepare_cloud", return_value=runtime), patch("edicola.ingestion.extract_pdf", side_effect=AssertionError), patch("edicola.chunking.build_chunks", side_effect=AssertionError):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
        assert not app.exception
        assert len(app.tabs) == 7
        assert app.button(key="rag_submit")
        assert app.button(key="account_login").disabled
        assert not app.multiselect  # Nessun fallback al profilo condiviso quando mancano i Secrets.
        app.run()
        assert not app.exception


def test_invalid_vectors_do_not_create_index(source, tmp_path):
    root = tmp_path / "cloud"
    destination = seed(source, root)
    vectors = destination / "vectors.json"
    records = json.loads(vectors.read_text())
    records[0]["embedding"] = [1.0]
    vectors.write_text(json.dumps(records), encoding="utf-8")
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["vectors.json"] = digest(vectors)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Embedding non valido"):
        prepare_cloud(root)
    assert not list((root / ".cloud-runtime").glob("*/data/chroma/chroma.sqlite3"))


def test_gitignore_protects_private_data(tmp_path):
    import shutil
    import subprocess
    git = shutil.which("git")
    if not git:
        pytest.skip("Git non installato")
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / ".gitignore", tmp_path / ".gitignore")
    private = [".env", ".streamlit/secrets.toml", "data/profiles.sqlite3", "data/new_cache.json", "data/incoming/a.pdf", "deployment/seed/vectors.json", ".cloud-runtime/x/data/archive.sqlite3", "evaluation/results/private.csv"]
    result = subprocess.run([git, "-C", str(tmp_path), "check-ignore", "--stdin", "-z"], input=("\0".join(private) + "\0").encode(), capture_output=True, check=True)
    assert set(result.stdout.decode().rstrip("\0").split("\0")) == set(private)
    public = ["app.py", "requirements.txt", ".env.example", "deployment/secrets.example.toml", "data/incoming/.gitkeep", "DEPLOYMENT.md"]
    result = subprocess.run([git, "-C", str(tmp_path), "check-ignore", "--stdin", "-z"], input=("\0".join(public) + "\0").encode(), capture_output=True)
    assert not result.stdout
