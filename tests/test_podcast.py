"""Gemini TTS interamente simulato, cache SQLite in sola lettura e WAV reali di test."""

import base64
import io
import json
import wave
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from google import genai
from google.genai import errors, types

from edicola.editorial import EditorialResult, cache_write
from edicola.podcast import MODEL, generate_podcast, wav_duration
from edicola.podcast_text import CachedProduct, PodcastError, list_products, prepare_script, spoken_text
from edicola.rag import Source


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 2400)
    return output.getvalue()


def tts_response(data=None, mime="audio/wav", reason=types.FinishReason.STOP):
    return types.GenerateContentResponse(candidates=[types.Candidate(finish_reason=reason,
        content=types.Content(parts=[types.Part(inline_data=types.Blob(data=data if data is not None else wav_bytes(), mime_type=mime))]))])


def editorial_product():
    return EditorialResult("briefing", "**Opere pubbliche** [S1]", [
        {"heading": "Nuovi fondi [S1]", "text": "Il Comune ha stanziato 4,2 milioni di euro nel 2026. [S1]"},
        {"heading": "Tempi previsti [S2]", "text": "L'inizio dei lavori è previsto per il 21 ottobre 2026. [S2]"}],
        [Source("S1", "chunk-1", "giornale.pdf", 3, "Il Comune ha stanziato 4,2 milioni di euro nel 2026.", 0.2),
         Source("S2", "chunk-2", "altro.pdf", 5, "L'inizio dei lavori è previsto per il 21 ottobre 2026.", 0.3)],
        ["S1", "S2"], {"partial": True, "indexed": 360, "total": 597, "files": []}, True)


@pytest.fixture
def podcast_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_TTS_MODEL", MODEL)
    monkeypatch.setenv("GEMINI_TTS_VOICE", "Kore")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-private-key")
    cache_write(tmp_path / "data/editorial.sqlite3", "product-1", editorial_product())
    return tmp_path


def fake_client():
    client = Mock()
    client.models.generate_content.return_value = tts_response()
    return client


def test_script_removes_technical_formatting_without_changing_numbers():
    text = "## **Fondi** [S1]\n2026. Importo 1.250.000,50 euro e incremento 2,5%.\n-  4,2 milioni.\n+ €5 milioni.\nCalcolo: 2 * 3 * 4. Fonte: giornale.pdf. [S1, S2]"
    clean = spoken_text(text, ["giornale.pdf"])
    assert "[S" not in clean and ".pdf" not in clean and "**" not in clean and "##" not in clean
    for value in ("2026.", "1.250.000,50", "2,5%", "- 4,2 milioni", "+ €5 milioni", "2 * 3 * 4"):
        assert value in clean


def test_script_preserves_future_tense_and_sources(podcast_archive):
    script = prepare_script(list_products(podcast_archive)[0])
    assert "è previsto per il 21 ottobre 2026" in script.text
    assert "4,2 milioni" in script.text
    assert script.sources == [
        {"id": "S1", "filename": "giornale.pdf", "page": 3, "chunk_id": "chunk-1"},
        {"id": "S2", "filename": "altro.pdf", "page": 5, "chunk_id": "chunk-2"}]
    assert script.coverage["partial"]


def test_script_selects_whole_sections_and_keeps_only_their_sources():
    result = editorial_product()
    result.sections[1]["text"] = ("Testo molto lungo con importi e date da non spezzare. " * 100) + "[S2]"
    script = prepare_script(CachedProduct("key", "date", result))
    assert script.excerpt and script.selected_sections == 1
    assert [s["id"] for s in script.sources] == ["S1"]
    assert "Testo molto lungo" not in script.text
    assert len(script.text.split()) <= 240 and len(script.text) <= 3500


@pytest.mark.parametrize("sections", [[], [{"heading": "", "text": ""}], [{"heading": "", "text": "[S1] giornale.pdf"}]])
def test_empty_text_prevents_api(podcast_archive, sections):
    product = editorial_product()
    product.sections = sections
    cache_write(podcast_archive / "data/editorial.sqlite3", "product-1", product)
    client = fake_client()
    with pytest.raises(PodcastError):
        generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    client.models.generate_content.assert_not_called()


