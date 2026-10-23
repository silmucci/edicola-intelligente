"""Pulizia, confini, metadati e riuso persistente dei chunk."""

import sqlite3
from unittest.mock import patch

import pytest

from edicola.chunking import ChunkConfig, build_chunks, clean_text, prepare_documents, split_text
from edicola.ingestion import ingest_directory
from edicola.models import Document, Page
from test_ingestion import make_pdf


def document(digest="a" * 64, filename="giornale.pdf"):
    return Document(filename, digest, 3, "ok", pages=[
        Page(filename, 1, 3, "Una frase leggibile. " * 120),
        Page(filename, 2, 3, "\n\t\u200b"),
        Page(filename, 3, 3, "Ultima pagina."),
    ])


def test_clean_text_normalizes_unicode_whitespace_and_controls():
    raw = "  Caffè\r\n\tﬁore\u00a0e\u200buro\x00\ufeff  quo\u00adtidiano! \x0c"
    assert clean_text(raw) == "Caffè fiore euro quotidiano!"
    assert clean_text(clean_text(raw)) == clean_text(raw)
    assert clean_text(" politico-\n economico, 2026. ") == "politico- economico, 2026."
    assert clean_text("\x00\u200b\r\n") == ""


def test_default_size_overlap_and_full_coverage():
    text = clean_text("La cronaca del quotidiano descrive i fatti della giornata. " * 100)
    chunks = split_text(text, ChunkConfig())
    assert len(chunks) > 1
    assert chunks[0][0] == 0
    assert chunks[-1][1] == len(text)
    assert all(content == text[start:end] and 0 < len(content) <= 1000
               for start, end, content in chunks)
    assert all(len(item[2]) >= 750 for item in chunks[:-1])
    reconstructed = chunks[0][2]
    for previous, current in zip(chunks, chunks[1:]):
        assert current[0] == previous[1] - 150
        assert previous[2][-150:] == current[2][:150]
        reconstructed += current[2][150:]
    assert reconstructed == text


def test_sentence_boundary_is_preferred_to_word_boundary():
    text = "a" * 79 + ". " + "b" * 70
    chunks = split_text(text, ChunkConfig(size=100, overlap=15))
    assert chunks[0][1] == 80
    assert chunks[0][2].endswith(".")


@pytest.mark.parametrize("size,overlap", [(30, 0), (30, 29), (1, 0)])
def test_unbroken_text_and_extreme_valid_configs_terminate(size, overlap):
    text = "x" * 123
    chunks = split_text(text, ChunkConfig(size=size, overlap=overlap))
    assert chunks[-1][1] == len(text)
    assert all(0 < end - start <= size for start, end, _ in chunks)
    assert len({start for start, _, _ in chunks}) == len(chunks)


@pytest.mark.parametrize("size,overlap", [(0, 0), (-1, 0), (100, -1), (100, 100), (5.5, 1)])
def test_invalid_configs_are_rejected(size, overlap):
    with pytest.raises(ValueError):
        ChunkConfig(size=size, overlap=overlap)


def test_empty_and_short_text():
    assert split_text("", ChunkConfig()) == []
    assert split_text("Ciao.", ChunkConfig()) == [(0, 5, "Ciao.")]


def test_metadata_page_boundaries_ids_and_exclusions(tmp_path):
    doc = document()
    prepared = prepare_documents([doc], tmp_path / "registry.sqlite3")[0]
    assert list(prepared.skipped_pages) == [2]
    assert [item.position for item in prepared.chunks] == list(range(1, len(prepared.chunks) + 1))
    assert {item.page for item in prepared.chunks} == {1, 3}
    assert len({item.id for item in prepared.chunks}) == len(prepared.chunks)
    for chunk in prepared.chunks:
        assert chunk.filename == doc.filename
        assert chunk.pdf_sha256 == doc.sha256
        assert chunk.text == clean_text(doc.pages[chunk.page - 1].text)[chunk.start:chunk.end]
    repeated = prepare_documents([doc], tmp_path / "registry.sqlite3")[0]
    assert repeated == prepared


