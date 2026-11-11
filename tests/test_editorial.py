"""Prodotti editoriali e cache: catalogo e API simulati, nessuna rete."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
import hashlib
import sqlite3
from dataclasses import asdict

import pytest
from google.genai import errors, types

from edicola.archive import IndexChunk
from edicola.editorial import EditorialConfig, EditorialError, EditorialResult, cache_write, generate_product, render_product
from edicola.editorial_selection import Catalog, balanced_briefing, headline_priority, near_duplicate, topic_clusters
from edicola.briefing import SYSTEM_INSTRUCTION as BRIEFING_INSTRUCTION, briefing_schema, validate_briefing
from edicola.rag import INSUFFICIENT, Source


def make_catalog():
    chunks, vectors, files = [], {}, []
    for edition in range(4):
        filename = f"giornale-{edition}.pdf"
        files.append({"pdf": filename, "publication": f"Testata {edition}", "date": "2026-10-22",
                      "indexed": 3, "total": 6})
        for position in range(3):
            identity = f"chunk-{edition}-{position}"
            chunks.append(IndexChunk(identity,
                f"Edizione {edition}, notizia {position}: il consiglio ha approvato il piano dei trasporti.",
                {"filename": filename, "pdf_sha256": str(edition) * 64,
                 "page": position + 1, "position": position + 1}))
            vectors[identity] = [float(axis == edition) for axis in range(4)]
    return Catalog(chunks, vectors, {"indexed": 12, "total": 24, "files": files,
                                   "partial": True, "warnings": []})


def simulated_response(**kwargs):
    prompt = json.loads(kwargs["contents"])
    sources = {item["source_id"]: item for item in prompt["sources"]}
    if prompt.get("task") == "briefing":
        editions = {}
        for source in prompt["sources"]:
            editions.setdefault(source["pdf"], source)
        news = []
        for index, source in enumerate(editions.values()):
            def claim(text):
                return {"text": text, "evidence": [{"source_id": source["source_id"], "quote": source["text"]}]}
            news.append({"title": claim(f"Titolo documentato numero {index + 1}."),
                         "summary": claim(f"Sintesi documentata numero {index + 1}.")})
        return SimpleNamespace(text=json.dumps({"sufficient": True, "news": news}),
                               candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    task = prompt["question"]
    if "ESATTAMENTE sette" in task:
        identities = [list(sources)[index % len(sources)] for index in range(7)]
    else:
        groups = json.loads(task.split("Gruppi: ")[1].split(" Edizioni disponibili:")[0])
        identities = [group[0] for group in groups for _ in range(2)]
    claims = [{"text": f"Sintesi documentata del passaggio numero {index + 1}.",
               "evidence": [{"source_id": identity, "quote": sources[identity]["text"]}]}
              for index, identity in enumerate(identities)]
    return SimpleNamespace(text=json.dumps({"sufficient": True, "claims": claims}),
                           candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])


@pytest.fixture
def setup_editorial(tmp_path, monkeypatch):
    catalog = make_catalog()
    client = Mock()
    client.models.generate_content.side_effect = simulated_response
    hits = [{"id": chunk.id, "distance": 0.2} for chunk in catalog.chunks[::3]]
    monkeypatch.setenv("GEMINI_RAG_MODEL", "configured-flash")
    with patch("google.genai.Client", side_effect=AssertionError("API reali vietate")), patch(
        "edicola.editorial.api_key", return_value="private-key"
    ), patch("edicola.editorial.read_catalog", return_value=catalog) as read, patch(
        "edicola.editorial.semantic_search", return_value=hits
    ) as search:
        yield tmp_path, catalog, client, read, search


def test_dossier_structure_citations_and_cache_avoids_all_api_calls(setup_editorial):
    root, catalog, client, _, search = setup_editorial
    first = generate_product("dossier", "Trasporti", root=root, authorize_external=True, client=client)
    assert first.sufficient
    assert len(first.sections) == 4
    assert first.sections[0]["heading"] == "Introduzione"
    assert first.sections[-1]["heading"] == "Conclusioni"
    assert len({source.filename for source in first.sources}) == 4
    assert first.used_source_ids
    assert first.coverage["partial"]
    assert search.call_args.kwargs["diversify_by_pdf"] is True
    second = generate_product("dossier", "Trasporti", root=root, authorize_external=True, client=client)
    assert second.from_cache
    assert second.sources == first.sources
    assert client.models.generate_content.call_count == 1
    assert search.call_count == 1  # Nessun nuovo embedding del tema sulla cache hit.
    assert client.models.generate_content.call_args.kwargs["model"] == "configured-flash"


def test_briefing_uses_multiple_editions_not_top_three(setup_editorial):
    root, _, client, _, search = setup_editorial
    result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.sufficient
    assert len(result.sources) == 12
    assert len({source.filename for source in result.sources}) == 4
    assert len(result.sections) == 4
    search.assert_not_called()  # Nessun embedding di domanda per il briefing.
    assert sum(len(source.text) for source in result.sources) <= 8000
    repeated = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert repeated.from_cache
    assert client.models.generate_content.call_count == 1


def test_balancing_publications_and_dates():
    catalog = make_catalog()
    catalog.coverage["files"][1]["publication"] = "Testata 0"
    catalog.coverage["files"][1]["date"] = "2026-10-23"
    selected = balanced_briefing(catalog, 8, 0.82)
    assert len({chunk.metadata["filename"] for chunk in selected[:3]}) == 3
    assert selected[0].metadata["filename"] == "giornale-0.pdf"
    assert selected[3].metadata["filename"] == "giornale-1.pdf"  # Nuova data della stessa testata.
    assert len({chunk.metadata["filename"] for chunk in selected}) == 4


def test_duplicate_text_is_selected_once_and_related_chunks_are_grouped():
    catalog = make_catalog()
    catalog.chunks = [replace(chunk, text="Notizia identica riportata in più edizioni del giornale.") for chunk in catalog.chunks]
    assert len(balanced_briefing(catalog, 8, 0.82)) == 1
    related = {chunk.id: [1.0, 0.0] for chunk in catalog.chunks}
    assert len(set(topic_clusters(catalog.chunks, related, 0.82).values())) == 1


def test_config_model_and_source_changes_invalidate_cache(setup_editorial, monkeypatch):
    root, catalog, client, read, _ = setup_editorial
    generate_product("briefing", root=root, authorize_external=True, client=client)
    generate_product("briefing", root=root, authorize_external=True, client=client,
                     config=EditorialConfig(briefing_chunks=4))
    assert client.models.generate_content.call_count == 2
    monkeypatch.setenv("GEMINI_RAG_MODEL", "another-configured-flash")
    generate_product("briefing", root=root, authorize_external=True, client=client)
    assert client.models.generate_content.call_count == 3
    catalog.chunks[0] = replace(catalog.chunks[0], text="Un nuovo contenuto realmente disponibile nel quotidiano.")
    generate_product("briefing", root=root, authorize_external=True, client=client)
    assert client.models.generate_content.call_count == 4


def test_insufficient_information_and_empty_index(setup_editorial):
    root, catalog, client, _, search = setup_editorial
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(
        text=json.dumps({"sufficient": False, "news": []}),
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert not result.sufficient
    assert result.diagnostics["status"] == "model_abstention"
    assert "non ha individuato notizie" in result.message
    assert not generate_product("briefing", root=root, authorize_external=True, client=client).from_cache
    catalog.chunks = []
    catalog.vectors = {}
    result = generate_product("dossier", "Tema", root=root, authorize_external=True, client=client)
    assert not result.sufficient
    assert result.sources == []
    assert client.models.generate_content.call_count == 2
    search.assert_not_called()


def test_invalid_references_are_rejected_and_not_cached(setup_editorial):
    root, _, client, _, _ = setup_editorial
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(
        text=json.dumps({"sufficient": True, "news": [{
            key: {"text": "Fatto inventato.", "evidence": [{"source_id": "S99", "quote": "Una citazione inventata."}]}
            for key in ("title", "summary")}]}),
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    for _ in range(2):
        result = generate_product("briefing", root=root, authorize_external=True, client=client)
        assert not result.sufficient
        assert not result.used_source_ids
        assert result.diagnostics["status"] == "citation_validation_failed"
        assert "Verifica delle citazioni fallita" in result.message
    assert client.models.generate_content.call_count == 2


def test_api_errors_are_safe_and_do_not_poison_cache(setup_editorial):
    root, _, client, _, _ = setup_editorial
    client.models.generate_content.side_effect = errors.ClientError(403, {"error": {"code": 403, "message": "private-key"}})
    with pytest.raises(EditorialError) as caught:
        generate_product("briefing", root=root, authorize_external=True, client=client)
    assert "private-key" not in str(caught.value)
    assert not (root / "data/editorial.sqlite3").exists()



def test_briefing_400_schema_fallback_keeps_verified_citations_and_cache(setup_editorial, caplog):
    root, _, client, _, _ = setup_editorial
    def api_response(**kwargs):
        if kwargs["config"].response_json_schema is not None:
            raise errors.ClientError(400, {"error": {"code": 400, "message": "private-key"}})
        return simulated_response(**kwargs)
    client.models.generate_content.side_effect = api_response
    with caplog.at_level("WARNING", logger="edicola"):
        result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.sufficient and result.used_source_ids
    assert client.models.generate_content.call_count == 2
    assert client.models.generate_content.call_args.kwargs["config"].response_json_schema is None
    assert "event=schema_fallback" in caplog.text
    assert "private-key" not in caplog.text
    assert generate_product("briefing", root=root, authorize_external=True, client=client).from_cache
    assert client.models.generate_content.call_count == 2


def test_authorization_prevents_any_generation(setup_editorial):
    root, _, client, read, search = setup_editorial
    with pytest.raises(EditorialError):
        generate_product("briefing", root=root, client=client)
    read.assert_not_called()
    search.assert_not_called()
    client.models.generate_content.assert_not_called()


def test_char_budget_is_enforced(setup_editorial):
    root, catalog, client, _, _ = setup_editorial
    catalog.chunks = [replace(chunk, text=chunk.text * (100 if index == 0 else 5)) for index, chunk in enumerate(catalog.chunks)]
    result = generate_product("briefing", root=root, authorize_external=True, client=client,
                              config=EditorialConfig(max_source_chars=2000))
    assert sum(len(source.text) for source in result.sources) <= 2000


def test_owned_client_uses_configured_model_and_limited_sdk_retries(setup_editorial):
    root, _, client, _, _ = setup_editorial
    with patch("edicola.editorial.genai.Client", return_value=client) as constructor:
        assert generate_product("briefing", root=root, authorize_external=True).sufficient
    assert constructor.call_args.kwargs["http_options"].retry_options.attempts == 1
    assert constructor.call_args.kwargs["http_options"].timeout == 30000
    assert client.models.generate_content.call_args.kwargs["model"] == "configured-flash"
    client.close.assert_called_once()


def news_for(source, number=1):
    def claim(text):
        return {"text": text, "evidence": [{"source_id": source.id, "quote": source.text}]}
    return {"title": claim(f"Notizia documentata {number}."), "summary": claim(f"Sintesi della notizia {number}.")}


def test_briefing_can_validate_eight_news_without_global_rag_claim_limit():
    sources = [Source(f"S{i}", f"id-{i}", "giornale.pdf", i, f"Passaggio originale numero {i} su una notizia documentata.", 0.0)
               for i in range(1, 9)]
    raw = json.dumps({"sufficient": True, "news": [news_for(source, i) for i, source in enumerate(sources)]})
    result = render_product("briefing", raw, sources, {"partial": True}, [])
    assert result.sufficient
    assert len(result.sections) == 8
    assert result.diagnostics["status"] == "ok"
    assert set(result.used_source_ids) == {source.id for source in sources}


def test_one_valid_news_is_a_partial_briefing_not_an_abstention():
    source = Source("S1", "id", "a.pdf", 1, "Il consiglio comunale ha approvato il piano dei trasporti.", 0.0)
    result = render_product("briefing", json.dumps({"sufficient": True, "news": [news_for(source)]}), [source], {}, [])
    assert result.sufficient
    assert len(result.sections) == 1


def test_only_invalid_news_is_rejected_not_whole_briefing():
    source = Source("S1", "id", "a.pdf", 1, "Il consiglio comunale ha approvato il piano dei trasporti.", 0.0)
    good = news_for(source)
    bad = news_for(source, 2)
    bad["summary"]["evidence"][0]["quote"] = "Citazione non presente nella fonte selezionata."
    result = render_product("briefing", json.dumps({"sufficient": True, "news": [good, bad]}), [source], {}, [])
    assert result.sufficient
    assert len(result.sections) == 1
    assert result.diagnostics["status"] == "partial_validation"
    assert "scartate" in result.message


@pytest.mark.parametrize("text,status", [("not JSON", "invalid_json"), ("{}", "invalid_structure"), ("", "empty_response")])
def test_diagnostics_distinguish_malformed_output_from_insufficient_sources(setup_editorial, text, status, caplog):
    root, _, client, _, _ = setup_editorial
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text=text, candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    with caplog.at_level("INFO", logger="edicola"):
        result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.diagnostics["status"] == status
    assert result.message != INSUFFICIENT
    assert status in caplog.text
    assert "private-key" not in caplog.text
    assert not (root / "data/editorial.sqlite3").exists()


def test_truncated_output_is_reported_and_not_cached(setup_editorial):
    root, _, client, _, _ = setup_editorial
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text="private-response", candidates=[SimpleNamespace(finish_reason=types.FinishReason.MAX_TOKENS)])
    result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.diagnostics["status"] == "output_truncated"
    assert "troncata" in result.message
    assert not (root / "data/editorial.sqlite3").exists()


def test_all_distinct_topic_passages_reach_briefing_prompt(setup_editorial):
    root, catalog, client, _, _ = setup_editorial
    for index, chunk in enumerate(catalog.chunks):
        catalog.vectors[chunk.id] = [float(axis == index) for axis in range(len(catalog.chunks))]
    result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert len(result.sources) == len(catalog.chunks)  # Nessun tetto globale a otto.
    prompt = json.loads(client.models.generate_content.call_args.kwargs["contents"])
    assert len(prompt["sources"]) == len(catalog.chunks)
    assert len(prompt["topic_hints"]) == len(catalog.chunks)
    assert {source.page for source in result.sources} >= {1, 2}
    assert client.models.generate_content.call_args.kwargs["config"].system_instruction == BRIEFING_INSTRUCTION
    assert "non c'è un numero minimo" in BRIEFING_INSTRUCTION.lower()


def test_selection_preserves_multiple_pages_and_prioritizes_headline_hints():
    catalog = make_catalog()
    selected = balanced_briefing(catalog, 12, 0.82)
    for filename in {chunk.metadata["filename"] for chunk in selected}:
        assert len({chunk.metadata["page"] for chunk in selected if chunk.metadata["filename"] == filename}) == 3
    normal = replace(catalog.chunks[0], text="Un lungo testo descrittivo che continua una notizia senza titolo chiaramente identificabile.")
    headline = replace(normal, text="APPROVATO IL NUOVO PIANO: il consiglio annuncia nuovi servizi di trasporto pubblico.")
    assert headline_priority(headline) > headline_priority(normal)


def test_near_duplicates_preserve_overlap_and_different_numbers():
    original = "Il consiglio comunale approva il piano dei trasporti con 20 nuove corse e servizi per tutti i quartieri della città a partire dalla prossima settimana."
    assert near_duplicate(original, original + "\n")
    assert near_duplicate(original, original.replace("settimana.", "settimana prossima."))
    assert not near_duplicate(original, original.replace("20", "30"))
    assert not near_duplicate(original, original[-30:] + " Un'altra notizia completamente diversa su altri argomenti.")


def test_briefing_version_invalidates_old_negative_cache_without_deleting_dossier(setup_editorial):
    root, catalog, client, _, search = setup_editorial
    dossier = generate_product("dossier", "Tema", root=root, authorize_external=True, client=client)
    config = EditorialConfig()
    old_payload = {"version": 1, "kind": "briefing", "topic": "", "model": "configured-flash", "config": asdict(config),
                   "coverage": catalog.coverage, "chunks": sorted((c.id, c.fingerprint, c.metadata) for c in catalog.chunks)}
    old_key = hashlib.sha256(json.dumps(old_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = root / "data/editorial.sqlite3"
    cache_write(path, old_key, EditorialResult("briefing", "Informazioni insufficienti", [], [], [], catalog.coverage, False, INSUFFICIENT))
    result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.sufficient and not result.from_cache
    assert generate_product("dossier", "Tema", root=root, authorize_external=True, client=client).from_cache
    assert client.models.generate_content.call_count == 2
    assert search.call_count == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 3


def test_complete_prompt_budget_includes_system_and_metadata(setup_editorial, monkeypatch):
    root, catalog, client, _, _ = setup_editorial
    monkeypatch.setenv("EDITORIAL_BRIEFING_MAX_PROMPT_CHARS", "5000")
    catalog.chunks = [replace(chunk, text=chunk.text * (100 if index == 0 else 5)) for index, chunk in enumerate(catalog.chunks)]
    result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.sufficient
    assert result.sources
    assert all(source.text == next(c.text for c in catalog.chunks if c.id == source.chunk_id) for source in result.sources)
    call = client.models.generate_content.call_args.kwargs
    assert len(call["contents"]) + len(call["config"].system_instruction) <= 5000
    assert result.diagnostics["prompt_chars"] <= result.diagnostics["prompt_budget"]


def test_too_small_budget_is_not_reported_as_insufficient_sources(setup_editorial, monkeypatch):
    root, _, client, _, _ = setup_editorial
    monkeypatch.setenv("EDITORIAL_BRIEFING_MAX_PROMPT_CHARS", "2000")
    result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.diagnostics["status"] == "prompt_budget_exceeded"
    assert "Budget" in result.message
    client.models.generate_content.assert_not_called()


def test_duplicate_generated_news_is_not_repeated():
    source = Source("S1", "id", "a.pdf", 1, "Il consiglio comunale ha approvato il piano dei trasporti.", 0.0)
    item = news_for(source)
    draft = validate_briefing(json.dumps({"sufficient": True, "news": [item, item]}), [source])
    assert len(draft.sections) == 1
    assert draft.diagnostics["duplicates_removed"] == 1


@pytest.mark.parametrize("kwargs", [{"dossier_chunks": 6}, {"briefing_chunks": 21}, {"max_source_chars": 100}, {"topic_similarity": 1.1}])
def test_invalid_configs(kwargs):
    with pytest.raises(ValueError):
        EditorialConfig(**kwargs)


def test_balanced_briefing_preserves_same_text_across_distinct_editions():
    catalog = make_catalog()
    text = "Lo stesso articolo viene riportato in più edizioni, con una frase sufficientemente lunga per la selezione."
    catalog.chunks = [replace(chunk, text=text) for chunk in catalog.chunks]
    selected = balanced_briefing(catalog, 8, 0.82, preserve_editions=True)
    assert len(selected) == 4
    assert {chunk.metadata["filename"] for chunk in selected} == {item["pdf"] for item in catalog.coverage["files"]}
    assert len(balanced_briefing(catalog, 8, 0.82, preserve_editions=False)) == 1



def test_briefing_reports_selected_and_cited_sources_separately(setup_editorial, caplog):
    root, _, client, _, _ = setup_editorial
    with caplog.at_level("INFO", logger="edicola"):
        result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.sufficient
    assert result.diagnostics["selected_pdfs"] == 4
    assert result.diagnostics["cited_pdfs"] == 4
    assert result.diagnostics["cited_passages"] == len(result.used_source_ids)
    assert "phase=briefing_coverage selected_pdfs=4 cited_pdfs=4" in caplog.text


def test_one_cited_pdf_does_not_misreport_four_selected_pdfs(setup_editorial):
    root, _, client, _, _ = setup_editorial
    client.models.generate_content.side_effect = None
    def only_one(**kwargs):
        source = json.loads(kwargs["contents"])["sources"][0]
        claim = lambda text: {"text": text, "evidence": [
            {"source_id": source["source_id"], "quote": source["text"]}]}
        return SimpleNamespace(text=json.dumps({"sufficient": True, "news": [
            {"title": claim("Un titolo verificabile"), "summary": claim("Una vicenda verificabile")}
        ]}), candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    client.models.generate_content.side_effect = only_one
    result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.sufficient
    assert result.diagnostics["selected_pdfs"] == 4
    assert result.diagnostics["cited_pdfs"] == 1
    assert len(result.used_source_ids) == 1
    assert len(result.sections) == 1



def test_briefing_switches_model_only_after_two_server_503_errors(setup_editorial, monkeypatch, caplog):
    root, _, client, _, _ = setup_editorial
    monkeypatch.setenv("GEMINI_RAG_FALLBACK_MODEL", "backup-flash")
    def maybe_busy(**kwargs):
        if kwargs["model"] == "configured-flash":
            raise errors.ServerError(503, {"error": {"code": 503, "message": "private-key"}})
        return simulated_response(**kwargs)
    client.models.generate_content.side_effect = maybe_busy
    with patch("edicola.briefing.time.sleep", return_value=None), caplog.at_level("INFO", logger="edicola"):
        result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.sufficient
    assert [c.kwargs["model"] for c in client.models.generate_content.call_args_list] == [
        "configured-flash", "configured-flash", "backup-flash"
    ]
    assert len({c.kwargs["contents"] for c in client.models.generate_content.call_args_list}) == 1
    assert all(c.kwargs["config"].response_mime_type == "application/json"
               for c in client.models.generate_content.call_args_list)
    assert result.used_source_ids
    assert "phase=briefing_generation event=model_fallback" in caplog.text
    assert "private-key" not in caplog.text
    assert generate_product("briefing", root=root, authorize_external=True, client=client).from_cache


@pytest.mark.parametrize("status", [403, 429])
def test_briefing_switches_model_on_quota_but_not_permission_errors(setup_editorial, monkeypatch, status):
    root, _, client, _, _ = setup_editorial
    monkeypatch.setenv("GEMINI_RAG_FALLBACK_MODEL", "backup-flash")
    client.models.generate_content.side_effect = errors.ClientError(
        status, {"error": {"code": status, "message": "private-key"}})
    with patch("edicola.briefing.time.sleep", return_value=None):
        with pytest.raises(EditorialError) as exc:
            generate_product("briefing", root=root, authorize_external=True, client=client)
    assert "private-key" not in str(exc.value)
    assert client.models.generate_content.call_count == (2 if status == 429 else 1)
    assert [c.kwargs["model"] for c in client.models.generate_content.call_args_list] == (
        ["configured-flash", "backup-flash"] if status == 429 else ["configured-flash"])


def test_briefing_fallback_disabled_retries_primary_only(setup_editorial, monkeypatch):
    root, _, client, _, _ = setup_editorial
    monkeypatch.setenv("GEMINI_RAG_FALLBACK_MODEL", "off")
    client.models.generate_content.side_effect = errors.ServerError(
        503, {"error": {"code": 503, "message": "private-key"}})
    with patch("edicola.briefing.time.sleep", return_value=None):
        with pytest.raises(EditorialError, match="503"):
            generate_product("briefing", root=root, authorize_external=True, client=client)
    assert client.models.generate_content.call_count == 3


def test_briefing_rejects_invalid_fallback_citations(setup_editorial, monkeypatch):
    root, _, client, _, _ = setup_editorial
    monkeypatch.setenv("GEMINI_RAG_FALLBACK_MODEL", "backup-flash")
    def maybe_busy(**kwargs):
        if kwargs["model"] == "configured-flash":
            raise errors.ServerError(503, {"error": {"code": 503, "message": "private-key"}})
        return SimpleNamespace(
            text=json.dumps({"sufficient": True, "news": [{
                key: {"text": "Dato non verificato", "evidence": [
                    {"source_id": "S999", "quote": "Citazione non presente in alcuna fonte"}]}
                for key in ("title", "summary")}] }),
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    client.models.generate_content.side_effect = maybe_busy
    with patch("edicola.briefing.time.sleep", return_value=None):
        result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert not result.sufficient and result.diagnostics["status"] == "citation_validation_failed"
    assert not (root / "data/editorial.sqlite3").exists()



def test_sparse_briefing_tries_unseen_passages_for_more_distinct_news(setup_editorial):
    root, catalog, client, _, _ = setup_editorial
    # Il contesto iniziale non puo' contenere tutti i passaggi: i PDF non
    # inclusi devono essere consultati in un secondo giro.
    expanded = " Il consiglio ha comunicato altri dettagli verificabili." * 70
    catalog.chunks = [replace(chunk, text=chunk.text + expanded) for chunk in catalog.chunks]
    calls = []

    def two_pass_briefing(**kwargs):
        data = json.loads(kwargs["contents"])
        calls.append(data)
        passages = data["sources"]
        assert len(passages) >= 2
        def news(source, title):
            claim = lambda text: {"text": text, "evidence": [{
                "source_id": source["source_id"], "quote": source["text"][:150]}]}
            return {"title": claim(title), "summary": claim(f"Approfondimento della notizia: {title}.")}
        if len(calls) == 1:
            selection = [news(passages[0], "Vicenda A documentata"),
                         news(passages[1], "Vicenda B documentata")]
        else:
            assert data["already_covered"] == ["Vicenda A documentata", "Vicenda B documentata"]
            assert set(p["source_id"] for p in passages).isdisjoint(
                p["source_id"] for p in calls[0]["sources"])
            selection = [news(passages[0], "Vicenda C documentata"),
                         news(passages[1], "Vicenda D documentata")]
        return SimpleNamespace(text=json.dumps({"sufficient": True, "news": selection}),
                               candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])

    client.models.generate_content.side_effect = two_pass_briefing
    result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.sufficient
    assert len(result.sections) == 4
    assert result.diagnostics["additional_news"] == 2
    assert len(calls) == 2
    assert len(result.used_source_ids) == 4
    assert len({s.chunk_id for s in result.sources}) == len(result.sources)
    assert generate_product("briefing", root=root, authorize_external=True, client=client).from_cache
    assert client.models.generate_content.call_count == 2


def test_briefing_second_pass_failure_preserves_first_verified_news(setup_editorial):
    root, catalog, client, _, _ = setup_editorial
    expanded = " Il consiglio ha comunicato altri dettagli verificabili." * 70
    catalog.chunks = [replace(chunk, text=chunk.text + expanded) for chunk in catalog.chunks]
    calls = []

    def generation(**kwargs):
        calls.append(kwargs["model"])
        if len(calls) > 1:
            raise errors.ServerError(503, {"error": {"code": 503, "message": "private-key"}})
        source = json.loads(kwargs["contents"])["sources"][0]
        claim = lambda text: {"text": text, "evidence": [{
            "source_id": source["source_id"], "quote": source["text"][:150]}]}
        return SimpleNamespace(text=json.dumps({"sufficient": True, "news": [{
            "title": claim("Prima notizia verificata"),
            "summary": claim("La prima notizia e' documentata.")}]}),
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])

    client.models.generate_content.side_effect = generation
    with patch("edicola.briefing.time.sleep", return_value=None):
        result = generate_product("briefing", root=root, authorize_external=True, client=client)
    assert result.sufficient
    assert len(result.sections) == 1
    assert len(calls) > 1
    assert result.used_source_ids


def test_merge_briefing_removes_duplicate_even_with_different_reference_numbers():
    from edicola.briefing import BriefingDraft, merge_briefing_drafts
    a = BriefingDraft([{"heading": "Un progetto approvato [S1]",
                        "text": "Il progetto e' stato approvato dal consiglio comunale [S1]"}],
                      ["S1"], diagnostics={"received_news": 1, "validated_news": 1})
    b = BriefingDraft([{"heading": "Un progetto approvato [S7]",
                        "text": "Il progetto e' stato approvato dal consiglio comunale [S7]"},
                       {"heading": "Una seconda notizia [S8]",
                        "text": "Un altro provvedimento documentato [S8]"}],
                      ["S7", "S8"], diagnostics={"received_news": 2, "validated_news": 2})
    result = merge_briefing_drafts(a, b)
    assert len(result.sections) == 2
    assert result.used_source_ids == ["S1", "S8"]
    assert result.diagnostics["duplicates_removed"] == 1
    assert result.diagnostics["additional_news"] == 1
