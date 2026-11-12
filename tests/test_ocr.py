"""OCR facoltativo: test isolati senza API e senza binario Tesseract reale."""
from types import SimpleNamespace
from unittest.mock import patch

import fitz

from edicola.ingestion import extract_pdf, ingest_directory
from edicola.chunking import prepare_documents
from edicola.ocr import OCR_METHOD, needs_ocr, recognize_page
from edicola.ocr_backfill import refresh


def image_pdf():
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 120), False)
    image.clear_with(255)
    page.insert_image(page.rect, pixmap=image)
    content = document.tobytes()
    document.close()
    return content


def sample_text():
    return "Questa pagina racconta le notizie del quotidiano con dettagli e fonti verificabili. " * 5


def test_scanned_page_uses_ocr_only_when_text_is_useful():
    with patch("edicola.ocr.shutil.which", return_value="/usr/bin/tesseract"), patch(
        "edicola.ocr.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout=sample_text().encode())
    ) as call:
        assert recognize_page(image_pdf(), 1, "") == sample_text().strip()
    assert call.call_count == 1
    assert call.call_args.kwargs["timeout"] <= 40


def test_digital_pages_are_not_sent_to_tesseract():
    with patch("edicola.ocr.subprocess.run", side_effect=AssertionError("not required")):
        assert recognize_page(b"irrelevant", 1, "Una descrizione estesa " * 25) is None
    assert not needs_ocr("Testo " * 100)


def test_blank_or_vector_only_pages_skip_ocr():
    doc = fitz.open()
    doc.new_page()
    content = doc.tobytes()
    doc.close()
    with patch("edicola.ocr.shutil.which", return_value="/usr/bin/tesseract"), patch(
        "edicola.ocr.subprocess.run", side_effect=AssertionError("not required")
    ):
        assert recognize_page(content, 1) is None


def test_unreliable_result_does_not_replace_original_text():
    with patch("edicola.ocr.shutil.which", return_value="/usr/bin/tesseract"), patch(
        "edicola.ocr.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout=b"A B C")
    ):
        assert recognize_page(image_pdf(), 1, "Titolo esistente") is None


def test_missing_binary_and_timeout_preserve_pdf():
    with patch("edicola.ocr.shutil.which", return_value=None):
        assert recognize_page(image_pdf(), 1) is None
    import subprocess
    with patch("edicola.ocr.shutil.which", return_value="/usr/bin/tesseract"), patch(
        "edicola.ocr.subprocess.run", side_effect=subprocess.TimeoutExpired("tesseract", 1)
    ):
        assert recognize_page(image_pdf(), 1) is None


def test_ingestion_uses_ocr_without_mixing_original_blocks():
    with patch("edicola.ingestion.recognize_page", return_value=sample_text()):
        result = extract_pdf(image_pdf())
    assert result["status"] == "ok"
    assert result["pages"][0]["extraction_method"] == OCR_METHOD
    assert result["pages"][0]["text"] == sample_text()
    assert "blocks" not in result["pages"][0]


def test_backfill_regenerates_sqlite_chunks_without_gemini(tmp_path):
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "giornale.pdf").write_bytes(image_pdf())
    registry = tmp_path / "data/archive.sqlite3"
    with patch("edicola.ingestion.recognize_page", return_value=None):
        before = ingest_directory(incoming, registry)
    assert before[0].status == "no_text"
    prepare_documents(before, registry)

    dry = refresh(tmp_path, limit=2)
    assert dry["candidate_pages"] == 1
    assert dry["attempted_pages"] == 0
    with patch("edicola.ocr_backfill.tesseract_available", return_value=True), patch(
        "edicola.ocr_backfill.recognize_page", return_value=sample_text()
    ) as run:
        report = refresh(tmp_path, apply=True, limit=1)
    assert run.call_count == 1
    assert report["recovered_pages"] == 1
    assert report["updated_documents"] == 1
    assert report["indexing_required"] is True
    after = ingest_directory(incoming, registry)
    assert after[0].status == "ok"
    assert prepare_documents(after, registry)[0].chunks
    assert refresh(tmp_path, limit=1)["candidate_pages"] == 0
