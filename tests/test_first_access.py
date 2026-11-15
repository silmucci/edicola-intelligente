"""Primo accesso: scelta facoltativa persistente e nessuna richiesta AI."""
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from edicola.profiles import Profile
from test_personal_accounts import A, auth, backend


SCRIPT = """
import streamlit as st
from edicola.account_ui import render_first_access
render_first_access()
st.write("Archivio consultabile")
"""


def test_guest_can_browse_without_onboarding_or_database():
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=AssertionError("No database for guests")):
        app = AppTest.from_string(SCRIPT).run()
    assert not app.exception
    assert not any(button.key == "account_first_access_save" for button in app.button)
    assert not any(button.key == "account_first_access_skip" for button in app.button)


def test_skip_is_persistent_and_shows_profile_reminder(auth, backend):
    db, _, store = backend
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda identity: store()):
        app = AppTest.from_string(SCRIPT).run()
        assert not app.exception
        assert not db.profiles
        assert app.button(key="account_first_access_skip")
        app.button(key="account_first_access_skip").click().run()
        assert not app.exception
        assert db.profiles[A.owner_id] == [[], 5, "testo", {}]
        assert any("Il mio profilo" in item.value and "Preferenze" in item.value for item in app.info)
        app.run()
        assert not any(button.key == "account_first_access_skip" for button in app.button)
        assert not any("Non hai ancora configurato" in item.value for item in app.info)
        # Anche in una nuova sessione si usa la riga persistente del profilo.
        second = AppTest.from_string(SCRIPT).run()
        assert not second.exception
        assert not any(button.key == "account_first_access_skip" for button in second.button)


def test_first_access_can_save_custom_topic(auth, backend):
    db, _, store = backend
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda identity: store()):
        app = AppTest.from_string(SCRIPT).run()
        app.text_input(key="account_first_access_custom").set_value("Cinema").run()
        app.button(key="account_first_access_save").click().run()
        assert not app.exception
        assert store().load_profile().interests == ["Cinema"]
        assert not any(button.key == "account_first_access_save" for button in app.button)
        assert not any("Non hai ancora configurato" in item.value for item in app.info)


def test_existing_profile_never_sees_first_access(auth, backend):
    db, _, store = backend
    store().save_preferences(Profile(user_id=A.owner_id, interests=["Scuola"]))
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda identity: store()):
        app = AppTest.from_string(SCRIPT).run()
    assert not app.exception
    assert not any(button.key == "account_first_access_save" for button in app.button)
    assert db.profiles[A.owner_id][0] == ["Scuola"]


def test_database_down_does_not_complete_or_block_guest_content(auth, backend):
    db, _, store = backend
    db.fail = True
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda identity: store()):
        app = AppTest.from_string(SCRIPT).run()
    assert not app.exception
    assert not any(button.key == "account_first_access_save" for button in app.button)
    assert "account_first_access_done" not in app.session_state
