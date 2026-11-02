"""Vecchie e nuove edizioni: corpus reale sintetico e sole API simulate."""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from google.genai import types

from edicola.archive import read_active_chunks
from edicola.chunking import prepare_documents
from edicola.corpus_update import inspect_corpus, main
from edicola.corpus_cache import audit_caches, product_status
from edicola.editorial import generate_product
from edicola.editorial_selection import read_catalog
from edicola.indexing import apply_plan, plan_index
from edicola.ingestion import ingest_directory
from edicola.knowledge import generate_knowledge
from edicola.infographic import build_infographic
from edicola.press_review import ReviewSelection, filter_catalog, review_groups
from edicola.podcast import generate_podcast
from edicola.podcast_text import list_products
from edicola.rag import ask_question
from edicola.search import semantic_search
from edicola.vectorstore import open_collection
from edicola.cloud import export_seed, validate_seed, main as cloud_main
from test_ingestion import make_pdf
from test_podcast import fake_client

VECTOR = [1.0] + [0.0] * 767
OLD = "Il Comune approva il piano trasporti il 12 ottobre 2026."
NEW = "La Regione finanzia il piano trasporti il 23 ottobre 2026."


@pytest.fixture
def corpus(tmp_path):
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "old.pdf").write_bytes(make_pdf((OLD,)))
    prepare_documents(ingest_directory(incoming, tmp_path / "data/archive.sqlite3"), tmp_path / "data/archive.sqlite3")
    chunks, _ = read_active_chunks(tmp_path / "data/archive.sqlite3", incoming)
    collection = open_collection(tmp_path / "data/chroma", create=True)
    embedder = Mock(embed=Mock(return_value=VECTOR))
    apply_plan(plan_index(chunks, collection), collection, embedder, 1)
    (incoming / "new.pdf").write_bytes(make_pdf((NEW,)))
    (tmp_path / "data/editions.json").write_text(json.dumps({
        "old.pdf": {"publication": "Testata prova", "date": "2026-10-16"},
        "new.pdf": {"publication": "Testata prova", "date": "2026-10-23"}}), encoding="utf-8")
    with patch("google.genai.Client", side_effect=AssertionError("API reali vietate")):
        yield tmp_path, collection, embedder


def test_refresh_only_new_and_preserves_old_chunks_vectors_and_extractions(corpus):
    root, collection, _ = corpus
    old = collection.get(include=["embeddings", "documents", "metadatas"])
    from edicola.ingestion import extract_pdf
    from edicola.chunking import build_chunks
    with patch("edicola.ingestion.extract_pdf", wraps=extract_pdf) as extract, patch(
        "edicola.chunking.build_chunks", wraps=build_chunks) as chunking:
        report = inspect_corpus(root, refresh=True)
        assert extract.call_count == chunking.call_count == 1
    assert report["changes"]["new"] == ["new.pdf"]
    assert (report["pdfs"], report["chunks"], report["indexed"], report["pending"]) == (2, 2, 1, 1)
    assert report["backup"] and report["api_calls"] == 0
    after = collection.get(include=["embeddings", "documents", "metadatas"])
    assert old["ids"] == after["ids"] and old["documents"] == after["documents"]
    assert old["metadatas"] == after["metadatas"]
    assert (old["embeddings"] == after["embeddings"]).all()
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("Estrazione duplicata")), patch(
        "edicola.chunking.build_chunks", side_effect=AssertionError("Chunking duplicato")):
        assert inspect_corpus(root, refresh=True)["pending"] == 1


def test_conservative_index_retains_historical_vectors_but_search_excludes_them(corpus):
    root, collection, embedder = corpus
    (root / "data/incoming/old.pdf").write_bytes(make_pdf(("Il Comune modifica il piano trasporti nel 2026.",)))
    inspect_corpus(root, refresh=True)
    chunks, _ = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    plan = plan_index(chunks, collection)
    assert len(plan.stale_ids) == 1
    apply_plan(plan, collection, embedder, 10, prune_stale=False)
    assert collection.count() == 3
    hits = semantic_search("trasporti", root=root, authorize_external=True, embedder=embedder)
    assert {hit["id"] for hit in hits} == {chunk.id for chunk in chunks}
    embedder.reset_mock()
    assert apply_plan(plan_index(chunks, collection), collection, embedder, 10, prune_stale=False) == 0
    embedder.embed.assert_not_called()


def test_metadata_flags_conflict_and_never_infers_from_filename(corpus):
    root, _, _ = corpus
    (root / "data/incoming/new.pdf").write_bytes(make_pdf(("Edizione del 24/10/2026. " + NEW,)))
    report = inspect_corpus(root, refresh=True)
    assert "date_conflicts_with_header" in report["metadata"]["new.pdf"]["issues"]
    (root / "data/editions.json").unlink()
    report = inspect_corpus(root)
    assert report["metadata"]["new.pdf"]["date"] == ""
    assert "missing_publication" in report["metadata"]["new.pdf"]["issues"]