def test_failed_and_missing_pages_are_excluded():
    doc = Document("broken.pdf", "b" * 64, 3, "partial", pages=[
        Page("broken.pdf", 1, 3, "Testo valido."),
        Page("broken.pdf", 2, 3, "Testo incompleto", error="Errore nella pagina."),
    ])
    result = build_chunks(doc, ChunkConfig())
    assert [item["page"] for item in result["chunks"]] == [1]
    assert result["skipped_pages"] == {
        2: "Errore nella pagina.", 3: "Testo della pagina non disponibile."
    }


def test_persistent_cache_deduplicates_copies_and_renames(tmp_path):
    registry = tmp_path / "registry.sqlite3"
    first = document()
    copy = document(filename="copia.pdf")
    with patch("edicola.chunking.build_chunks", wraps=build_chunks) as build:
        results = prepare_documents([first, copy], registry)
        assert build.call_count == 1
    assert results[0].chunks[0].id == results[1].chunks[0].id
    assert results[1].chunks[0].filename == "copia.pdf"
    with sqlite3.connect(registry) as connection:
        count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        assert count == len(results[0].chunks)
    with patch("edicola.chunking.build_chunks", side_effect=AssertionError("chunking ripetuto")):
        renamed = prepare_documents([document(filename="rinominato.pdf")], registry)[0]
        assert renamed.chunks[0].id == results[0].chunks[0].id
        assert renamed.chunks[0].filename == "rinominato.pdf"


def test_changed_configuration_replaces_only_requested_document(tmp_path):
    registry = tmp_path / "registry.sqlite3"
    first, second = document(), document("b" * 64, "altro.pdf")
    initial = prepare_documents([first, second], registry)
    config = ChunkConfig(size=600, overlap=100)
    with patch("edicola.chunking.build_chunks", wraps=build_chunks) as build:
        changed = prepare_documents([first], registry, config)[0]
        assert build.call_count == 1
    assert changed.chunks[0].id != initial[0].chunks[0].id
    with sqlite3.connect(registry) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE pdf_sha256 = ?", (first.sha256,)
        ).fetchone()[0] == len(changed.chunks)
        stored_ids = {row[0] for row in connection.execute("SELECT id FROM chunks")}
        assert not stored_ids.intersection(item.id for item in initial[0].chunks)
    with patch("edicola.chunking.build_chunks", side_effect=AssertionError("chunking ripetuto")):
        assert prepare_documents([second], registry)[0] == initial[1]
        assert prepare_documents([first], registry, config)[0] == changed


def test_pipeline_version_change_invalidates_cache(tmp_path):
    registry = tmp_path / "registry.sqlite3"
    doc = document()
    first = prepare_documents([doc], registry)[0]
    with patch("edicola.chunking.PIPELINE_VERSION", 2):
        changed = prepare_documents([doc], registry)[0]
    assert changed.chunks[0].id != first.chunks[0].id


def test_changed_pdf_only_processes_new_content_and_reuses_extraction(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    registry = tmp_path / "registry.sqlite3"
    (incoming / "a.pdf").write_bytes(make_pdf(("Primo testo.",)))
    (incoming / "b.pdf").write_bytes(make_pdf(("Secondo testo.",)))
    docs = ingest_directory(incoming, registry)
    initial = prepare_documents(docs, registry)
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("estrazione ripetuta")):
        with patch("edicola.chunking.build_chunks", side_effect=AssertionError("chunking ripetuto")):
            assert prepare_documents(ingest_directory(incoming, registry), registry) == initial
    (incoming / "a.pdf").write_bytes(make_pdf(("Testo aggiornato.",)))
    with patch("edicola.chunking.build_chunks", wraps=build_chunks) as build:
        updated = prepare_documents(ingest_directory(incoming, registry), registry)
        assert build.call_count == 1
    assert updated[0].chunks[0].id != initial[0].chunks[0].id
    assert updated[1] == initial[1]


def test_zero_chunk_results_are_cached(tmp_path):
    doc = Document("scansione.pdf", "c" * 64, 1, "no_text", pages=[Page("scansione.pdf", 1, 1, "")])
    registry = tmp_path / "registry.sqlite3"
    initial = prepare_documents([doc], registry)
    assert initial[0].chunks == []
    assert 1 in initial[0].skipped_pages
    with patch("edicola.chunking.build_chunks", side_effect=AssertionError("chunking ripetuto")):
        assert prepare_documents([doc], registry) == initial
