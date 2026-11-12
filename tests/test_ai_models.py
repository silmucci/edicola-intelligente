"""Gestione comune dei modelli Gemini: prove offline, nessuna API reale."""

from unittest.mock import Mock

import pytest
from google.genai import errors

from edicola.ai_models import alternative_models, product_model, run_text_request


def api_error(code):
    klass = errors.ServerError if code >= 500 else errors.ClientError
    return klass(code, {"error": {"code": code, "message": "private-key"}})


def test_model_selection_and_no_duplicate_or_disabled_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_CHAT_MODEL", "gemini-3.6-flash")
    monkeypatch.setenv("GEMINI_CHAT_FALLBACK_MODELS",
                       "gemini-3.6-flash, gemini-3.1-flash-lite, gemini-3.8-flash, gemini-3.1-flash-lite")
    assert product_model("CHAT", "gemini-3.5-flash-lite", root=tmp_path) == "gemini-3.6-flash"
    assert alternative_models("CHAT", "gemini-3.6-flash", root=tmp_path) == (
        "gemini-3.1-flash-lite", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_CHAT_FALLBACK_MODELS", "off")
    assert alternative_models("CHAT", "gemini-3.6-flash", root=tmp_path) == ()


def test_unconfigured_product_keeps_old_primary_and_secondary(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_MAP_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MAP_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("GEMINI_RAG_FALLBACK_MODEL", "gemini-3.8-flash")
    assert product_model("MAP", "configured", root=tmp_path) == "configured"
    assert alternative_models("MAP", "configured", root=tmp_path) == ("gemini-3.8-flash",)


def test_visual_and_briefing_can_use_stable_free_fallback_without_changing_chat(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_RAG_FALLBACK_MODEL", raising=False)
    for product in ("MAP", "TIMELINE", "BRIEFING"):
        monkeypatch.delenv(f"GEMINI_{product}_FALLBACK_MODELS", raising=False)
        assert alternative_models(product, "gemini-3.5-flash-lite", root=tmp_path,
                                  default_fallback="gemini-3.1-flash-lite") == ("gemini-3.1-flash-lite",)
    assert alternative_models("CHAT", "gemini-3.5-flash-lite", root=tmp_path) == ("gemini-3.8-flash",)
    monkeypatch.setenv("GEMINI_MAP_FALLBACK_MODELS", "off")
    assert alternative_models("MAP", "primary", root=tmp_path,
                              default_fallback="gemini-3.1-flash-lite") == ()
    monkeypatch.setenv("GEMINI_RAG_FALLBACK_MODEL", "another-verified-model")
    assert alternative_models("TIMELINE", "primary", root=tmp_path,
                              default_fallback="gemini-3.1-flash-lite") == ("another-verified-model",)


def test_quota_switches_once_per_model_with_unchanged_payload(caplog):
    seen = []
    def send(model):
        seen.append((model, "same-source-schema-and-prompt"))
        if model == "primary":
            raise api_error(429)
        return {"response": "valid"}
    with caplog.at_level("WARNING", logger="edicola"):
        result = run_text_request(send, "primary", fallbacks=("secondary",),
                                  quota_fallback=True, sleep=Mock(), phase="test_router")
    assert result == {"response": "valid"}
    assert seen == [("primary", "same-source-schema-and-prompt"),
                    ("secondary", "same-source-schema-and-prompt")]
    assert "reason=429" in caplog.text
    assert "private-key" not in caplog.text


def test_repeated_server_error_uses_bounded_fallback():
    seen = []
    def send(model):
        seen.append(model)
        if model == "primary":
            raise api_error(503)
        return "ok"
    assert run_text_request(send, "primary", fallbacks=("secondary",),
                            quota_fallback=True, sleep=Mock()) == "ok"
    assert seen == ["primary", "primary", "secondary"]


def test_three_models_are_bounded_and_unique():
    seen = []
    def send(model):
        seen.append(model)
        raise api_error(503)
    with pytest.raises(errors.APIError):
        run_text_request(send, "first", fallbacks=("first", "second", "third", "fourth"),
                         quota_fallback=True, sleep=Mock())
    assert seen == ["first", "first", "second", "second", "third", "third"]


@pytest.mark.parametrize("code", [400, 403, 404])
def test_permissions_invalid_schema_and_missing_model_never_rotate(code):
    seen = []
    def send(model):
        seen.append(model)
        raise api_error(code)
    with pytest.raises(errors.APIError):
        run_text_request(send, "primary", fallbacks=("secondary",),
                         quota_fallback=True, sleep=Mock())
    assert seen == ["primary"]


def test_quota_exhaustion_does_not_retry_same_model_or_expose_payload():
    seen = []
    def send(model):
        seen.append(model)
        raise api_error(429)
    with pytest.raises(errors.APIError):
        run_text_request(send, "primary", fallbacks=("secondary",),
                         quota_fallback=True, sleep=Mock())
    assert seen == ["primary", "secondary"]


def test_legacy_without_fallback_preserves_retry_bound():
    send = Mock(side_effect=api_error(503))
    sleeper = Mock()
    with pytest.raises(errors.APIError):
        run_text_request(send, "primary", sleep=sleeper)
    assert send.call_count == 3
    assert sleeper.call_count == 2
