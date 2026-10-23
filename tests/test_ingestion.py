"""PDF sintetici: nessun accesso ai quotidiani presenti nel progetto."""

from io import BytesIO
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from edicola.ingestion import extract_pdf, ingest_directory


def make_pdf(texts=("Prima pagina", "Seconda pagina"), password=None):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=600, height=800)
        if text:
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
            })
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def archive(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    return incoming, tmp_path / "archive.sqlite3"


def test_acquires_text_and_page_metadata(archive):
    incoming, registry = archive
    (incoming / "giornale.PDF").write_bytes(make_pdf())
    (incoming / "ignore.txt").write_text("non PDF")
    (incoming / "directory.pdf").mkdir()
    documents = ingest_directory(incoming, registry)
    assert len(documents) == 1
    doc = documents[0]
    assert doc.filename == "giornale.PDF"
    assert doc.status == "ok"
    assert doc.total_pages == 2
    assert len(doc.sha256) == 64
    assert [page.number for page in doc.pages] == [1, 2]
    assert [page.text.strip() for page in doc.pages] == ["Prima pagina", "Seconda pagina"]
    assert all(page.filename == doc.filename and page.total_pages == 2 for page in doc.pages)
    with sqlite3.connect(registry) as connection:
        assert connection.execute("SELECT filename, sha256 FROM sources").fetchall() == [
            (doc.filename, doc.sha256)
        ]


def test_cache_survives_new_scan_and_skips_extraction(archive):
    incoming, registry = archive
    (incoming / "a.pdf").write_bytes(make_pdf())
    first = ingest_directory(incoming, registry)
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("estrazione ripetuta")):
        assert ingest_directory(incoming, registry) == first


def test_duplicates_and_rename_share_extraction(archive):
    incoming, registry = archive
    content = make_pdf()
    (incoming / "a.pdf").write_bytes(content)
    (incoming / "b.pdf").write_bytes(content)
    with patch("edicola.ingestion.extract_pdf", wraps=extract_pdf) as extract:
        documents = ingest_directory(incoming, registry)
        assert extract.call_count == 1
    assert len(documents) == 2
    assert documents[0].sha256 == documents[1].sha256
    assert documents[1].pages[0].filename == "b.pdf"
    (incoming / "a.pdf").rename(incoming / "renamed.pdf")
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("estrazione ripetuta")):
        assert [doc.filename for doc in ingest_directory(incoming, registry)] == ["b.pdf", "renamed.pdf"]


def test_changed_file_and_new_file_are_extracted(archive):
    incoming, registry = archive
    path = incoming / "a.pdf"
    path.write_bytes(make_pdf(("Prima",)))
    original = ingest_directory(incoming, registry)[0]
    path.write_bytes(make_pdf(("Nuova",)))
    (incoming / "b.pdf").write_bytes(make_pdf(("Altra",)))
    with patch("edicola.ingestion.extract_pdf", wraps=extract_pdf) as extract:
        documents = ingest_directory(incoming, registry)
        assert extract.call_count == 2
    assert documents[0].sha256 != original.sha256
    assert documents[0].pages[0].text.strip() == "Nuova"


@pytest.mark.parametrize("content,status,pages", [
    (b"", "empty", 0),
    (b"%PDF-1.7\ninvalid", "error", 0),
    (make_pdf(()), "empty", 0),
    (make_pdf((None,)), "no_text", 1),
    (make_pdf(password="secret"), "error", 0),
])
def test_unreadable_empty_and_no_text_are_cached(archive, content, status, pages):
    incoming, registry = archive
    (incoming / "problem.pdf").write_bytes(content)
    (incoming / "valid.pdf").write_bytes(make_pdf())
    documents = ingest_directory(incoming, registry)
    assert documents[0].status == status
    assert documents[0].total_pages == pages
    assert documents[0].message
    assert documents[1].status == "ok"
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("estrazione ripetuta")):
        assert ingest_directory(incoming, registry) == documents


def test_filesystem_read_failure_does_not_stop_other_files(archive):
    incoming, registry = archive
    blocked = incoming / "blocked.pdf"
    blocked.write_bytes(make_pdf())
    (incoming / "valid.pdf").write_bytes(make_pdf())
    original = Path.read_bytes

    def read(path):
        if path == blocked:
            raise PermissionError("accesso negato")
        return original(path)

    with patch.object(Path, "read_bytes", read):
        documents = ingest_directory(incoming, registry)
    assert documents[0].status == "error"
    assert documents[0].sha256 is None
    assert documents[1].status == "ok"


def test_single_page_error_preserves_other_pages():
    class FakePage:
        def __init__(self, broken):
            self.broken = broken

        def extract_text(self):
            if self.broken:
                raise ValueError("contenuto danneggiato")
            return "Testo leggibile"

    with patch("edicola.ingestion.PdfReader") as reader:
        reader.return_value.is_encrypted = False
        reader.return_value.pages = [FakePage(False), FakePage(True)]
        result = extract_pdf(b"synthetic")
    assert result["status"] == "partial"
    assert result["total_pages"] == 2
    assert result["pages"][0]["text"] == "Testo leggibile"
    assert result["pages"][1]["error"]


def test_missing_directory_and_removed_files(archive):
    incoming, registry = archive
    assert ingest_directory(incoming / "new", registry) == []
    path = incoming / "a.pdf"
    path.write_bytes(make_pdf())
    ingest_directory(incoming, registry)
    path.unlink()
    assert ingest_directory(incoming, registry) == []
