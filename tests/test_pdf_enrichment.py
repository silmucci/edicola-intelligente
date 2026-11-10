"""Test offline: PDF sintetici, nessuna immagine inviata alle API."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import fitz
import pytest

from edicola.article_vision import (cached_page, chunk_annotation, page_candidates,
                                    read_annotations, save_page, validate_vision_response)
from edicola.ingestion import extract_pdf
from edicola.pdf_enrichment import execute


def make_layout_pdf():
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((35, 35), "Titolo generale del quotidiano", fontsize=18)
    page.insert_text((35, 85), "Colonna sinistra prima parte.", fontsize=10)
    page.insert_text((35, 115), "Colonna sinistra seconda parte.", fontsize=10)
    page.insert_text((330, 85), "Colonna destra prima parte.", fontsize=10)
    page.insert_text((330, 115), "Colonna destra seconda parte.", fontsize=10)
    content = document.tobytes()
    document.close()
    return content


def test_columns_are_read_sequentially_and_blocks_keep_coordinates():
    result = extract_pdf(make_layout_pdf())
    assert result["status"] == "ok"
    page = result["pages"][0]
    assert page["extraction_method"] == "pymupdf-layout-v1"
    assert page["text"].index("Colonna sinistra seconda") < page["text"].index("Colonna destra prima")
    assert "Titolo generale" in page["text"]
    assert len(page["blocks"]) == 5
    assert all(len(block["bbox"]) == 4 for block in page["blocks"])
    assert all(block["font_size"] > 0 for block in page["blocks"])


def test_page_candidates_priority_and_invalid_refs():
    pages = [
        "Prima pagina. Vai a pag. 3 e pagina 99; poi p.2.",
        "Sport\nRisultati disponibili",
        "Economia\nLe notizie"
    ]
    assert page_candidates(pages, 3) == [1, 3, 2]
    assert page_candidates(pages, 1) == [1]
    assert page_candidates([], 4) == []


def test_vision_matches_only_literal_unique_titles_and_real_references():
    text = ("Economia\nNotizia sulle imprese\nLe nuove misure annunciate. "
            "Continua a pagina 2.\nAltra notizia distinta\nDettagli.")
    response = {"articles": [
        {"title": "Notizia sulle imprese", "section": "Economia",
         "importance": "apertura", "continuation_page": 2},
        {"title": "Titolo inventato dal modello", "importance": "spalla"},
        {"title": "Altra notizia distinta", "importance": "breve",
         "continuation_page": 40},
    ]}
    validated = validate_vision_response(response, text, 1, 3)
    assert len(validated["articles"]) == 2
    first, second = validated["articles"]
    assert first["section"] == "Economia"
    assert first["continuation_page"] == 2
    assert first["end"] == second["start"]
    assert second["continuation_page"] is None


@pytest.mark.parametrize("raw", [
    "not JSON", "{}", "[]", '{"articles": "invalid"}',
    '{"articles": [' + '{"title": "X"},' * 41 + '{"title": "X"}]}'
])
def test_vision_rejects_invalid_responses(raw):
    with pytest.raises((ValueError, TypeError)):
        validate_vision_response(raw, "Titolo verificabile", 1, 2)


def test_metadata_is_not_assigned_across_article_boundary(tmp_path):
    text = ("Titolo della prima notizia. " + "Corpo uno. " * 20 +
            "Titolo della seconda notizia. " + "Corpo due. " * 20)
    response = {"articles": [
        {"title": "Titolo della prima notizia."},
        {"title": "Titolo della seconda notizia."},
    ]}
    parsed = validate_vision_response(response, text, 1, 1)
    first, second = parsed["articles"]
    labels = {1: parsed["articles"]}
    assert chunk_annotation("a" * 64, 1, first["start"], first["end"], labels)["article_title_verified"]
    assert chunk_annotation("a" * 64, 1, first["end"] - 10, second["start"] + 10, labels) == {}
    assert chunk_annotation("a" * 64, 1, second["start"], second["end"], labels)["article_title"] == "Titolo della seconda notizia."


def test_continuations_link_only_when_both_pages_have_verified_same_title(tmp_path):
    page1 = "Economia. Titolo notizia verificata. Continua a pagina 2. " + "Testo. " * 30
    page2 = "Titolo notizia verificata. " + "Continuazione. " * 30
    title = "Titolo notizia verificata."
    one = validate_vision_response({"articles": [
        {"title": title, "continuation_page": 2}]}, page1, 1, 2)
    two = validate_vision_response({"articles": [{"title": title}]}, page2, 2, 2)
    path = tmp_path / "vision.sqlite3"
    save_page(path, "f" * 64, 1, "mock-model", page1, one)
    save_page(path, "f" * 64, 2, "mock-model", page2, two)
    labels = read_annotations(path, "f" * 64, {1: page1, 2: page2})
    assert labels[1][0]["linked_page"] == 2
    assert labels[2][0]["linked_page"] == 1
    a = chunk_annotation("f" * 64, 1, one["articles"][0]["start"],
                         one["articles"][0]["end"], labels)
    b = chunk_annotation("f" * 64, 2, two["articles"][0]["start"],
                         two["articles"][0]["end"], labels)
    assert a["article_id"] == b["article_id"]
    assert json.loads(a["article_pages_json"]) == [1, 2]
    assert cached_page(path, "f" * 64, 1, "mock-model", page1)
    assert cached_page(path, "f" * 64, 1, "mock-model", "Testo cambiato") is None
    assert read_annotations(path, "f" * 64, {1: "Testo cambiato", 2: page2}).get(1) is None


def test_vision_does_not_invent_cross_page_article_without_target_verification(tmp_path):
    page1 = "Notizia importante sul giornale. Continua a pagina 2."
    page2 = "Un altro titolo sul giornale. Corpo di altre notizie."
    path = tmp_path / "vision.sqlite3"
    one = validate_vision_response({"articles": [
        {"title": "Notizia importante sul giornale.", "continuation_page": 2}]}, page1, 1, 2)
    two = validate_vision_response({"articles": [
        {"title": "Un altro titolo sul giornale."}]}, page2, 2, 2)
    save_page(path, "b" * 64, 1, "mock", page1, one)
    save_page(path, "b" * 64, 2, "mock", page2, two)
    found = read_annotations(path, "b" * 64, {1: page1, 2: page2})
    assert "linked_page" not in found[1][0]


def test_dry_run_is_read_only_and_never_calls_vision(tmp_path):
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "giornale.pdf").write_bytes(make_layout_pdf())
    with patch("edicola.pdf_enrichment.vision_request", side_effect=AssertionError("API")):
        report = execute(tmp_path, dry_run=True, authorize_external=False,
                         limit=3, maximum=3, model="mock-model")
    assert report["selected_for_run"] == 1
    assert report["completed"] == 0
    assert not (tmp_path / "data/editorial_pages.sqlite3").exists()
    assert not (tmp_path / "data/archive.sqlite3").exists()


def test_without_vision_annotations_returns_empty(tmp_path):
    assert read_annotations(tmp_path / "absent.sqlite3", "f" * 64, {1: "Testo"}) == {}
    assert chunk_annotation("f" * 64, 1, 0, 5, {}) == {}



def test_local_refresh_dry_run_does_not_modify_archive(tmp_path):
    from edicola.ingestion import ingest_directory
    from edicola.chunking import prepare_documents
    from edicola.pdf_refresh import refresh

    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "giornale.pdf").write_bytes(make_layout_pdf())
    registry = tmp_path / "data/archive.sqlite3"
    prepare_documents(ingest_directory(incoming, registry), registry)
    before = registry.read_bytes()
    report = refresh(tmp_path, ["giornale.pdf"], apply=False)
    assert report["dry_run"]
    assert report["backup"] is None
    assert registry.read_bytes() == before


def test_local_refresh_requires_named_valid_pdf(tmp_path):
    from edicola.pdf_refresh import refresh
    with pytest.raises(ValueError):
        refresh(tmp_path, [], apply=True)
