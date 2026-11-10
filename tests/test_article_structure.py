"""Test offline di riconoscimento articoli e diagnosi in sola lettura."""
import fitz
import pytest

from edicola.article_structure import infer_article_annotations
from edicola.article_vision import chunk_annotation
from edicola.ingestion import extract_pdf
from edicola.pdf_diagnostics import inspect_pdf, locate_pdf


def newspaper_pdf(*, two_titles=False):
    doc = fitz.open()
    cover = doc.new_page(width=600, height=800)
    cover.insert_text((45, 80), "Prima pagina con molti richiami", fontsize=22)
    for number in range(2, 5):
        page = doc.new_page(width=600, height=800)
        page.insert_text((485, 35), "Edizione giornale", fontsize=9)
        if number == 2:
            page.insert_text((45, 95), "Notizia principale del territorio", fontsize=30)
            if two_titles:
                page.insert_text((45, 145), "Un'altra notizia completamente diversa", fontsize=30)
        elif number == 4:
            page.insert_text((45, 95), "Un altro articolo indipendente", fontsize=30)
        for line in range(12):
            sentence = ("continua il racconto con fatti concreti e dettagli utili "
                        if number == 3 else
                        "Il contenuto del quotidiano descrive un fatto accertato ")
            page.insert_text((45, 200 + line * 24) if number != 3 else (45, 80 + line * 24),
                             sentence, fontsize=10)
            page.insert_text((325, 200 + line * 24) if number != 3 else (325, 80 + line * 24),
                             "ulteriori spiegazioni riportate nella seconda colonna", fontsize=10)
    content = doc.tobytes()
    doc.close()
    return content


def test_layout_groups_single_article_and_continuation_without_vision():
    result = extract_pdf(newspaper_pdf())
    assert result["status"] == "ok"
    labels = infer_article_annotations(result, "f" * 64)
    assert 1 not in labels
    assert sorted(labels) == [2, 3, 4]
    assert labels[2][0]["article_pages"] == [2, 3]
    assert labels[3][0]["role"] == "continuation"
    assert labels[4][0]["article_pages"] == [4]
    assert labels[4][0]["article_id"] != labels[2][0]["article_id"]
    first = chunk_annotation("f" * 64, 2, 0, 30, labels)
    second = chunk_annotation("f" * 64, 3, 0, 30, labels)
    assert first["article_id"] == second["article_id"]
    assert first["article_pages_json"] == "[2, 3]"
    assert second["article_role"] == "continuation"
    assert first["article_title_verified"] is True


def test_fallback_and_ambiguous_headings_do_not_invent_article_structure():
    ambiguous = extract_pdf(newspaper_pdf(two_titles=True))
    inferred = infer_article_annotations(ambiguous, "f" * 64)
    assert 2 not in inferred and 3 not in inferred
    assert 4 in inferred
    for page in ambiguous["pages"]:
        page["extraction_method"] = "pypdf-fallback"
    assert infer_article_annotations(ambiguous, "f" * 64) == {}


def test_pdf_diagnostics_from_snapshot_does_not_write_any_data(tmp_path):
    incoming = tmp_path / "deployment/seed/data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "esempio.pdf").write_bytes(newspaper_pdf())
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    report = inspect_pdf(tmp_path, "esempio.pdf")
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert before == after
    assert report["total_pages"] == 4
    assert report["articles_recognized"] == 2
    assert report["continuation_pages"] == 1
    assert report["unclassified_pages"] == [1]
    assert "pymupdf-layout" in report["extraction_methods"][0]
    with pytest.raises(ValueError):
        locate_pdf(tmp_path, "../esempio.pdf")