def test_cli_readonly_without_key_and_protects_private_report(corpus, capsys):
    root, _, _ = corpus
    inspect_corpus(root, refresh=True)
    before = (root / "data/archive.sqlite3").read_bytes()
    with patch("edicola.embeddings.api_key", side_effect=AssertionError("Nessuna chiave necessaria")):
        assert main(["--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["api_calls"] == 0
    assert (root / "data/archive.sqlite3").read_bytes() == before
    assert main(["--root", str(root), "--report", str(root / "public.json")]) == 1
    assert not (root / "public.json").exists()


def simulated_text_response(**kwargs):
    prompt = json.loads(kwargs["contents"])
    sources = prompt["sources"]
    def claim(source, text=None):
        return {"text": text or source["text"], "evidence": [{"source_id": source["source_id"], "quote": source["text"]}]}
    task = prompt.get("task")
    if task == "briefing":
        value = {"sufficient": True, "news": [{"title": claim(s), "summary": claim(s)} for s in sources]}
    elif task == "timeline":
        value = {"events": [{"title": claim(s), "description": claim(s),
                            "event_date": "2026-10-12" if "Comune" in s["text"] else "2026-10-23",
                            "date_evidence": {"source_id": s["source_id"], "quote": s["text"]}} for s in sources]}
    elif task == "map":
        value = {"nodes": [{"id": f"N{i+1}", "kind": "organization",
                            "label": claim(s, "Comune" if "Comune" in s["text"] else "Regione")} for i, s in enumerate(sources)], "edges": []}
    else:
        count = 7 if "ESATTAMENTE sette" in prompt["question"] else len(sources)
        value = {"sufficient": True, "claims": [claim(sources[i % len(sources)]) for i in range(count)]}
    return SimpleNamespace(text=json.dumps(value), candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])


def test_old_and_new_enter_all_seven_products_only_after_incremental_index(corpus):
    root, collection, embedder = corpus
    inspect_corpus(root, refresh=True)
    assert {c.metadata["filename"] for c in read_catalog(root).chunks} == {"old.pdf"}
    chunks, _ = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    embedder.reset_mock()
    assert apply_plan(plan_index(chunks, collection), collection, embedder, 1, prune_stale=False) == 1
    embedder.embed.assert_called_once()  # Nessun reinvio dell'edizione precedente.
    catalog = read_catalog(root)
    assert {c.metadata["filename"] for c in catalog.chunks} == {"old.pdf", "new.pdf"}
    assert len(filter_catalog(catalog, ReviewSelection("trasporti", ("new.pdf",))).chunks) == 1
    assert sum(map(len, review_groups(catalog))) == 2
    def search(topic, **kwargs):
        return semantic_search(topic, embedder=embedder, **kwargs)
    client = Mock()
    client.models.generate_content.side_effect = simulated_text_response
    with patch("edicola.editorial.semantic_search", side_effect=search), patch(
        "edicola.knowledge.semantic_search", side_effect=search), patch("edicola.rag.semantic_search", side_effect=search):
        for kind in ("briefing", "dossier"):
            result = generate_product(kind, "trasporti", root=root, authorize_external=True, client=client)
            assert result.sufficient
            assert {s.filename for s in result.sources if s.id in result.used_source_ids} == {"old.pdf", "new.pdf"}
        for kind in ("timeline", "map"):
            result = generate_knowledge(kind, "trasporti", root=root, authorize_external=True, client=client)
            assert result.data["events" if kind == "timeline" else "nodes"]
            assert {s.filename for s in result.sources} == {"old.pdf", "new.pdf"}
        result = ask_question("trasporti", root=root, authorize_external=True, client=client)
        assert result.sufficient and len(result.used_source_ids) == 2
    infographic = build_infographic(catalog, "trasporti")
    assert {block["filename"] for block in infographic.blocks} == {"old.pdf", "new.pdf"}
    briefing = next(p for p in list_products(root) if p.result.kind == "briefing")
    podcast = generate_podcast(briefing.key, root=root, authorize_external=True, client=fake_client())
    assert {s["filename"] for s in podcast.script.sources} == {"old.pdf", "new.pdf"}


def test_cache_classifies_without_deleting_previous_products(corpus):
    root, _, _ = corpus
    inspect_corpus(root, refresh=True)
    chunks, _ = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    chunk = next(c for c in chunks if c.metadata["filename"] == "old.pdf")
    source = {"chunk_id": chunk.id, "filename": "old.pdf", "page": 1, "text": chunk.text}
    coverage = {"indexed": 1, "total": 2, "files": []}
    valid = {"sources": [source], "coverage": {**coverage, "total": 1}}
    assert product_status(valid, {c.id: c for c in chunks}, coverage) == "historical_coverage"
    assert product_status(valid, {}, coverage) == "obsolete_sources"
    directory = root / "data/knowledge_cache"
    directory.mkdir()
    path = directory / "old.json"
    path.write_text(json.dumps(valid), encoding="utf-8")
    before = path.read_bytes()
    assert audit_caches(root, chunks, coverage)["knowledge"] == {"historical_coverage": 1}
    assert path.read_bytes() == before


def test_snapshot_requires_explicit_distribution_and_includes_only_named_pdf(corpus):
    root, _, _ = corpus
    inspect_corpus(root, refresh=True)
    with pytest.raises(ValueError):
        export_seed(root, root / "not-authorized", ["new.pdf"])
    exported = root / "authorized-test-seed"
    export_seed(root, exported, ["old.pdf"], authorize_distribution=True)
    assert validate_seed(exported)["pdfs"] == 1
    assert not (exported / "data/incoming/new.pdf").exists()
    assert not (exported / "data/corpus_updates").exists()
    cloud_main(["--validate", str(exported)])
    assert not (root / "deployment/seed").exists()


def test_adding_indexed_sources_bypasses_old_cache_without_deleting_it(corpus):
    root, collection, embedder = corpus
    inspect_corpus(root, refresh=True)
    client = Mock()
    client.models.generate_content.side_effect = simulated_text_response
    first = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert first.sufficient and {s.filename for s in first.sources} == {"old.pdf"}
    chunks, _ = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    apply_plan(plan_index(chunks, collection), collection, embedder, 1, prune_stale=False)
    second = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert second.sufficient and not second.from_cache and len(second.sources) == 2
    assert generate_product("briefing", root=root, authorize_external=True, client=client).from_cache
    assert client.models.generate_content.call_count == 2
    with sqlite3.connect(root / "data/editorial.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