def test_unknown_source_reference_is_rejected(podcast_archive):
    result = editorial_product()
    result.sections[0]["text"] += " [S99]"
    with pytest.raises(PodcastError, match="riferimenti"):
        prepare_script(CachedProduct("key", "date", result))


def test_generation_wav_cache_and_readonly_editorial_database(podcast_archive):
    client = fake_client()
    path = podcast_archive / "data/editorial.sqlite3"
    before = path.read_bytes()
    first = generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    assert not first.from_cache and first.seconds == pytest.approx(0.1)
    assert first.audio_path.read_bytes() == wav_bytes()
    assert first.script.sources[0]["page"] == 3
    with patch("edicola.podcast.genai.Client", side_effect=AssertionError("API vietate sul cache hit")):
        second = generate_podcast("product-1", root=podcast_archive, authorize_external=True)
    assert second.from_cache and second.audio_path == first.audio_path
    client.models.generate_content.assert_called_once()
    assert path.read_bytes() == before
    manifests = list((podcast_archive / "data/podcast_cache").glob("*.json"))
    saved = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert saved["script"]["sources"] == first.script.sources
    assert "fake-private-key" not in manifests[0].read_text(encoding="utf-8")
    assert not list((podcast_archive / "data/podcast_cache").glob("*.lock"))


def test_cache_changes_for_text_voice_and_model(podcast_archive, monkeypatch):
    client = fake_client()
    a = generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    b = generate_podcast("product-1", voice="Aoede", root=podcast_archive, authorize_external=True, client=client)
    monkeypatch.setenv("GEMINI_TTS_MODEL", "configured-test-tts")
    c = generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    result = editorial_product()
    result.sections[0]["text"] = "Il Comune ha stanziato 5 milioni di euro nel 2026. [S1]"
    cache_write(podcast_archive / "data/editorial.sqlite3", "product-1", result)
    d = generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    assert len({x.audio_path for x in (a, b, c, d)}) == 4
    assert client.models.generate_content.call_count == 4


def test_identical_audio_keeps_product_provenance_separate(podcast_archive):
    client = fake_client()
    first = generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    product = editorial_product()
    product.sources[0] = replace(product.sources[0], filename="edizione-diversa.pdf", page=7, chunk_id="different")
    cache_write(podcast_archive / "data/editorial.sqlite3", "product-2", product)
    second = generate_podcast("product-2", root=podcast_archive, authorize_external=True, client=client)
    assert second.audio_path == first.audio_path and second.from_cache
    assert second.script.sources[0]["filename"] == "edizione-diversa.pdf"
    assert first.script.sources[0]["filename"] == "giornale.pdf"
    assert len(list(first.audio_path.parent.glob("*.json"))) == 2
    client.models.generate_content.assert_called_once()


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 503])
def test_api_errors_do_not_retry_or_leak_data_or_cache_failure(podcast_archive, code, caplog):
    client = fake_client()
    client.models.generate_content.side_effect = errors.APIError(code, {"error": {"code": code, "message": "fake-private-key copione segreto"}})
    with caplog.at_level("INFO", logger="edicola.podcast"), pytest.raises(PodcastError, match=str(code)) as caught:
        generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    client.models.generate_content.assert_called_once()
    assert not list((podcast_archive / "data/podcast_cache").glob("*.wav"))
    assert not list((podcast_archive / "data/podcast_cache").glob("*.lock"))
    assert "fake-private-key" not in caplog.text + str(caught.value)
    assert "copione segreto" not in caplog.text + str(caught.value)
    assert "4,2 milioni" not in caplog.text


def test_network_error_is_safe(podcast_archive):
    client = fake_client()
    client.models.generate_content.side_effect = httpx.ConnectError("fake-private-key")
    with pytest.raises(PodcastError, match="Connessione"):
        generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    client.models.generate_content.assert_called_once()


