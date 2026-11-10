"""Recovery sicuro per indisponibilità del database personale.

Nessuna richiesta esterna o salvataggio implicito: si passa a guest solo
cliccando il pulsante di logout. Le chat già salvate non vengono modificate.
"""
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from edicola.personal_store import PersonalStoreError
from test_chat_ui import script
from test_personal_accounts import auth


def test_account_database_failure_explains_issue_and_offers_explicit_guest(auth, tmp_path):
    with patch("edicola.chat_sessions.store", side_effect=PersonalStoreError("db-offline")), patch(
        "edicola.account_recovery.identity.logout"
    ) as logout, patch("edicola.rag.ask_question") as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        assert not app.exception
        assert app.chat_input[0].disabled
        assert any("database personale" in e.message.lower() for e in app.error)
        assert app.button(key="chat_guest_recovery").label == "Continua senza account"
        assert "rag_pending" not in app.session_state
        ask.assert_not_called()
        logout.assert_not_called()
        app.button(key="chat_guest_recovery").click().run()
        logout.assert_called_once()
        ask.assert_not_called()


def test_guest_has_no_account_recovery_and_can_chat_without_db(tmp_path):
    with patch("edicola.rag.ask_question") as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        assert not app.exception and not app.chat_input[0].disabled
        assert all(button.key != "chat_guest_recovery" for button in app.button)
        ask.assert_not_called()


def test_partial_index_notice_is_not_rendered_in_chat(tmp_path):
    with patch("edicola.editorial_selection.read_catalog", side_effect=AssertionError("non richiesto nella chat")):
        app = AppTest.from_string(script(tmp_path)).run()
    assert not app.exception
    assert all("Le risposte coprono solo una parte" not in c.value for c in app.caption)
