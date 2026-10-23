"""UI audio: azione esplicita, consenso, cache e nessuna rigenerazione editoriale."""

from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from edicola.podcast import generate_podcast
from edicola.podcast_text import PodcastError
from test_podcast import fake_client, podcast_archive


def ui_script(root):
    return f"from pathlib import Path\nfrom edicola.podcast_ui import render_podcast_ui\nrender_podcast_ui(Path({str(root)!r}))"


def test_ui_never_generates_on_start_or_rerun_and_reuses_wav(podcast_archive):
    client = fake_client()
    with patch("edicola.podcast_ui.generate_podcast", side_effect=lambda key, **kw: generate_podcast(key, client=client, **kw)) as generate, patch(
        "google.genai.Client", side_effect=AssertionError("API reali vietate")
    ), patch("edicola.editorial.generate_product", side_effect=AssertionError("Rigenerazione editoriale vietata")), patch(
        "edicola.search.semantic_search", side_effect=AssertionError("Retrieval non richiesto")):
        app = AppTest.from_string(ui_script(podcast_archive), default_timeout=10).run()
        assert not app.exception
        generate.assert_not_called()
        assert any("4,2 milioni" in text.value for text in app.text)
        assert any("giornale.pdf — pagina 3" in text.value for text in app.text)
        app.button[0].click().run()
        generate.assert_not_called()
        assert app.warning
        app.checkbox[0].check()
        app.button[0].click().run()
        assert not app.exception
        assert len(app.get("audio")) == 1 and len(app.get("download_button")) == 1
        assert client.models.generate_content.call_count == 1
        app.run()
        assert generate.call_count == 1
        app.button[0].click().run()
        assert generate.call_count == 2 and client.models.generate_content.call_count == 1
        assert any("Audio già disponibile" in item.value for item in app.caption)
        app.selectbox[1].select("Aoede").run()
        assert len(app.get("audio")) == 0
        assert generate.call_count == 2
        app.button[0].click().run()
        assert client.models.generate_content.call_count == 2
        assert client.models.generate_content.call_args.kwargs["config"].speech_config.voice_config.voice == "Aoede"


def test_ui_api_error_does_not_retry_on_rerun(podcast_archive):
    with patch("edicola.podcast_ui.generate_podcast", side_effect=PodcastError("Gemini TTS HTTP 429. Quota esaurita.")) as generate, patch(
        "google.genai.Client", side_effect=AssertionError("API reali vietate")):
        app = AppTest.from_string(ui_script(podcast_archive), default_timeout=10).run()
        app.checkbox[0].check()
        app.button[0].click().run()
        assert not app.exception and "429" in app.error[0].value
        assert not app.get("audio")
        app.run()
        generate.assert_called_once()


def test_empty_editorial_cache_never_calls_api_or_creates_files(tmp_path):
    with patch("google.genai.Client", side_effect=AssertionError("API reali vietate")), patch(
        "edicola.podcast_ui.generate_podcast", side_effect=AssertionError("Audio automatico vietato")):
        app = AppTest.from_string(ui_script(tmp_path), default_timeout=10).run()
        assert not app.exception and not app.button
        assert any("biblioteca audio è ancora vuota" in info.value for info in app.info)
        assert not list(tmp_path.iterdir())


def test_voice_default_is_loaded_locally_from_dotenv_without_api(podcast_archive, monkeypatch):
    monkeypatch.delenv("GEMINI_TTS_VOICE")
    (podcast_archive / ".env").write_text("GEMINI_TTS_VOICE=Aoede\n", encoding="utf-8")
    with patch("google.genai.Client", side_effect=AssertionError("API reali vietate")):
        app = AppTest.from_string(ui_script(podcast_archive), default_timeout=10).run()
    assert not app.exception and app.selectbox[1].value == "Aoede"
