"""Nessuna richiesta reale: il client ufficiale viene sostituito con mock."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from google.genai import errors

from edicola.embeddings import (
    DIMENSIONS, MODEL, EmbeddingError, GeminiEmbedder, document_prompt,
    question_prompt, validate_vector,
)


def response(vector=None):
    return SimpleNamespace(embeddings=[SimpleNamespace(values=vector or [1.0] + [0.0] * 767)])


def test_official_sdk_configuration_and_exact_prompts():
    client = Mock()
    client.models.embed_content.return_value = response()
    with patch("edicola.embeddings.genai.Client", return_value=client) as constructor:
        embedder = GeminiEmbedder("test-secret")
        options = constructor.call_args.kwargs["http_options"]
        assert options.timeout == 30_000
        assert options.retry_options.attempts == 1
        vector = embedder.embed(document_prompt("Giornale", "Testo."))
    assert len(vector) == DIMENSIONS
    call = client.models.embed_content.call_args.kwargs
    assert call["model"] == MODEL
    assert call["contents"] == "title: Giornale | text: Testo."
    assert call["config"].output_dimensionality == 768
    assert call["config"].task_type is None
    assert question_prompt("Cosa è successo?") == "task: question answering | query: Cosa è successo?"
    embedder.close()
    client.close.assert_called_once()


@pytest.mark.parametrize("failure", [
    errors.ClientError(429, {"error": {"code": 429, "message": "private-key"}}),
    errors.ServerError(503, {"error": {"code": 503, "message": "private-key"}}),
    httpx.ConnectError("private-key"),
    httpx.ReadTimeout("private-key"),
])
def test_transient_errors_retry_then_succeed(failure):
    client, sleep = Mock(), Mock()
    client.models.embed_content.side_effect = [failure, response()]
    embedder = GeminiEmbedder("test-secret", client=client, sleep=sleep)
    assert len(embedder.embed("test")) == 768
    assert client.models.embed_content.call_count == 2
    sleep.assert_called_once_with(1)


def test_retry_limit_and_error_redaction():
    client, sleep = Mock(), Mock()
    client.models.embed_content.side_effect = httpx.ConnectError("private-key")
    with pytest.raises(EmbeddingError) as caught:
        GeminiEmbedder("test-secret", client=client, sleep=sleep).embed("test")
    assert "private-key" not in str(caught.value)
    assert client.models.embed_content.call_count == 3
    assert sleep.call_count == 2


def test_permanent_errors_are_not_retried():
    client = Mock()
    client.models.embed_content.side_effect = errors.ClientError(
        403, {"error": {"code": 403, "message": "private-key"}}
    )
    with pytest.raises(EmbeddingError, match="403"):
        GeminiEmbedder("test-secret", client=client).embed("test")
    assert client.models.embed_content.call_count == 1


@pytest.mark.parametrize("vector", [[], [1.0] * 767, [float("nan")] * 768, [float("inf")] * 768, [0.0] * 768, None])
def test_invalid_vectors_rejected(vector):
    with pytest.raises(EmbeddingError):
        validate_vector(vector)


def test_missing_key_does_not_construct_client():
    with patch("edicola.embeddings.genai.Client") as constructor:
        with pytest.raises(EmbeddingError, match="GEMINI_API_KEY"):
            GeminiEmbedder("")
        constructor.assert_not_called()


def test_missing_embeddings_does_not_retry():
    client = Mock()
    client.models.embed_content.return_value = SimpleNamespace(embeddings=[])
    with pytest.raises(EmbeddingError):
        GeminiEmbedder("test-secret", client=client).embed("test")
    assert client.models.embed_content.call_count == 1


def test_embedding_error_retains_only_http_code():
    client = Mock()
    client.models.embed_content.side_effect = errors.ServerError(503, {"error": {"code": 503, "message": "private-key"}})
    with pytest.raises(EmbeddingError) as caught:
        GeminiEmbedder("test-secret", client=client, sleep=Mock()).embed("private-question")
    assert caught.value.http_status == 503
    assert client.models.embed_content.call_count == 3
    assert "private-key" not in str(caught.value)
