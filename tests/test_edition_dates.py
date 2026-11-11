"""Date dal nome dei PDF: archivi già importati, futuri PDF e metadati curati."""
import json

from edicola.edition_dates import read_edition_metadata
from pathlib import Path
from unittest.mock import patch

import pytest

from edicola.chunking import prepare_documents
from edicola.edition_dates import date_from_filename, sync_filename_dates
from edicola.ingestion import ingest_directory
from edicola.vectorstore import open_collection
from test_ingestion import make_pdf

FIRST = "A4_edizione_del_1-11-2026_1027.pdf"
SECOND = "A4_edizione_del_10-11-2026_1036.pdf"
EXISTING = "quotidiano.pdf"


@pytest.mark.parametrize(("name", "expected"), [
    (FIRST, "2026-11-01"),
    (SECOND, "2026-11-10"),
    ("A4_edizione_del_31-10-2026_1026.pdf", "2026-10-31"),
    ("a4_EDIZIONE_DEL_5-11-2026.pdf", "2026-11-05"),
    ("A4_edizione_del_29-2-2024_1.pdf", "2024-02-29"),
    ("A4_edizione_del_29-2-2026_1.pdf", None),
    ("A4_edizione_del_31-11-2026_1.pdf", None),
    ("A4_edizione_del_20-13-2026_1.pdf", None),
    ("A4_edizione_del_1-11-2026_1027.txt", None),
    ("A4_edizione_del_1-11-2026extra.pdf", None),
    ("nota.pdf", None),
    ("../A4_edizione_del_1-11-2026.pdf", None),
])
def test_date_from_filename(name, expected):
    assert date_from_filename(name) == expected


def _build(tmp_path, names):
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    for name in names:
        (incoming / name).write_bytes(make_pdf(("Testo di prova per questa edizione.",)))
    registry = tmp_path / "data/archive.sqlite3"
    documents = ingest_directory(incoming, registry)
    prepare_documents(documents, registry)
    return documents


def test_sync_existing_files_preserves_curated_dates_and_vectors(tmp_path):
    documents = _build(tmp_path, [FIRST, SECOND, EXISTING])
    catalog_path = tmp_path / "data/editions.json"
    catalog_path.write_text(json.dumps({
        EXISTING: {"publication": "Testata confermata", "date": "2026-10-21"},
        FIRST: {"publication": "Testata già curata", "date": "2026-10-30"},
    }))
    collection = open_collection(tmp_path / "data/chroma", create=True)
    count_before = collection.count()
    with patch("google.genai.Client", side_effect=AssertionError("Nessuna chiamata Gemini")):
        changed = sync_filename_dates(tmp_path, documents)
    assert changed == [SECOND]
    metadata = json.loads(catalog_path.read_text())
    assert metadata[EXISTING] == {"publication": "Testata confermata", "date": "2026-10-21"}
    assert metadata[FIRST] == {"publication": "Testata già curata", "date": "2026-10-30"}
    assert metadata[SECOND]["date"] == "2026-11-10"
    assert metadata[SECOND]["date_source"] == "filename"
    backups = list((tmp_path / "data/corpus_updates").glob("editions-before-filename-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == {
        EXISTING: {"publication": "Testata confermata", "date": "2026-10-21"},
        FIRST: {"publication": "Testata già curata", "date": "2026-10-30"},
    }
    assert collection.count() == count_before
    assert sync_filename_dates(tmp_path, documents) == []
    assert len(list((tmp_path / "data/corpus_updates").glob("editions-before-filename-*.json"))) == 1


def test_sync_both_preexisting_and_future_pdfs_without_reimport(tmp_path):
    documents = _build(tmp_path, [FIRST])
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("PDF già estratto")):
        reloaded = ingest_directory(tmp_path / "data/incoming", tmp_path / "data/archive.sqlite3")
    assert sync_filename_dates(tmp_path, reloaded) == [FIRST]
    assert json.loads((tmp_path / "data/editions.json").read_text())[FIRST]["date"] == "2026-11-01"

    # Il PDF aggiunto in futuro eredita la stessa regola al prossimo reload.
    (tmp_path / "data/incoming" / SECOND).write_bytes(make_pdf(("Un altro articolo.",)))
    later = ingest_directory(tmp_path / "data/incoming", tmp_path / "data/archive.sqlite3")
    assert sync_filename_dates(tmp_path, later) == [SECOND]
    dates = json.loads((tmp_path / "data/editions.json").read_text())
    assert {key: item["date"] for key, item in dates.items()} == {
        FIRST: "2026-11-01", SECOND: "2026-11-10"
    }


def test_unknown_filename_skipped_without_modifying_catalog(tmp_path):
    documents = _build(tmp_path, [EXISTING])
    assert sync_filename_dates(tmp_path, documents) == []
    assert not (tmp_path / "data/editions.json").exists()


def test_invalid_catalog_or_symlink_rejected_without_overwrite(tmp_path):
    documents = _build(tmp_path, [FIRST])
    catalog = tmp_path / "data/editions.json"
    catalog.write_text("non-json", encoding="utf-8")
    with pytest.raises(ValueError):
        sync_filename_dates(tmp_path, documents)
    assert catalog.read_text() == "non-json"
    catalog.unlink()
    external = tmp_path / "elsewhere.json"
    external.write_text("{}")
    try:
        catalog.symlink_to(external)
    except OSError:
        pytest.skip("Symlink non supportato")
    with pytest.raises(ValueError, match="non consentiti"):
        sync_filename_dates(tmp_path, documents)
    assert external.read_text() == "{}"


def test_edition_metadata_loader_uses_current_file_without_stale_cache(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    target = folder / "editions.json"
    assert read_edition_metadata(tmp_path) == {}
    target.write_text("not-json", encoding="utf-8")
    assert read_edition_metadata(tmp_path) == {}
    target.write_text("[]", encoding="utf-8")
    assert read_edition_metadata(tmp_path) == {}
    target.write_text('{"a.pdf": {"date": "2026-11-01"}}', encoding="utf-8")
    assert read_edition_metadata(tmp_path)["a.pdf"]["date"] == "2026-11-01"
    target.write_text('{"a.pdf": {"date": "2026-11-02"}}', encoding="utf-8")
    assert read_edition_metadata(tmp_path)["a.pdf"]["date"] == "2026-11-02"
