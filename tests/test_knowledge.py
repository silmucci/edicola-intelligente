"""Timeline, mappe e cache JSON con Gemini e retrieval simulati."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from google import genai
from google.genai import errors, types

from edicola.archive import IndexChunk
from edicola.editorial_selection import Catalog
from edicola.knowledge import KnowledgeError, generate_data, generate_knowledge, knowledge_schema
from edicola.knowledge_validation import documented_dates, map_dot, validate_map, validate_timeline
from edicola.rag import Source


TEXT1 = "Il Comune di Roma approva il piano il 12 ottobre 2026. Il piano riguarda i trasporti."
TEXT2 = "La Regione Lazio finanzia il progetto il 3 ottobre 2026 con risorse regionali. La Regione Lazio si occupa di trasporti."
SOURCES = [Source("S1", "a", "a.pdf", 2, TEXT1, 0.2), Source("S2", "b", "b.pdf", 4, TEXT2, 0.3)]
COVERAGE = {"indexed": 2, "total": 4, "partial": True, "warnings": [], "files": [
    {"pdf": "a.pdf", "publication": "Testata A", "date": "2026-10-23", "indexed": 1, "total": 2},
    {"pdf": "b.pdf", "publication": "Testata B", "date": "2026-10-23", "indexed": 1, "total": 2},
]}


def claim(text, source=SOURCES[0]):
    return {"text": text, "evidence": [{"source_id": source.id, "quote": source.text}]}


def event(source=SOURCES[0], event_date="2026-10-12"):
    return {"title": claim("Approvazione del piano", source), "description": claim("La fonte descrive l'approvazione del piano.", source),
            "event_date": event_date, "date_evidence": {"source_id": source.id, "quote": source.text}}


def map_data():
    return {"nodes": [
        {"id": "N1", "kind": "organization", "label": claim("Comune di Roma")},
        {"id": "N2", "kind": "concept", "label": claim("piano")},
        {"id": "N3", "kind": "organization", "label": claim("Regione Lazio", SOURCES[1])},
    ], "edges": [
        {"from_id": "N1", "to_id": "N2", "kind": "documented", "label": claim("approva")},
        {"from_id": "N2", "to_id": "N3", "kind": "thematic", "label": {
            "text": "trasporti", "evidence": [
                {"source_id": s.id, "quote": s.text} for s in SOURCES]}},
    ]}


def test_timeline_orders_only_verified_event_dates_and_keeps_publication_separate():
    raw = {"events": [event(), event(SOURCES[1], "2026-10-03")]}
    data, diagnostics = validate_timeline(raw, SOURCES, COVERAGE)
    assert [e["event_date"] for e in data["events"]] == ["2026-10-03", "2026-10-12"]
    assert data["events"][0]["publication_dates"][0]["date"] == "2026-10-23"
    assert diagnostics["dated_events"] == 2


@pytest.mark.parametrize("text,proposed,status", [
    ("Il Comune di Roma approva il piano il 12 ottobre per migliorare i trasporti.", "2026-10-12", "ambiguous"),
    ("Il Comune di Roma approva il piano il 30 febbraio 2026 per i trasporti.", "2026-02-28", "unverified"),
    ("Edizione del 23 ottobre 2026. Il Comune di Roma approva il piano.", "2026-10-23", "publication_reference"),
    ("Il Comune di Roma approva il piano: riunioni il 12 ottobre 2026 e il 13 ottobre 2026.", "2026-10-12", "ambiguous"),
])
def test_unreliable_dates_are_not_placed_chronologically(text, proposed, status):
    source = replace(SOURCES[0], text=text)
    data, _ = validate_timeline({"events": [event(source, proposed)]}, [source], COVERAGE)
    assert not data["events"]
    assert data["undated_events"][0]["date_status"] == status
    assert data["undated_events"][0]["event_date"] is None


def test_missing_dates_are_retained_as_undated():
    item = event()
    item["event_date"] = item["date_evidence"] = None
    data, _ = validate_timeline({"events": [item]}, SOURCES, COVERAGE)
    assert not data["events"]
    assert len(data["undated_events"]) == 1


def test_fabricated_date_in_description_is_not_shown():
    item = event()
    item["description"] = claim("Il piano è approvato il 15 ottobre 2026.")
    data, counts = validate_timeline({"events": [item]}, SOURCES, COVERAGE)
    assert not data["events"] and not data["undated_events"]
    assert counts["rejected_events"] == 1


def test_date_parser_accepts_italian_and_iso_without_inferring_relative_dates():
    assert documented_dates("Il 12 ottobre 2026, 13/10/2026 e 2026-10-14.") == {"2026-10-12", "2026-10-13", "2026-10-14"}
    assert not documented_dates("Ieri, il 12 ottobre, nel 2026 e il 30/02/2026.")


def test_map_preserves_documented_and_thematic_sources_and_styles():
    data, counts = validate_map(map_data(), SOURCES)
    assert len(data["nodes"]) == 3 and len(data["edges"]) == 2
    assert data["edges"][1]["label"] == "associazione tematica"
    dot = map_dot(data)
    assert "style=dashed, dir=none" in dot
    assert "style=solid, dir=forward" in dot
    assert "[S1]" not in dot
    assert "S1" in data["edges"][0]["source_ids"]
    assert not counts["rejected_edges"]


@pytest.mark.parametrize("kind,label", [("documented", "causa"), ("thematic", "provoca")])
def test_unsupported_causal_relations_are_rejected(kind, label):
    raw = map_data()
    raw["edges"] = [{"from_id": "N1", "to_id": "N2", "kind": kind, "label": claim(label)}]
    data, counts = validate_map(raw, SOURCES)
    assert not data["edges"]
    assert counts["rejected_edges"] == 1


def test_negated_relation_does_not_become_positive():
    source = replace(SOURCES[0], text="Il Comune di Roma non approva il piano per la viabilità e i trasporti.")
    raw = {"nodes": [{"id": "N1", "kind": "organization", "label": claim("Comune di Roma", source)},
                     {"id": "N2", "kind": "concept", "label": claim("piano", source)}],
           "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented", "label": claim("approva", source)}]}
    data, _ = validate_map(raw, [source])
    assert not data["edges"]


def test_unknown_source_and_unknown_node_cannot_create_links():
    raw = map_data()
    raw["nodes"][0]["label"]["evidence"][0]["source_id"] = "S99"
    raw["edges"][0]["to_id"] = "N99"
    data, counts = validate_map(raw, SOURCES)
    assert all(node["id"] != "N1" for node in data["nodes"])
    assert counts["rejected_nodes"] == 1
    assert counts["rejected_edges"] >= 1


def test_cooccurrence_is_not_a_causal_relation_between_entities():
    source = replace(SOURCES[0], text="Il Comune di Roma riferisce che l'alluvione provoca danni al piano dei trasporti.")
    raw = {"nodes": [{"id": "N1", "kind": "organization", "label": claim("Comune di Roma", source)},
                     {"id": "N2", "kind": "concept", "label": claim("piano", source)}],
           "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented", "label": claim("provoca", source)}]}
    data, _ = validate_map(raw, [source])
    assert not data["edges"]


@pytest.fixture
def setup_knowledge(tmp_path, monkeypatch):
    chunks = [IndexChunk(s.chunk_id, s.text, {"filename": s.filename, "page": s.page,
              "pdf_sha256": str(index) * 64, "position": 1}) for index, s in enumerate(SOURCES)]
    catalog = Catalog(chunks, {}, COVERAGE)
    client = Mock()
    def response(**kwargs):
        prompt = json.loads(kwargs["contents"])
        value = {"events": [event()]} if prompt["task"] == "timeline" else map_data()
        return SimpleNamespace(text=json.dumps(value), candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    client.models.generate_content.side_effect = response
    monkeypatch.setenv("GEMINI_RAG_MODEL", "configured-flash")
    with patch("google.genai.Client", side_effect=AssertionError("API reali vietate")), patch(
        "edicola.knowledge.api_key", return_value="private-key"
    ), patch("edicola.knowledge.read_catalog", return_value=catalog) as read, patch(
        "edicola.knowledge.semantic_search", return_value=[{"id": s.chunk_id, "distance": s.distance} for s in SOURCES]
    ) as search:
        yield tmp_path, catalog, client, read, search


@pytest.mark.parametrize("kind", ["timeline", "map"])
def test_generation_cache_coverage_and_model_preserved(setup_knowledge, kind):
    root, _, client, _, search = setup_knowledge
    first = generate_knowledge(kind, "Trasporti", authorize_external=True, root=root, client=client)
    assert first.coverage["partial"]
    assert first.sources == SOURCES
    second = generate_knowledge(kind, "Trasporti", authorize_external=True, root=root, client=client)
    assert second.from_cache
    assert first.data == second.data
    assert client.models.generate_content.call_count == 1
    assert client.models.generate_content.call_args.kwargs["model"] == "configured-flash"
    assert search.call_count == 1
    assert search.call_args.kwargs["diversify_by_pdf"] is (kind != "map")
    assert not list(root.rglob("*.sqlite3"))  # Cache esclusivamente JSON.


def test_changed_sources_and_model_invalidate_cache(setup_knowledge, monkeypatch):
    root, catalog, client, _, _ = setup_knowledge
    generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client)
    monkeypatch.setenv("GEMINI_RAG_MODEL", "other-configured-flash")
    generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client)
    catalog.chunks[0] = replace(catalog.chunks[0], text=TEXT1 + " Un aggiornamento documentato.")
    generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client)
    assert client.models.generate_content.call_count == 3


def test_authorization_and_empty_index_prevent_api_calls(setup_knowledge):
    root, catalog, client, read, search = setup_knowledge
    with pytest.raises(KnowledgeError):
        generate_knowledge("timeline", "Trasporti", root=root, client=client)
    read.assert_not_called()
    catalog.chunks = []
    result = generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client)
    assert result.diagnostics["status"] == "no_sources"
    search.assert_not_called()
    client.models.generate_content.assert_not_called()


def test_malformed_generation_is_not_cached(setup_knowledge):
    root, _, client, _, _ = setup_knowledge
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text="not JSON", candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    with pytest.raises(KnowledgeError, match="strutturati"):
        generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client)
    assert not (root / "data/knowledge_cache").exists()


@pytest.mark.parametrize("failure", [errors.ServerError(503, {"error": {"code": 503, "message": "private-key"}}), httpx.ConnectError("private-key")])
def test_generation_retries_are_limited_and_logs_safe(failure, caplog):
    client = Mock()
    client.models.generate_content.side_effect = failure
    with caplog.at_level("INFO", logger="edicola"), pytest.raises(KnowledgeError) as caught:
        generate_data(client, "configured-flash", "private-documents", {}, sleep=Mock())
    assert client.models.generate_content.call_count == 3
    assert "private-key" not in str(caught.value) + caplog.text
    assert "private-documents" not in caplog.text


def test_truncated_output_is_not_shown_or_cached(setup_knowledge):
    root, _, client, _, _ = setup_knowledge
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text="partial", candidates=[SimpleNamespace(finish_reason=types.FinishReason.MAX_TOKENS)])
    with pytest.raises(KnowledgeError, match="troncata"):
        generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client)
    assert not (root / "data/knowledge_cache").exists()


def test_owned_client_uses_configured_model_timeout_and_no_sdk_retry(setup_knowledge):
    root, _, client, _, _ = setup_knowledge
    with patch("edicola.knowledge.genai.Client", return_value=client) as constructor:
        result = generate_knowledge("map", "Trasporti", authorize_external=True, root=root)
    assert result.data["nodes"]
    assert constructor.call_args.kwargs["http_options"].retry_options.attempts == 1
    assert constructor.call_args.kwargs["http_options"].timeout == 30000
    assert client.models.generate_content.call_args.kwargs["model"] == "configured-flash"
    client.close.assert_called_once()


@pytest.mark.parametrize("kind", ["timeline", "map"])
def test_sdk_serializes_simplified_schema_without_nested_array_bounds(kind):
    """Esegue anche la conversione SDK e HTTP, senza alcuna connessione reale."""
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": "{}"}], "role": "model"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as transport:
        with genai.Client(api_key="fake-test-key", vertexai=False, http_options=types.HttpOptions(
            httpx_client=transport, retry_options=types.HttpRetryOptions(attempts=1))) as client:
            assert generate_data(client, "configured-flash", "test", knowledge_schema(kind, SOURCES)) == "{}"
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/models/configured-flash:generateContent")
    config = json.loads(requests[0].content)["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["maxOutputTokens"] == 8192
    schema = config["responseJsonSchema"]
    assert "responseSchema" not in config  # Un solo canale per lo schema JSON.
    assert "maxItems" not in json.dumps(schema)
    assert "minItems" not in json.dumps(schema)
    assert set(schema["properties"]) == ({"events"} if kind == "timeline" else {"nodes", "edges"})
    # La costruzione non deve alterare lo schema del chatbot.
    from edicola.rag import response_schema
    assert response_schema(SOURCES)["properties"]["claims"]["maxItems"] == 8


@pytest.mark.parametrize("message,details,category", [
    ("Response schema has too many states for serving", [], "schema"),
    ("Unknown name maxItems in response_schema", [], "schema"),
    ("Request contains an invalid argument", [{"fieldViolations": [
        {"field": "generation_config.response_json_schema", "description": "Too complex"}]}], "schema"),
    ("temperature is not supported for this model", [], "unsupported_parameter"),
    ("response_mime_type is not supported", [], "unsupported_parameter"),
    ("API key not valid", [], "authentication"),
    ("Input token count exceeds the maximum", [], "invalid_request"),
    ("Invalid argument", [], "invalid_request"),
])
def test_http_400_classification_through_sdk_has_no_retry_or_sensitive_logs(message, details, category, caplog):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT",
            "message": message + " private-documents fake-secret", "details": details}})
    sleep = Mock()
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as transport:
        with genai.Client(api_key="fake-secret", vertexai=False, http_options=types.HttpOptions(
            httpx_client=transport, retry_options=types.HttpRetryOptions(attempts=1))) as client:
            with caplog.at_level("INFO", logger="edicola.knowledge"), pytest.raises(KnowledgeError) as caught:
                generate_data(client, "configured-flash", "private-documents", knowledge_schema("map", SOURCES), sleep=sleep)
    assert len(requests) == 1
    sleep.assert_not_called()
    assert f"({category})" in str(caught.value)
    assert f"error_kind={category}" in caplog.text
    assert "http_status=400" in caplog.text
    assert "model='configured-flash'" in caplog.text
    assert "fake-secret" not in caplog.text + str(caught.value)
    assert "private-documents" not in caplog.text + str(caught.value)


@pytest.mark.parametrize("field,limit", [("events", 12), ("nodes", 16), ("edges", 24)])
def test_array_limits_still_enforced_in_python(field, limit):
    raw = {"events": [event()] * (limit + 1)} if field == "events" else map_data()
    if field != "events":
        raw[field] = [raw[field][0]] * (limit + 1)
    with pytest.raises(ValueError, match="invalid_structure"):
        if field == "events":
            validate_timeline(raw, SOURCES, COVERAGE)
        else:
            validate_map(raw, SOURCES)


@pytest.mark.parametrize("evidence", [[], [dict(source_id="S1", quote=TEXT1)] * 6])
def test_evidence_limits_still_enforced_in_python(evidence):
    raw = {"events": [event()]}
    raw["events"][0]["title"]["evidence"] = evidence
    data, counts = validate_timeline(raw, SOURCES, COVERAGE)
    assert counts["rejected_events"] == 1
    assert not data["events"] and not data["undated_events"]


def test_only_knowledge_strategy_cache_is_invalidated(setup_knowledge, monkeypatch):
    root, _, client, _, _ = setup_knowledge
    monkeypatch.setattr("edicola.knowledge.VERSION", "knowledge-v1")
    generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client)
    old_cache = list((root / "data/knowledge_cache").glob("*.json"))[0]
    monkeypatch.setattr("edicola.knowledge.VERSION", "knowledge-v2")
    result = generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client)
    assert not result.from_cache
    assert old_cache.exists()
    assert len(list((root / "data/knowledge_cache").glob("*.json"))) == 2
    assert generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    assert client.models.generate_content.call_count == 2


def test_rejected_schema_is_not_cached(setup_knowledge):
    root, _, client, _, _ = setup_knowledge
    client.models.generate_content.side_effect = errors.ClientError(400, {"error": {
        "code": 400, "message": "Response schema is too complex"}})
    with pytest.raises(KnowledgeError, match="400 \\(schema\\)"):
        generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client)
    client.models.generate_content.assert_called_once()
    assert not (root / "data/knowledge_cache").exists()


def test_timeline_context_uses_only_temporal_source_edition_and_preserves_citations():
    from copy import deepcopy
    text = "Mercoledì 21 ottobre si terrà l'incontro del Comune di Roma sul piano dei trasporti."
    source = replace(SOURCES[0], text=text)
    coverage = deepcopy(COVERAGE)
    coverage["files"][0]["date"] = "2026-10-17"
    coverage["files"][1]["date"] = "2027-10-17"
    raw = {"events": [event(source, None)]}
    # Anche se il modello usa il passato, la rappresentazione conserva l'annuncio originale.
    raw["events"][0]["description"] = claim("L'incontro si è svolto.", source)
    data, _ = validate_timeline(raw, [source, SOURCES[1]], coverage)
    result = data["events"][0]
    assert result["event_date"] == "2026-10-21"
    assert result["date_origin"] == "edition_metadata"
    assert result["event_status"] == "announced"
    assert result["description"] == text
    assert result["temporal_quote"] == text
    assert result["source_ids"] == ["S1"]
    assert result["date_anchor"] == {"source_id": "S1", "pdf": "a.pdf", "publication_date": "2026-10-17",
                                     "rule": "edition_and_document_context"}
    assert result["publication_dates"] == [{"source_id": "S1", "date": "2026-10-17"}]
    assert source.page == 2 and source.filename == "a.pdf"


def test_timeline_never_borrows_date_from_another_source():
    from copy import deepcopy
    text = "Mercoledì 21 ottobre si terrà l'incontro del Comune di Roma sul piano dei trasporti."
    source = replace(SOURCES[0], text=text)
    coverage = deepcopy(COVERAGE)
    coverage["files"][0]["date"] = ""
    coverage["files"][1]["date"] = "2026-10-17"
    data, _ = validate_timeline({"events": [event(source, None)]}, [source, SOURCES[1]], coverage)
    assert not data["events"]
    assert data["undated_events"][0]["date_reason"] == "missing_edition_date"


def test_unknown_date_evidence_does_not_complete_year():
    raw = {"events": [event(event_date=None)]}
    raw["events"][0]["date_evidence"]["source_id"] = "S99"
    data, _ = validate_timeline(raw, SOURCES, COVERAGE)
    assert not data["events"]
    assert data["undated_events"][0]["date_anchor"] is None


def test_conflicting_edition_metadata_does_not_complete_year():
    text = "Mercoledì 21 ottobre si terrà l'incontro del Comune di Roma sul piano dei trasporti."
    source = replace(SOURCES[0], text=text)
    coverage = {"files": [dict(pdf="a.pdf", date="2026-10-17"), dict(pdf="a.pdf", date="2027-10-17")]}
    data, _ = validate_timeline({"events": [event(source, None)]}, [source], coverage)
    assert not data["events"]
    assert data["undated_events"][0]["date_reason"] == "missing_edition_date"


def test_only_timeline_cache_changes_with_date_strategy(setup_knowledge, monkeypatch):
    root, catalog, client, _, _ = setup_knowledge
    for kind in ("map", "timeline"):
        generate_knowledge(kind, "Trasporti", authorize_external=True, root=root, client=client)
    monkeypatch.setattr("edicola.knowledge.TIMELINE_VERSION", "timeline-dates-next")
    assert generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    assert not generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    assert client.models.generate_content.call_count == 3
    config = client.models.generate_content.call_args.kwargs["config"]
    assert "conserva SEMPRE date_evidence" in config.system_instruction
    catalog.coverage["files"][0]["date"] = "2026-10-17"
    assert not generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    prompt = json.loads(client.models.generate_content.call_args.kwargs["contents"])
    assert prompt["editions"][0]["date"] == "2026-10-17"


def test_map_strategy_does_not_invalidate_timeline_cache(setup_knowledge, monkeypatch):
    root, _, client, _, _ = setup_knowledge
    for kind in ("timeline", "map"):
        generate_knowledge(kind, "Trasporti", authorize_external=True, root=root, client=client)
    monkeypatch.setattr("edicola.knowledge.MAP_VERSION", "concept-map-next")
    assert generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    result = generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client)
    assert not result.from_cache
    assert client.models.generate_content.call_count == 3
    assert result.data["edges"][0]["evidence"]
    config = client.models.generate_content.call_args.kwargs["config"]
    assert "N1, N2" in config.system_instruction
    assert "massimo 10" in config.system_instruction


def test_map_rejection_logs_only_reason_counts(setup_knowledge, caplog):
    root, _, client, _, _ = setup_knowledge
    raw = map_data()
    raw["edges"] = [raw["edges"][0]]
    raw["edges"][0]["label"]["text"] = "causa"
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(raw),
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    with caplog.at_level("INFO", logger="edicola.knowledge"):
        result = generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client)
    assert not result.data["edges"]
    assert result.diagnostics["edge_rejections"] == {"relation_not_explicit": 1}
    assert "relation_not_explicit" in caplog.text
    assert "private-key" not in caplog.text
    assert TEXT1 not in caplog.text and TEXT2 not in caplog.text


def test_map_retrieves_adjacent_indexed_context_without_extra_search_or_reembedding(setup_knowledge):
    from test_map_context import adjacent_case
    raw, sources, _, chunks = adjacent_case()
    root, catalog, client, _, search = setup_knowledge
    catalog.chunks = chunks
    catalog.coverage = {"indexed": 2, "total": 2, "partial": False, "warnings": [],
        "files": [{"pdf": "giornale.pdf", "publication": "Testata", "date": "2026-10-17", "indexed": 2, "total": 2}]}
    search.return_value = [{"id": chunks[0].id, "distance": 0.2}]
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(raw),
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    first = generate_knowledge("map", "Finanziamenti a Chieti", authorize_external=True, root=root, client=client)
    assert first.diagnostics["adjacent_chunks_used"] == 1
    assert first.diagnostics["accepted_edges"] == 1
    assert first.diagnostics["adjacent_edges"] == 1
    prompt = json.loads(client.models.generate_content.call_args.kwargs["contents"])
    assert [s["text"] for s in prompt["sources"]] == [s.text for s in sources]
    assert prompt["adjacent_sources"] == [["S1", "S2"]]
    second = generate_knowledge("map", "Finanziamenti a Chieti", authorize_external=True, root=root, client=client)
    assert second.from_cache and second.data == first.data
    client.models.generate_content.assert_called_once()
    search.assert_called_once()


def test_map_budget_keeps_original_chunks_whole(setup_knowledge):
    from test_map_context import adjacent_case
    raw, _, _, chunks = adjacent_case()
    root, catalog, client, _, search = setup_knowledge
    large = IndexChunk("large", "Un passaggio molto lungo del giornale. " * 500,
                       {**chunks[0].metadata, "pdf_sha256": "b" * 64, "filename": "altro.pdf"})
    catalog.chunks = chunks + [large]
    search.return_value = [{"id": chunks[0].id, "distance": 0.2}, {"id": large.id, "distance": 0.3}]
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(raw),
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    result = generate_knowledge("map", "Finanziamenti", authorize_external=True, root=root, client=client)
    assert result.diagnostics["chunks_dropped_for_budget"] == 1
    assert result.diagnostics["adjacent_edges"] == 1
    request = client.models.generate_content.call_args.kwargs
    assert len(request["contents"]) + len(request["config"].system_instruction) <= 12000
    assert [s.text for s in result.sources] == [c.text for c in chunks]


def test_neighbor_configuration_invalidates_only_map_cache(setup_knowledge, monkeypatch):
    root, _, client, _, _ = setup_knowledge
    for kind in ("timeline", "map"):
        generate_knowledge(kind, "Trasporti", authorize_external=True, root=root, client=client)
    monkeypatch.setenv("MAP_ADJACENT_CHUNKS", "0")
    assert generate_knowledge("timeline", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    assert not generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    assert client.models.generate_content.call_count == 3
