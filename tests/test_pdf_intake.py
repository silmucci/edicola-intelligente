"""Import automatico locale: nessun Gemini, niente overwrite e riuso cache."""
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from edicola.chunking import prepare_documents
from edicola.ingestion import ingest_directory
from edicola.pdf_intake import process_inbox
from test_ingestion import make_pdf


@pytest.fixture
def inbox(tmp_path):
    (tmp_path / "data/inbox").mkdir(parents=True)
    (tmp_path / "data/incoming").mkdir()
    return tmp_path


def test_new_pdf_imported_and_extracted_only_once(inbox):
    content = make_pdf(("La prima notizia e la sua pagina",))
    source = inbox / "data/inbox/ottobre.pdf"
    source.write_bytes(content)
    with patch("edicola.pdf_intake.extract_pdf") as extractor:
        from edicola.ingestion import extract_pdf
        extractor.side_effect = extract_pdf
        result = process_inbox(inbox)
    assert result["added"] == ["ottobre.pdf"]
    assert result["api_calls"] == 0 and result["pending"] == 0
    assert not source.exists()
    assert extractor.call_count == 1
    target = inbox / "data/incoming/ottobre.pdf"
    assert target.read_bytes() == content
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("estrazione duplicata")):
        documents = ingest_directory(inbox / "data/incoming", inbox / "data/archive.sqlite3")
        chunks = prepare_documents(documents, inbox / "data/archive.sqlite3")
    assert documents[0].status == "ok" and chunks[0].chunks
    before = [chunk.id for chunk in chunks[0].chunks]
    assert process_inbox(inbox)["added"] == []
    assert [chunk.id for chunk in prepare_documents(
        ingest_directory(inbox / "data/incoming", inbox / "data/archive.sqlite3"),
        inbox / "data/archive.sqlite3")[0].chunks] == before


def test_duplicate_content_is_not_duplicated_or_reprocessed(inbox):
    original = make_pdf(("Uno stesso quotidiano",))
    (inbox / "data/incoming/prima.pdf").write_bytes(original)
    (inbox / "data/inbox/copia.pdf").write_bytes(original)
    with patch("edicola.pdf_intake.extract_pdf", side_effect=AssertionError("non serve estrarre")):
        report = process_inbox(inbox)
    assert report["added"] == []
    assert report["duplicates"] == [{"pdf": "copia.pdf", "existing": "prima.pdf"}]
    assert sorted(p.name for p in (inbox / "data/incoming").glob("*.pdf")) == ["prima.pdf"]
    assert not (inbox / "data/inbox/copia.pdf").exists()


def test_existing_name_preserved_as_older_edition(inbox):
    old = make_pdf(("Versione della prima edizione",))
    updated = make_pdf(("Nuova edizione della settimana",))
    (inbox / "data/incoming/edizione.pdf").write_bytes(old)
    (inbox / "data/inbox/edizione.pdf").write_bytes(updated)
    report = process_inbox(inbox)
    expected = f"edizione--{hashlib.sha256(updated).hexdigest()[:12]}.pdf"
    assert report["added"] == [expected]
    assert report["renamed"] == {"edizione.pdf": expected}
    assert (inbox / "data/incoming/edizione.pdf").read_bytes() == old
    assert (inbox / "data/incoming" / expected).read_bytes() == updated
    docs = ingest_directory(inbox / "data/incoming", inbox / "data/archive.sqlite3")
    chunks = prepare_documents(docs, inbox / "data/archive.sqlite3")
    assert len(docs) == len(chunks) == 2
    assert docs[0].sha256 != docs[1].sha256
    assert all(c.chunks for c in chunks)


def test_invalid_unreadable_and_symlink_are_not_published(inbox):
    (inbox / "data/inbox/false.pdf").write_bytes(b"not a PDF")
    (inbox / "data/inbox/broken.pdf").write_bytes(b"%PDF-1.7\nbroken")
    (inbox / "data/inbox/note.txt").write_text("do not import")
    outside = inbox / "outside.pdf"
    outside.write_bytes(make_pdf())
    link = inbox / "data/inbox/outside.pdf"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pass
    result = process_inbox(inbox)
    assert len(result["rejected"]) >= 2
    assert result["added"] == []
    assert not list((inbox / "data/incoming").glob("*.pdf"))
    assert (inbox / "data/inbox/false.pdf").exists()
    assert outside.exists()


def test_batch_limit_does_not_lose_remaining_pdf(inbox):
    (inbox / "data/inbox/a.pdf").write_bytes(make_pdf(("Prima",)))
    (inbox / "data/inbox/b.pdf").write_bytes(make_pdf(("Seconda",)))
    first = process_inbox(inbox, max_files=1)
    assert first["added"] == ["a.pdf"] and first["pending"] == 1
    second = process_inbox(inbox, max_files=1)
    assert second["added"] == ["b.pdf"] and second["pending"] == 0


def test_refuses_untrusted_inbox_and_oversize(inbox, monkeypatch):
    from edicola import pdf_intake
    (inbox / "data/inbox/large.pdf").write_bytes(make_pdf())
    monkeypatch.setattr(pdf_intake, "MAX_PDF_BYTES", 10)
    result = process_inbox(inbox)
    assert result["rejected"][0]["reason"] == "dimensione non consentita"
    assert not list((inbox / "data/incoming").glob("*.pdf"))
    with pytest.raises(ValueError):
        process_inbox(inbox, max_files=0)


def test_no_inbox_no_mutations(tmp_path):
    assert process_inbox(tmp_path)["added"] == []
    assert not (tmp_path / "data").exists()
