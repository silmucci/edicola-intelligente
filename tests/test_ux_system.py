"""Tema, onboarding e navigazione PDF: dati simulati e controlli nativi."""

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from test_pdf_viewer import archive, script
from test_personal_accounts import accounts_mode, auth, backend, ui
from test_editorial import make_catalog


@pytest.fixture(autouse=True)
def no_gemini():
    with patch("google.genai.Client", side_effect=AssertionError("Gemini reale vietato")):
        yield


def test_native_page_jump_preserves_original_reader_and_limits(archive):
    context, _ = archive
    app = AppTest.from_string(script(context)).run()
    app.session_state["archive_pdf"] = "a.pdf"
    app.session_state["archive_open"] = True
    app.run()
    assert not app.exception and app.number_input(key="archive_page_jump").value == 1
    app.number_input(key="archive_page_jump").set_value(2).run()
    assert not app.exception and app.session_state["archive_page"] == 2
    app.number_input(key="archive_page_jump").set_value(1).run()
    assert not app.exception and app.session_state["archive_page"] == 1


def test_invalid_page_state_shows_message_without_reading_pdf(archive):
    context, _ = archive
    app = AppTest.from_string(script(context)).run()
    app.session_state["archive_pdf"] = "a.pdf"
    app.session_state["archive_open"] = True
    app.session_state["archive_page"] = 99
    with patch("edicola.archive_ui.read_original", side_effect=AssertionError("PDF non richiesto")):
        app.run()
    assert not app.exception and any("pagina richiesta" in item.value for item in app.info)
    assert not app.number_input


def luminance(color):
    channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(weight * value for weight, value in zip((.2126, .7152, .0722), linear))


def test_local_theme_uses_supported_keys_and_readable_text_contrast():
    from streamlit import config
    theme = tomllib.loads((Path(__file__).resolve().parents[1] / ".streamlit/config.toml").read_text())["theme"]
    assert all("theme." + key in config.get_config_options() for key in theme)
    contrast = lambda a, b: (max(luminance(a), luminance(b)) + .05) / (min(luminance(a), luminance(b)) + .05)
    assert contrast(theme["textColor"], theme["backgroundColor"]) >= 4.5
    assert contrast("#ffffff", theme["primaryColor"]) >= 4.5
    assert all("http" not in str(value) for value in theme.values())


def test_first_access_opens_preferences_and_organizes_personal_area(auth, backend, tmp_path):
    _, _, factory = backend
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda _: factory()), patch(
        "edicola.account_ui.read_catalog", return_value=make_catalog()):
        app = AppTest.from_string(ui(tmp_path)).run()
    assert not app.exception
    assert app.session_state["personal_area"] == "Preferenze"
    assert [tab.label for tab in app.tabs] == ["Per te", "Raccolta", "I miei briefing", "Preferenze", "Privacy"]
    assert any("Cominciamo dai tuoi interessi" in h.value for h in app.subheader)
    assert app.button(key="personal_briefing_submit").disabled
