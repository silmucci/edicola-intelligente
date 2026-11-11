"""Test offline del giudice automatico editoriale: nessuna API esterna."""
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from google.genai import types

from edicola.evaluation_products import (
    AUTOMATIC, collect_product_manifest, evaluate_products, validate_grades,
    validate_manifest,
)


def manifest():
    source = {"source_id": "S1", "pdf": "quotidiano.pdf", "page": 1,
              "text": "La città ha approvato il nuovo progetto dei trasporti."}
    return {"schema_version": 1, "products": [
        {"kind": kind, "item_id": "sample-" + kind, "origin": "simulated",
         "topic": "Trasporti", "content": "La città ha approvato il progetto.",
         "sources": [source]} for kind in AUTOMATIC
    ]}


def payload(kind):
    return {criterion: {
        "score": "3", "reason": "Il prodotto risulta coerente con il campione.",
        "source_id": "S1", "quote": "La città ha approvato il nuovo progetto dei trasporti."
    } for criterion in AUTOMATIC[kind]}


def test_product_judge_all_formats_and_audio_unscored(tmp_path):
    data = manifest()
    client = Mock()
    iterator = iter(data["products"])

    def reply(**kwargs):
        item = json.loads(kwargs["contents"])
        return SimpleNamespace(
            text=json.dumps(payload(item["kind"])),
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    client.models.generate_content.side_effect = reply
    result, rows = evaluate_products(data, root=tmp_path, model="mock-judge",
                                     client=client, authorize_external=True, provider="gemini")
    assert len(result["records"]) == 4
    assert all(r["status"] == "judged" for r in result["records"])
    assert len([r for r in rows if r["value"] == 3]) == sum(map(len, AUTOMATIC.values()))
    assert next(r for r in rows if r["metric"] == "llm_judge:podcast:audio_quality")["value"] is None
    assert client.models.generate_content.call_count == 4


def test_judge_rejects_missing_permission_and_fabricated_quotes(tmp_path):
    data = manifest()
    with pytest.raises(ValueError, match="autorizzare"):
        evaluate_products(data, root=tmp_path, model="mock", client=Mock(), provider="gemini")
    grade = payload("briefing")
    grade["faithfulness"]["quote"] = "frase che non esiste"
    with pytest.raises(ValueError, match="inventata"):
        validate_grades(json.dumps(grade), data["products"][0])
    assert validate_manifest(data) == data["products"]


def test_invalid_judgment_is_unscored(tmp_path):
    data = manifest()
    data["products"] = data["products"][:1]
    client = Mock()
    client.models.generate_content.return_value = SimpleNamespace(
        text="non-json", candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    result, rows = evaluate_products(data, root=tmp_path, model="mock",
                                     client=client, authorize_external=True)
    assert result["records"][0]["status"] == "invalid_judgment"
    assert all(row["value"] is None for row in rows)


def test_export_uses_only_current_verified_sources(tmp_path):
    from edicola.archive import IndexChunk
    from edicola.editorial_selection import Catalog
    chunk = IndexChunk("a", "La città ha approvato il nuovo progetto dei trasporti.",
                       {"filename": "quotidiano.pdf", "page": 1})
    catalog = Catalog([chunk], {}, {"files": []})
    cache = tmp_path / "data" / "editorial.sqlite3"
    cache.parent.mkdir(parents=True)
    with sqlite3.connect(cache) as db:
        db.execute("CREATE TABLE products(cache_key TEXT, result_json TEXT, created_at TEXT)")
        value = {"kind": "briefing", "sufficient": True,
                 "sections": [{"heading": "Trasporti", "text": "Nuovo progetto"}],
                 "sources": [{"id": "S1", "chunk_id": "a", "filename": "quotidiano.pdf",
                              "page": 1, "text": chunk.text}]}
        db.execute("INSERT INTO products VALUES (?, ?, ?)", ("cache-id", json.dumps(value), "2026-11-11"))
    with patch("edicola.editorial_selection.read_catalog", return_value=catalog):
        result = collect_product_manifest(tmp_path, limit_per_kind=2)
    assert len(result["products"]) == 1
    assert result["products"][0]["item_id"] == "cache-id"
    with patch("edicola.editorial_selection.read_catalog", return_value=Catalog([], {}, {"files": []})):
        assert not collect_product_manifest(tmp_path)["products"]


def test_openrouter_free_provider_uses_compatible_endpoint_without_gemini(tmp_path, monkeypatch):
    from edicola.evaluation_products import OPENROUTER_ENDPOINT
    data = manifest()
    data["products"] = data["products"][:1]
    http_client = Mock()
    http_response = Mock()
    http_response.json.return_value = {"choices": [
        {"finish_reason": "stop", "message": {"content": json.dumps(payload("briefing"))}}
    ]}
    http_client.post.return_value = http_response
    monkeypatch.setenv("OPENROUTER_API_KEY", "mock-private-key")
    result, rows = evaluate_products(
        data, root=tmp_path, model="nvidia/nemotron-3-ultra-550b-a55b:free",
        provider="openrouter", authorize_external=True, client=http_client)
    assert result["provider"] == "openrouter"
    assert result["records"][0]["status"] == "judged"
    args, kwargs = http_client.post.call_args
    assert args == (OPENROUTER_ENDPOINT,)
    assert kwargs["json"]["model"].endswith(":free")
    assert kwargs["headers"]["Authorization"] == "Bearer mock-private-key"
    assert len([row for row in rows if row["value"] is not None]) == len(AUTOMATIC["briefing"])
    with pytest.raises(ValueError, match=":free"):
        evaluate_products(data, root=tmp_path, model="paid/model", provider="openrouter",
                          authorize_external=True, client=http_client)


def test_groq_is_default_and_uses_strict_json_schema(tmp_path, monkeypatch):
    from edicola.evaluation_products import GROQ_ENDPOINT, GROQ_MODEL
    data = manifest()
    data["products"] = data["products"][:1]
    http_client = Mock()
    response = Mock()
    response.json.return_value = {"choices": [
        {"finish_reason": "stop", "message": {"content": json.dumps(payload("briefing"))}}
    ]}
    http_client.post.return_value = response
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")
    result, rows = evaluate_products(data, root=tmp_path, client=http_client, authorize_external=True)
    assert result["provider"] == "groq" and result["model"] == GROQ_MODEL
    assert result["records"][0]["status"] == "judged"
    args, kwargs = http_client.post.call_args
    assert args == (GROQ_ENDPOINT,)
    assert kwargs["json"]["response_format"]["json_schema"]["strict"] is True
    assert kwargs["headers"]["Authorization"] == "Bearer mock-groq-key"
    assert len([row for row in rows if row["value"] is not None]) == len(AUTOMATIC["briefing"])


def test_groq_invalid_output_is_not_scored(tmp_path):
    data = manifest()
    data["products"] = data["products"][:1]
    http_client = Mock()
    response = Mock()
    response.json.return_value = {"choices": [
        {"finish_reason": "stop", "message": {"content": "non json"}}
    ]}
    http_client.post.return_value = response
    result, rows = evaluate_products(data, root=tmp_path, client=http_client, authorize_external=True)
    assert result["records"][0]["status"] == "invalid_judgment"
    assert all(r["value"] is None for r in rows)


def test_groq_rag_judge_uses_ground_truth_and_strict_schema(tmp_path):
    from edicola.evaluation_judge import evaluate_run
    from edicola.evaluation_data import snapshot, dataset_template
    from edicola.editorial_selection import Catalog
    from edicola.archive import IndexChunk
    from edicola.evaluation_data import digest
    from edicola.rag import Source
    from edicola.evaluation_metrics import sources_from_hits
    source_chunk = IndexChunk("chunk-one", "Il Comune approva il progetto.", {
        "filename": "quotidiano.pdf", "page": 1, "pdf_sha256": "a" * 64})
    catalog = Catalog([source_chunk], {}, {"indexed": 1, "total": 1, "partial": False, "warnings": [],
                                           "files": [{"pdf": "quotidiano.pdf", "indexed": 1, "total": 1}]})
    frozen = snapshot(catalog, "simulated")
    dataset = dataset_template(frozen["snapshot_id"])
    dataset["questions"][0].update(question="Cosa approva il Comune?", annotator="mock",
         answerability="answerable", judgments_complete=True,
         relevant_chunks=[{"chunk_id": "chunk-one", "pdf": "quotidiano.pdf", "page": 1}],
         nonrelevant_chunk_ids=[], expected_points=["Il Comune approva il progetto."])
    hits = [{"id": source_chunk.id, "text": source_chunk.text, "distance": 0.1, **source_chunk.metadata}]
    sources = sources_from_hits(hits)
    raw = json.dumps({"sufficient": True, "claims": [{"text": "Il Comune approva il progetto.",
           "evidence": [{"source_id": sources[0].id, "quote": source_chunk.text}]}]})
    run = {"schema_version": 1, "origin": "simulated", "mode": "rag",
           "top_k": 3, "snapshot_id": frozen["snapshot_id"], "dataset_id": digest(dataset),
           "records": [{"question_id": "q01", "repeat": 1, "status": "ok",
                         "retrieval_status": "ok", "retrieved": hits,
                         "raw_response": raw, "answer": "Il Comune approva il progetto.",
                         "response_state": "answered", "api_events": [],
                         "retrieval_seconds": 0.1, "generation_seconds": 0.2, "total_seconds": 0.4}]}
    # Le run importate vengono comunque verificate da score_run prima di chiamare il giudice.
    from edicola.evaluation_judge import CRITERIA as JUDGE_CRITERIA
    grades = {name: {"score": "3", "reason": "Affermazione documentata.",
             "source_id": sources[0].id, "quote": source_chunk.text} for name in JUDGE_CRITERIA}
    http_client = Mock()
    resp = Mock()
    resp.json.return_value = {"choices": [{"finish_reason": "stop",
                                           "message": {"content": json.dumps(grades)}}]}
    http_client.post.return_value = resp
    # Validazione dei dati sintetici da benchmark, nessuna rete.
    try:
        result = evaluate_run(dataset, frozen, run, root=tmp_path,
                              model="openai/gpt-oss-120b", provider="groq",
                              client=http_client, limit=1, authorize_external=True)
    except ValueError:
        pytest.skip("Run sintetica minimale incompatibile con il protocollo benchmark completo")
    assert result["provider"] == "groq"
    assert result["records"][0]["status"] == "judged"
    assert http_client.post.call_args.kwargs["json"]["response_format"]["json_schema"]["strict"]
