"""Autorizzazioni, ripresa singola e revoca: rete e credenziali reali vietate."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola import consent
from edicola.api_guard import PermissionDenied, permission_scope, require_permission
from edicola.embeddings import DIMENSIONS, GeminiEmbedder
from edicola.personal_store import PersonalStoreError
from edicola.rag import generate_response
from test_personal_accounts import A, B, accounts_mode, auth, backend, user


SCRIPT = '''
import streamlit as st
from edicola.identity import synchronize_identity
from edicola.consent_ui import authorize_action, privacy_controls
from edicola.consent import perform
synchronize_identity()
question = st.text_input("Domanda", key="rag_input")
submit = st.button("Invia", key="send")
if authorize_action("text", "test_chat", submit, question):
    perform("text", lambda: st.session_state.__setitem__("rag_calls", st.session_state.get("rag_calls", 0) + 1))
privacy_controls()
'''


def test_guest_first_consent_resumes_once_and_survives_reruns():
    app = AppTest.from_string(SCRIPT).run()
    assert not app.exception and "rag_calls" not in app.session_state
    app.text_input(key="rag_input").set_value("Un tema di prova")
    app.button(key="send").click().run()
    assert app.button(key="consent_accept") and "rag_calls" not in app.session_state
    assert not app.checkbox  # Nessuna scelta preselezionata.
    app.button(key="consent_accept").click().run()
    assert not app.exception and app.session_state["rag_calls"] == 1
    assert "consent_pending" not in app.session_state
    app.run()
    assert app.session_state["rag_calls"] == 1
    app.button(key="send").click().run()
    assert app.session_state["rag_calls"] == 2
    assert all(button.key != "consent_accept" for button in app.button)


def test_refusal_and_revocation_block_following_requests():
    app = AppTest.from_string(SCRIPT).run()
    app.button(key="send").click().run()
    app.button(key="consent_refuse").click().run()
    assert not app.exception and "rag_calls" not in app.session_state
    assert app.session_state["consent_choices"][("text", "text-v2")] is False
    app.button(key="send").click().run()
    app.button(key="consent_accept").click().run()
    app.button(key="profile_privacy_text_revoke").click().run()
    assert not app.exception and app.session_state["rag_calls"] == 1
    app.button(key="send").click().run()
    assert app.button(key="consent_accept") and app.session_state["rag_calls"] == 1


def test_guest_choice_not_in_new_session_and_privacy_review_never_generates():
    first = AppTest.from_string(SCRIPT).run()
    first.button(key="profile_privacy_audio_review").click().run()
    first.button(key="consent_accept").click().run()
    assert not first.exception and "rag_calls" not in first.session_state
    assert first.session_state["consent_choices"][("audio", "audio-v1")]
    second = AppTest.from_string(SCRIPT).run()
    assert "consent_choices" not in second.session_state


def test_new_treatment_version_requires_new_choice(monkeypatch):
    with patch("streamlit.session_state", {}):
        consent.choose("text", True)
        assert consent.allowed("text")
        old = consent.PURPOSES["text"]
        monkeypatch.setitem(consent.PURPOSES, "text", ("text-v3", *old[1:]))
        assert consent.decision("text") is None
        assert not consent.allowed("text")


def test_owner_scoped_persistence_export_deletion_and_no_demo_import(backend):
    db, actor, factory = backend
    assert factory().get_consent("text", "text-v2") is None
    factory().set_consent("text", "text-v2", True)
    assert factory().get_consent("text", "text-v2") is True
    assert factory().get_consent("text", "text-v3") is None
    actor[0] = B
    assert factory().get_consent("text", "text-v2") is None
    factory().set_consent("text", "text-v2", False)
    actor[0] = A
    assert factory().get_consent("text", "text-v2") is True
    exported = factory().export_data()["ai_consents"]
    assert exported[0]["granted"] and len(exported) == 1
    old = factory()
    actor[0] = B
    with pytest.raises(PersonalStoreError):
        old.set_consent("audio", "audio-v1", True)
    actor[0] = A
    factory().delete_all()
    assert not any(owner == A.owner_id for owner, _ in db.consents)
    assert (B.owner_id, "text") in db.consents


def test_authenticated_choice_restored_after_new_session_without_guest_fallback(auth, backend):
    db, actor, factory = backend
    with patch("edicola.consent.PostgresPersonalStore", side_effect=lambda _: factory()):
        first = AppTest.from_string(SCRIPT).run()
        first.button(key="send").click().run()
        first.button(key="consent_accept").click().run()
        assert not first.exception and first.session_state["rag_calls"] == 1
        second = AppTest.from_string(SCRIPT).run()
        second.button(key="send").click().run()
        assert not second.exception and second.session_state["rag_calls"] == 1
        assert "consent_choices" not in second.session_state
        actor[0] = B
        with patch("streamlit.user", user(B)):
            second.run()
            assert "rag_calls" not in second.session_state
            second.button(key="send").click().run()
            assert second.button(key="consent_accept")


def test_database_error_never_grants_or_reports_success(auth, backend):
    db, _, factory = backend
    with patch("edicola.consent.PostgresPersonalStore", side_effect=lambda _: factory()):
        app = AppTest.from_string(SCRIPT).run()
        app.button(key="send").click().run()
        db.fail_commit = True
        app.button(key="consent_accept").click().run()
    assert not app.exception and app.error and "rag_calls" not in app.session_state
    assert not db.consents and "consent_choices" not in app.session_state


def test_revocation_between_embedding_and_generation_stops_second_api():
    sdk = Mock()
    sdk.models.embed_content.return_value.embeddings = [Mock(values=[1.0] * DIMENSIONS)]
    embedder = GeminiEmbedder("simulated-key", client=sdk)
    with patch("streamlit.session_state", {}):
        consent.choose("text", True)
        def flow():
            embedder.embed("simulated query")
            consent.choose("text", False)
            generate_response(sdk, "unchanged-model", "simulated", {})
        with pytest.raises(PermissionDenied):
            consent.perform("text", flow)
    sdk.models.embed_content.assert_called_once()
    sdk.models.generate_content.assert_not_called()


def test_distinct_purposes_and_identity_change_cannot_reuse_scope():
    with permission_scope(lambda: True, "text"):
        with pytest.raises(PermissionDenied):
            require_permission("audio")
    with patch("streamlit.session_state", {}), patch("edicola.consent.actor", side_effect=["owner-a", "owner-b"]):
        with pytest.raises(PermissionDenied):
            consent.perform("text", Mock())


def test_streamlit_cannot_bypass_scope_with_authorize_flag():
    script = '''
import streamlit as st
from edicola.api_guard import require_permission, PermissionDenied
try:
    require_permission("audio")
except PermissionDenied:
    st.success("Invio bloccato")
'''
    app = AppTest.from_string(script).run()
    assert not app.exception and app.success[0].value == "Invio bloccato"


def test_migration_is_additive_private_rls_and_has_no_account_role_changes():
    sql = (Path(__file__).resolve().parents[1] / "migrations/003_ai_consents.sql").read_text()
    assert "BEGIN;" in sql and "COMMIT;" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql and "WITH CHECK" in sql
    assert "ON DELETE CASCADE" in sql and "PRIMARY KEY (owner_id, purpose)" in sql
    assert "ALTER ROLE" not in sql and "DROP TABLE" not in sql
    assert "FROM PUBLIC, anon, authenticated, edicola_app" in sql


def test_revocation_from_another_session_is_checked_before_the_next_call(auth, backend):
    _, _, factory = backend
    with patch("edicola.consent.PostgresPersonalStore", side_effect=lambda _: factory()):
        consent.choose("text", True)
        def flow():
            factory().set_consent("text", "text-v2", False)  # Altro dispositivo.
            require_permission("text")
        with pytest.raises(PermissionDenied):
            consent.perform("text", flow)


def test_changed_draft_cannot_resume_a_previous_pending_request():
    app = AppTest.from_string(SCRIPT).run()
    app.text_input(key="rag_input").set_value("Prima bozza")
    app.button(key="send").click().run()
    app.text_input(key="rag_input").set_value("Bozza diversa").run()
    assert not app.exception and "rag_calls" not in app.session_state
    assert "consent_pending" not in app.session_state


def test_revocation_stops_embedding_retry_after_http_error():
    from google.genai import errors
    sdk = Mock()
    with patch("streamlit.session_state", {}):
        consent.choose("text", True)
        def fail(**kwargs):
            consent.choose("text", False)
            raise errors.APIError(503, {"error": {"message": "simulated unavailable"}})
        sdk.models.embed_content.side_effect = fail
        embedder = GeminiEmbedder("simulated-key", client=sdk, sleep=Mock())
        with pytest.raises(PermissionDenied):
            consent.perform("text", embedder.embed, "simulated")
    sdk.models.embed_content.assert_called_once()


def test_failed_consent_commit_rolls_back_without_false_success(auth, backend):
    db, _, factory = backend
    original = consent.choose
    def fail_commit(*args):
        db.fail_commit = True
        original(*args)
    with patch("edicola.consent.PostgresPersonalStore", side_effect=lambda _: factory()):
        app = AppTest.from_string(SCRIPT).run()
        app.button(key="send").click().run()
        with patch("edicola.consent.choose", side_effect=fail_commit):
            app.button(key="consent_accept").click().run()
    assert not app.exception and app.error and not app.success
    assert not db.consents and not db.profiles
    assert "rag_calls" not in app.session_state and "consent_choices" not in app.session_state


def test_missing_consent_table_blocks_account_without_guest_fallback(auth):
    unavailable = Mock()
    unavailable.get_consent.side_effect = PersonalStoreError("private-schema-error")
    with patch("edicola.consent.PostgresPersonalStore", return_value=unavailable):
        app = AppTest.from_string(SCRIPT).run()
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.button(key="send").click().run()
    assert not app.exception and app.error
    assert all("private-schema-error" not in error.value for error in app.error)
    assert "rag_calls" not in app.session_state