@pytest.mark.parametrize("response", [tts_response(b"bad wav"), tts_response(mime="audio/mpeg"),
    tts_response(reason=types.FinishReason.MAX_TOKENS), types.GenerateContentResponse(candidates=[])])
def test_invalid_or_incomplete_audio_is_not_saved(podcast_archive, response):
    client = fake_client()
    client.models.generate_content.return_value = response
    with pytest.raises(PodcastError):
        generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    assert not list((podcast_archive / "data/podcast_cache").glob("*.wav"))


def test_raw_pcm_is_wrapped_once_and_truncated_wav_is_rejected(podcast_archive):
    client = fake_client()
    client.models.generate_content.return_value = tts_response(b"\0\0" * 2400, "audio/L16;codec=pcm;rate=24000")
    result = generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    assert result.audio_path.read_bytes() == wav_bytes()
    with pytest.raises(PodcastError):
        wav_duration(wav_bytes()[:-20])


def test_authorization_missing_product_and_invalid_voice_prevent_api(podcast_archive):
    client = fake_client()
    for kwargs in ({}, {"authorize_external": True, "voice": "unverified-voice"}):
        with pytest.raises(PodcastError):
            generate_podcast("product-1", root=podcast_archive, client=client, **kwargs)
    with pytest.raises(PodcastError):
        generate_podcast("missing", root=podcast_archive, client=client, authorize_external=True)
    client.models.generate_content.assert_not_called()


def test_owned_client_has_timeout_no_sdk_retries_and_closes(podcast_archive):
    client = fake_client()
    with patch("edicola.podcast.genai.Client", return_value=client) as constructor:
        generate_podcast("product-1", root=podcast_archive, authorize_external=True)
    options = constructor.call_args.kwargs["http_options"]
    assert options.timeout == 60000 and options.retry_options.attempts == 1
    assert constructor.call_args.kwargs["vertexai"] is False
    client.close.assert_called_once()


def test_sdk_serializes_38_tts_metadata_and_decodes_wav_without_network(podcast_archive):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [
            {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav_bytes()).decode()}}]}}]})
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as transport:
        with genai.Client(api_key="fake-key", vertexai=False, http_options=types.HttpOptions(
            httpx_client=transport, retry_options=types.HttpRetryOptions(attempts=1))) as client:
            result = generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    assert result.audio_path.read_bytes() == wav_bytes()
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert requests[0].url.path.endswith(f"/models/{MODEL}:generateContent")
    assert payload["contents"][0]["parts"][0]["text"] == result.script.text
    assert "style" in payload["contents"][0]["parts"][0]["speechMetadata"]
    config = payload["generationConfig"]
    assert config["responseModalities"] == ["AUDIO"]
    speech = config["speechConfig"]
    assert speech.get("voiceConfig", speech.get("voice_config")) == {"voice": "Kore"}
    assert "responseSchema" not in config and "responseJsonSchema" not in config


def test_absent_cache_does_not_create_database(tmp_path):
    assert list_products(tmp_path) == []
    assert not list(tmp_path.iterdir())


def test_busy_generation_lock_prevents_duplicate_request(podcast_archive):
    client = fake_client()
    result = generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    result.audio_path.unlink()  # Solo file temporaneo di test.
    lock = result.audio_path.with_suffix(".lock")
    lock.write_text("already working")
    client.models.generate_content.reset_mock()
    with pytest.raises(PodcastError, match="già in generazione"):
        generate_podcast("product-1", root=podcast_archive, authorize_external=True, client=client)
    client.models.generate_content.assert_not_called()
    assert lock.exists()  # Non eliminare il lock di un altro processo.


def test_negative_editorial_cache_entries_are_not_podcast_inputs(podcast_archive):
    product = editorial_product()
    product.sufficient = False
    cache_write(podcast_archive / "data/editorial.sqlite3", "negative", product)
    before = (podcast_archive / "data/editorial.sqlite3").read_bytes()
    assert [p.key for p in list_products(podcast_archive)] == ["product-1"]
    assert (podcast_archive / "data/editorial.sqlite3").read_bytes() == before
