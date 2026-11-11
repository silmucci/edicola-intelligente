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
                                     client=client, authorize_external=True)
    assert len(result["records"]) == 4
    assert all(r["status"] == "judged" for r in result["records"])
    assert len([r for r in rows if r["value"] == 3]) == sum(map(len, AUTOMATIC.values()))
    assert next(r for r in rows if r["metric"] == "llm_judge:podcast:audio_quality")["value"] is None
    assert client.models.generate_content.call_count == 4


def test_judge_rejects_missing_permission_and_fabricated_quotes(tmp_path):
    data = manifest()
    with pytest.raises(ValueError, match="autorizzare"):
        evaluate_products(data, root=tmp_path, model="mock", client=Mock())
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
