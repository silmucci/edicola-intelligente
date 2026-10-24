"""OIDC/PostgreSQL simulati: mai accessi a Google, Supabase o Gemini."""

import copy
import base64
import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola import identity
from edicola.account_ui import render_account_profile
from edicola.identity import Identity, current_identity
from edicola.personal_store import PersonalStoreError, PostgresPersonalStore, connect_database
from edicola.personalization import generate_personal_briefing
from edicola.profiles import Profile
from test_editorial import make_catalog
from test_personalization import client_with_news

AUTH = {"redirect_uri": "http://localhost:8501/oauth2callback", "cookie_secret": "test-cookie-not-a-real-secret-32-characters",
        "google": {"client_id": "test-client", "client_secret": "test-client-secret", "server_metadata_url": identity.GOOGLE_METADATA}}
A = Identity(identity.GOOGLE_ISSUER, "user-a")
B = Identity(identity.GOOGLE_ISSUER, "user-b")


class User(dict):
    is_logged_in = True


def user(actor=A, **claims):
    return User(iss=actor.issuer, sub=actor.subject, aud="test-client", **claims)


class FakeDatabase:
    """Memoria condivisa fra connessioni/sessioni, con transazioni e scoping simulati."""
    def __init__(self):
        self.profiles, self.saved, self.briefs, self.consents = {}, {}, {}, {}
        self.chat_settings, self.chats, self.messages = {}, {}, {}
        self.calls = []
        self.role = ("edicola_app", False, False, False, False, False)
        self.fail = False
        self.fail_commit = False
        self.migration_select = True
        self.connections = []

    @contextmanager
    def connect(self):
        if self.fail:
            raise OSError("private-password DATABASE-DOWN")
        before = copy.deepcopy((self.profiles, self.saved, self.briefs, self.consents, self.chat_settings, self.chats, self.messages))
        connection = FakeConnection(self)
        self.connections.append(connection)
        try:
            yield connection
            if self.fail_commit:
                raise OSError("private-password COMMIT-FAILED")
        except Exception:
            self.profiles, self.saved, self.briefs, self.consents, self.chat_settings, self.chats, self.messages = before
            raise
        finally:
            connection.owner = None  # SET LOCAL non sopravvive a commit/rollback.


class FakeConnection:
    def __init__(self, db):
        self.db, self.owner, self.rows = db, None, []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def execute(self, sql, params=()):
        self.db.calls.append((sql, params))
        self.rows = []
        if sql.startswith("SELECT current_user"):
            self.rows = [self.db.role]
        elif "schema_migrations" in sql:
            if not self.db.migration_select:
                error = RuntimeError("private-schema-details permission denied")
                error.sqlstate = "42501"
                raise error
            self.rows = [(1,)]
        elif sql.startswith("SET TRANSACTION"):
            assert len(self.db.calls) == 1 or self.db.calls[-2][0].startswith(("SELECT", "UPDATE", "DELETE", "INSERT"))
        elif "set_config('edicola.owner_id'" in sql:
            self.owner = params[0]
        elif "set_config('statement_timeout'" in sql:
            pass
        else:
            assert self.owner is not None
            assert params, "Le query dati devono essere parametrizzate"
            if any("edicola_private." + table in sql for table in ("chat_settings", "conversations", "chat_messages")):
                from chat_fake import execute_chat
                self.rows = execute_chat(self.db, sql, params, self.owner)
                return self
            owner = params[-1] if sql.startswith("UPDATE") else params[0]
            assert owner == self.owner, "RLS simulata: identità differente"
            if sql.startswith("INSERT INTO edicola_private.ai_consents"):
                self.db.consents[(owner, params[1])] = (params[2], params[3])
            elif sql.startswith("SELECT") and "FROM edicola_private.ai_consents" in sql:
                if sql.startswith("SELECT granted"):
                    result = self.db.consents.get((owner, params[1]))
                    self.rows = [(result[1],)] if result and result[0] == params[2] else []
                else:
                    self.rows = [(purpose, version, granted, datetime(2026, 10, 23, tzinfo=timezone.utc))
                                 for (who, purpose), (version, granted) in self.db.consents.items() if who == owner]
            elif sql.startswith("INSERT INTO edicola_private.profiles"):
                self.db.profiles.setdefault(owner, [[], 5, "testo", {}])
            elif sql.startswith("SELECT") and "FROM edicola_private.profiles" in sql:
                row = self.db.profiles.get(owner)
                if row is not None:
                    if sql.startswith("SELECT feedback"):
                        self.rows = [(copy.deepcopy(row[3]),)]
                    elif sql.startswith("SELECT interests,feedback"):
                        self.rows = [(copy.deepcopy(row[0]), copy.deepcopy(row[3]))]
                    elif sql.startswith("SELECT owner_id,"):
                        self.rows = [(owner, *copy.deepcopy(row), datetime(2026, 10, 23, tzinfo=timezone.utc))]
                    else:
                        self.rows = [copy.deepcopy(tuple(row))]
            elif sql.startswith("UPDATE"):
                if "SET interests=" in sql:
                    interests, minutes, preferred, feedback, owner = params
                    self.db.profiles[owner] = [json.loads(interests), minutes, preferred, json.loads(feedback)]
                else:
                    self.db.profiles[owner][3] = json.loads(params[0])
            elif sql.startswith("INSERT INTO edicola_private.saved_passages"):
                self.db.saved[(owner, params[1])] = json.loads(params[2])
            elif sql.startswith("DELETE FROM edicola_private.saved_passages"):
                self.db.saved.pop((owner, params[1]), None)
            elif sql.startswith("SELECT") and "saved_passages" in sql:
                self.rows = [(key, copy.deepcopy(ref)) for (who, key), ref in self.db.saved.items() if who == owner]
                if sql.startswith("SELECT chunk_id,reference,created_at"):
                    self.rows = [(key, ref, datetime(2026, 10, 23, tzinfo=timezone.utc)) for key, ref in self.rows]
            elif sql.startswith("INSERT INTO edicola_private.briefings"):
                self.db.briefs[(owner, params[1])] = json.loads(params[2])
            elif sql.startswith("SELECT") and "FROM edicola_private.briefings" in sql:
                if sql.startswith("SELECT result_json"):
                    result = self.db.briefs.get((owner, params[1]))
                    self.rows = [(copy.deepcopy(result),)] if result is not None else []
                else:
                    self.rows = [(key, datetime(2026, 10, 23, tzinfo=timezone.utc), copy.deepcopy(result))
                                 for (who, key), result in self.db.briefs.items() if who == owner]
            elif sql.startswith("DELETE FROM edicola_private.profiles"):
                self.db.profiles.pop(owner, None)
                self.db.saved = {key: ref for key, ref in self.db.saved.items() if key[0] != owner}
                self.db.briefs = {key: ref for key, ref in self.db.briefs.items() if key[0] != owner}
                self.db.consents = {key: ref for key, ref in self.db.consents.items() if key[0] != owner}
                self.db.chat_settings.pop(owner, None)
                self.db.chats = {key: ref for key, ref in self.db.chats.items() if key[0] != owner}
                self.db.messages = {key: ref for key, ref in self.db.messages.items() if key[0] != owner}
            else:
                raise AssertionError("Query simulata non prevista: " + sql)
        return self


@pytest.fixture(autouse=True)
def accounts_mode(monkeypatch):
    monkeypatch.setenv("EDICOLA_PROFILE_MODE", "accounts")
    monkeypatch.setenv("EDICOLA_CLOUD_DEMO", "0")
    with patch("google.genai.Client", side_effect=AssertionError("Gemini reale vietato")), patch(
        "psycopg.connect", side_effect=AssertionError("Database reale vietato")):
        yield


@pytest.fixture
def backend():
    db, actor = FakeDatabase(), [A]
    def store(who=None):
        return PostgresPersonalStore(who or actor[0], connect=db.connect, identity_provider=lambda: actor[0])
    return db, actor, store


@pytest.fixture
def auth():
    with patch("streamlit.secrets", {"auth": AUTH}), patch("streamlit.user", user()):
        yield


def test_identity_is_native_issuer_subject_not_email(auth):
    assert current_identity() == A
    with patch("streamlit.user", user(email="changed@example.test")):
        assert current_identity().owner_id == A.owner_id
    with patch("streamlit.user", user(B, email="same@example.test")):
        assert current_identity().owner_id != A.owner_id
    for bad in ({"iss": "https://evil.example", "sub": "user-a", "aud": "test-client"},
                {"iss": identity.GOOGLE_ISSUER, "sub": "", "aud": "test-client"},
                {"iss": identity.GOOGLE_ISSUER, "sub": "user-a", "aud": "other-client"}):
        with patch("streamlit.user", User(bad)):
            assert current_identity() is None


def test_real_streamlit_nested_secrets_mapping_is_supported():
    from streamlit.runtime.secrets import AttrDict
    with patch("streamlit.secrets", AttrDict({"auth": AUTH})), patch("streamlit.user", user()):
        assert identity.google_configured() and current_identity() == A


@pytest.mark.parametrize("cookie", ["short", "GENERARE_PRIVATAMENTE_UN_SEGRETO_CASUALE_LUNGO"])
def test_short_or_example_cookie_secret_never_enables_personal_access(cookie):
    config = {**AUTH, "cookie_secret": cookie}
    with patch("streamlit.secrets", {"auth": config}), patch("streamlit.user", user()):
        assert not identity.google_configured() and current_identity() is None


def test_login_logout_use_native_provider_and_clear_private_ui(auth):
    script = '''import streamlit as st
from edicola.identity import login_controls
login_controls()
'''
    guest = User()
    guest.is_logged_in = False
    with patch("streamlit.user", guest), patch("streamlit.login") as login:
        app = AppTest.from_string(script).run()
        app.button(key="account_login").click().run()
        login.assert_called_once_with("google")
    with patch("streamlit.logout") as logout:
        app = AppTest.from_string(script).run()
        app.session_state["personal_interests"] = ["private"]
        app.session_state["account_export"] = "private"
        app.session_state["rag_history"] = ["private"]
        app.button(key="account_logout").click().run()
        logout.assert_called_once()
        assert all(key not in app.session_state for key in ("personal_interests", "account_export", "rag_history"))


def test_first_access_new_session_and_two_users(backend):
    db, actor, store = backend
    assert store().load_profile() == Profile(user_id=A.owner_id)
    assert db.profiles == {}  # Nessuna importazione demo o falso salvataggio al primo accesso.
    store().save_preferences(Profile(A.owner_id, ["scuola"], 2, "testo"))
    assert store().load_profile().interests == ["scuola"]  # Nuovo oggetto e nuova connessione.
    actor[0] = B
    assert store().load_profile().interests == []
    store().save_preferences(Profile(B.owner_id, ["ambiente"], 10, "audio"))
    assert store().load_profile().interests == ["ambiente"]
    actor[0] = A
    assert store().load_profile().interests == ["scuola"]


@pytest.mark.parametrize("operation", ["load", "save", "feedback", "saved", "remove", "brief", "list", "delete", "export"])
def test_foreign_or_stale_identity_is_rejected_before_connection(backend, operation):
    db, actor, factory = backend
    old = factory()
    actor[0] = B
    operations = {"load": old.load_profile, "save": lambda: old.save_preferences(Profile(B.owner_id)),
                  "feedback": lambda: old.set_feedback("scuola", 1), "saved": lambda: old.save_passage(make_catalog().chunks[0]),
                  "remove": lambda: old.remove_passage("foreign"), "brief": lambda: old.get_briefing("foreign"),
                  "list": old.list_products, "delete": old.delete_all, "export": old.export_data}
    with pytest.raises(PersonalStoreError, match="autorizzato"):
        operations[operation]()
    assert not db.calls


def test_cannot_save_profile_owned_by_another_user(backend):
    db, _, store = backend
    with pytest.raises(PersonalStoreError):
        store().save_preferences(Profile(B.owner_id, ["scuola"]))
    assert not db.calls


def test_updates_feedback_references_export_and_cascade_delete(backend):
    db, actor, store = backend
    store().save_preferences(Profile(A.owner_id, ["scuola", "ambiente"]))
    store().set_feedback("scuola", 1)
    assert store().load_profile().feedback == {"scuola": 1}
    store().set_feedback("scuola", 0)
    assert store().load_profile().feedback == {}
    store().set_feedback("ambiente", -1)
    store().save_preferences(Profile(A.owner_id, ["scuola"], 10, "visuale"))
    assert store().load_profile().feedback == {}
    chunk = make_catalog().chunks[0]
    store().save_passage(chunk)
    assert store().load_profile().saved[chunk.id]["text"] == ""
    assert "text" not in db.saved[(A.owner_id, chunk.id)]  # Solo riferimenti, non copie degli articoli.
    actor[0] = B
    store().save_preferences(Profile(B.owner_id, ["scuola"]))
    store().save_passage(chunk)
    store().remove_passage(chunk.id)
    assert (A.owner_id, chunk.id) in db.saved
    actor[0] = A
    exported = store().export_data()
    assert exported["profile"]["interests"] == ["scuola"]
    assert exported["profile"]["owner_id"] == A.owner_id and exported["profile"]["updated_at"]
    assert len(exported["saved"]) == 1
    store().delete_all()
    assert A.owner_id not in db.profiles and not store().load_profile().saved
    assert B.owner_id in db.profiles


def test_real_generator_uses_persistent_owner_scoped_cache_without_sqlite(backend, tmp_path, monkeypatch):
    db, actor, store = backend
    catalog, client = make_catalog(), client_with_news()
    monkeypatch.setenv("GEMINI_RAG_MODEL", "configured-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    profile = Profile(A.owner_id, ["trasporti"])
    store().save_preferences(profile)
    with patch("edicola.personalization.read_personal_cache", side_effect=AssertionError("Cache SQLite vietata")), patch(
        "edicola.personalization.write_personal_cache", side_effect=AssertionError("Cache SQLite vietata")):
        key, result = generate_personal_briefing(tmp_path, profile, authorize_external=True, catalog=catalog, client=client, store=store())
        assert result.sufficient and client.models.generate_content.call_count == 1
        _, repeated = generate_personal_briefing(tmp_path, store().load_profile(), authorize_external=True, catalog=catalog, client=client, store=store())
        assert repeated.from_cache and client.models.generate_content.call_count == 1
        actor[0] = B
        assert store().get_briefing(key) is None and store().list_products() == []
        profile_b = Profile(B.owner_id, ["trasporti"])
        same_key, _ = generate_personal_briefing(tmp_path, profile_b, authorize_external=True, catalog=catalog, client=client, store=store())
        assert same_key == key and client.models.generate_content.call_count == 2
        assert len(db.briefs) == 2
        actor[0] = A
        assert len(store().list_products()) == 1
        store().delete_all()
        assert (B.owner_id, key) in db.briefs and (A.owner_id, key) not in db.briefs
    assert not list(tmp_path.rglob("*.sqlite3"))


@pytest.mark.parametrize("failure", ["connect", "commit", "admin", "bypass", "membership"])
def test_database_failures_do_not_report_success_or_leak_credentials(backend, failure):
    db, _, store = backend
    if failure == "connect":
        db.fail = True
    elif failure == "commit":
        db.fail_commit = True
    else:
        db.role = {"admin": ("postgres", True, True, True, True, False),
                   "bypass": ("edicola_app", False, True, False, False, False),
                   "membership": ("edicola_app", False, False, False, False, True)}[failure]
    with pytest.raises(PersonalStoreError) as caught:
        store().save_preferences(Profile(A.owner_id, ["scuola"]))
    assert "private-password" not in str(caught.value)
    assert not db.profiles


def test_connections_force_verified_tls_no_admin_password_in_logs():
    config = {"host": "db.example.test", "dbname": "postgres", "user": "edicola_app.ref", "password": "test-secret"}
    with patch("edicola.personal_store.secret_section", return_value=config), patch("psycopg.connect", return_value=Mock()) as connect:
        connect_database()
        assert connect.call_args.kwargs["sslmode"] == "verify-full"
        assert connect.call_args.kwargs["prepare_threshold"] is None
        assert connect.call_args.kwargs["connect_timeout"] == 8


def test_malformed_secret_sections_fail_closed():
    with patch("streamlit.secrets", {"auth": "invalid", "personal_database": "invalid"}):
        assert not identity.google_configured()
        with pytest.raises(PersonalStoreError, match="non configurato"):
            connect_database()


def test_malformed_cached_briefing_is_reported_without_raw_data(backend):
    db, _, factory = backend
    db.briefs[(A.owner_id, "test-key")] = {"private-field": "private-value"}
    with pytest.raises(PersonalStoreError) as caught:
        factory().get_briefing("test-key")
    assert "private-value" not in str(caught.value)


def test_session_switch_clears_previous_user_data(auth):
    source = "from edicola.identity import synchronize_identity\nsynchronize_identity()"
    app = AppTest.from_string(source).run()
    app.session_state["personal_interests"] = ["private-a"]
    app.session_state["account_export"] = "private-export-a"
    app.session_state["personal_product"] = "brief-a"
    with patch("streamlit.user", user(B)):
        app.run()
        assert not app.exception
        assert app.session_state["_active_owner"] == B.owner_id
        assert all(k not in app.session_state for k in ("personal_interests", "account_export", "personal_product"))


def ui(root):
    return f"from pathlib import Path\nfrom edicola.personalization_ui import render_personalization_ui\nrender_personalization_ui(Path({str(root)!r}))"


def test_public_unconfigured_auth_never_reads_legacy_demo(tmp_path):
    with patch("streamlit.secrets", {}), patch("edicola.personalization_ui.load_profile", side_effect=AssertionError("Demo pubblica vietata")):
        app = AppTest.from_string(ui(tmp_path)).run()
    assert not app.exception and app.button(key="account_login").disabled
    assert not app.multiselect and not list(tmp_path.iterdir())


def test_cloud_cannot_enable_local_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("EDICOLA_PROFILE_MODE", "local_demo")
    monkeypatch.setenv("EDICOLA_CLOUD_DEMO", "1")
    assert not identity.local_demo()
    with patch("streamlit.secrets", {}), patch("edicola.personalization_ui.load_profile", side_effect=AssertionError):
        app = AppTest.from_string(ui(tmp_path)).run()
    assert not app.exception and not app.multiselect


def test_ui_reports_database_error_without_success(auth, backend, tmp_path):
    db, _, store = backend
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda _: store()), patch("edicola.account_ui.read_catalog", return_value=make_catalog()):
        app = AppTest.from_string(ui(tmp_path)).run()
        assert not app.exception
        db.fail_commit = True
        app.multiselect(key="personal_interests").set_value(["scuola"])
        app.button(key="FormSubmitter:personal_preferences-Salva preferenze").click().run()
        assert not app.exception and app.error and not app.success
        assert not db.profiles


def test_public_home_does_not_import_demo(auth, backend, tmp_path):
    db, _, store = backend
    from edicola.pdf_viewer import ArchiveContext
    context = ArchiveContext(tmp_path, [], {})
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda _: store()), patch(
        "edicola.experience_ui.load_profile", side_effect=AssertionError("Lettura demo vietata")), patch(
        "edicola.experience_ui.read_catalog", return_value=make_catalog()), patch("edicola.experience_ui.render_gallery"):
        # Le strutture vuote dell'archivio non richiedono dati reali o PDF.
        source = f"from pathlib import Path\nfrom edicola.pdf_viewer import ArchiveContext\nfrom edicola.experience_ui import render_home\nr=Path({str(tmp_path)!r})\nrender_home(r,ArchiveContext(r,[],{{}}))"
        app = AppTest.from_string(source).run()
    assert not app.exception and not db.profiles
    assert any(h.value == "Consigliati per te" for h in app.subheader)


def test_ui_two_new_sessions_recover_only_current_profile(auth, backend, tmp_path):
    db, actor, factory = backend
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda _: factory()), patch("edicola.account_ui.read_catalog", return_value=make_catalog()):
        first = AppTest.from_string(ui(tmp_path)).run()
        first.multiselect(key="personal_interests").set_value(["scuola"])
        first.button(key="FormSubmitter:personal_preferences-Salva preferenze").click().run()
        assert not first.exception and first.success
        with patch("streamlit.logout") as logout:
            first.button(key="account_logout").click().run()
            logout.assert_called_once()
        actor[0] = B
        with patch("streamlit.user", user(B)):
            second = AppTest.from_string(ui(tmp_path)).run()
            assert not second.exception and second.multiselect(key="personal_interests").value == []
            second.multiselect(key="personal_interests").set_value(["ambiente"])
            second.button(key="FormSubmitter:personal_preferences-Salva preferenze").click().run()
            assert not second.exception
        actor[0] = A
        restored = AppTest.from_string(ui(tmp_path)).run()
        assert not restored.exception and restored.multiselect(key="personal_interests").value == ["scuola"]
        assert set(db.profiles) == {A.owner_id, B.owner_id}
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_ui_save_export_delete_and_no_shared_download_urls(auth, backend, tmp_path):
    db, _, factory = backend
    factory().save_preferences(Profile(A.owner_id, ["trasporti"]))
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda _: factory()), patch(
        "edicola.account_ui.read_catalog", return_value=make_catalog()), patch("edicola.private_media._media") as media:
        app = AppTest.from_string(ui(tmp_path)).run()
        save = next(button for button in app.button if button.label == "Salva lettura")
        app.button(key=save.key).click().run()
        assert not app.exception and factory().load_profile().saved
        app.button(key="account_export_prepare").click().run()
        assert not app.exception
        exported = json.loads(base64.b64decode(media.call_args.kwargs["data"]["bytes"]))
        assert exported["profile"]["interests"] == ["trasporti"]
        assert exported["saved"]
        assert not app.get("download_button")  # Nessun endpoint media anonimo per i dati personali.
        app.checkbox(key="account_delete_confirm").check().run()
        app.button(key="account_delete").click().run()
        assert not app.exception and any("cancellati" in s.value for s in app.success)
        assert not db.profiles and not db.saved and "account_export" not in app.session_state


def test_unconfigured_database_after_verified_login_fails_closed(auth, tmp_path):
    with patch("edicola.personalization_ui.load_profile", side_effect=AssertionError("Demo vietata")):
        app = AppTest.from_string(ui(tmp_path)).run()
    assert not app.exception and app.error and not app.success and not app.multiselect
    assert any("spazio personale" in e.value for e in app.error)


def test_personal_audio_is_scoped_ephemeral_and_briefings_stay_in_postgres(backend, tmp_path, monkeypatch):
    from edicola.personal_audio import audio_scope, prepare_audio, remove_audio
    from edicola.podcast import generate_podcast
    from test_podcast import fake_client
    db, actor, factory = backend
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    key, _ = generate_personal_briefing(tmp_path, Profile(A.owner_id, ["trasporti"]), authorize_external=True,
                                      catalog=make_catalog(), client=client_with_news(), store=factory())
    stale = factory()
    scope_a = prepare_audio(tmp_path, stale, key)
    audio = generate_podcast(key, root=scope_a, authorize_external=True, client=fake_client())
    assert audio.audio_path.is_file()
    with patch("edicola.personal_audio.write_personal_cache", side_effect=OSError("private-path-key")):
        with pytest.raises(PersonalStoreError) as caught:
            prepare_audio(tmp_path, stale, key)
        assert "private-path-key" not in str(caught.value)
    assert audio_scope(tmp_path / ".cloud-runtime/first", factory()) == audio_scope(tmp_path / ".cloud-runtime/second", factory())
    actor[0] = B
    scope_b = audio_scope(tmp_path, factory())
    assert scope_b != scope_a
    with pytest.raises(PersonalStoreError):
        prepare_audio(tmp_path, factory(), key)
    with pytest.raises(PersonalStoreError):
        audio_scope(tmp_path, stale)
    remove_audio(tmp_path, factory())
    assert audio.audio_path.exists()
    actor[0] = A
    remove_audio(tmp_path, factory())
    assert not scope_a.exists() and factory().get_briefing(key).sufficient


def test_ui_loads_persistent_briefing_without_generation_or_local_sqlite(auth, backend, tmp_path, monkeypatch):
    db, _, factory = backend
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    key, _ = generate_personal_briefing(tmp_path, Profile(A.owner_id, ["trasporti"]), authorize_external=True,
                                      catalog=make_catalog(), client=client_with_news(), store=factory())
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda _: factory()), patch(
        "edicola.account_ui.read_catalog", return_value=make_catalog()), patch(
        "edicola.account_ui.generate_personal_briefing", side_effect=AssertionError("Rigenerazione automatica vietata")):
        app = AppTest.from_string(ui(tmp_path)).run()
    assert not app.exception and app.selectbox(key="personal_product").value == key
    assert any("spazio personale" in caption.value for caption in app.caption)
    assert any("temporanei" in caption.value for caption in app.caption)
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_sql_is_parametrized_and_migration_enforces_rls(backend):
    db, _, factory = backend
    malicious = "scuola'; DROP TABLE profiles; --"
    factory().save_preferences(Profile(A.owner_id, [malicious]))
    factory().load_profile()
    factory().export_data()
    factory().delete_all()
    assert all(malicious not in sql and A.owner_id not in sql for sql, _ in db.calls)
    for sql, params in db.calls:
        if sql.startswith(("UPDATE", "DELETE")) or sql.startswith("SELECT") and any(
            table in sql for table in ("FROM edicola_private.profiles", "FROM edicola_private.saved_passages", "FROM edicola_private.briefings")):
            assert "WHERE owner_id=%s" in sql and A.owner_id in params
    migration = (Path(__file__).resolve().parents[1] / "migrations/001_personal_accounts.sql").read_text()
    assert migration.count("FORCE ROW LEVEL SECURITY") == 3
    assert migration.count("WITH CHECK") == 3 and "rolbypassrls" in migration
    assert "GRANTSELECT,INSERT,UPDATE,DELETE" in "".join(migration.split()) and "GRANT ALL" not in migration


def test_missing_migration_select_is_safe_actionable_and_prevents_writes(backend):
    db, _, factory = backend
    db.migration_select = False
    with pytest.raises(PersonalStoreError, match="migrazione 002") as caught:
        factory().save_preferences(Profile(A.owner_id, ["scuola"]))
    assert "private-schema-details" not in str(caught.value)
    assert db.profiles == {}
    assert not any("INSERT" in sql for sql, _ in db.calls)


def test_owner_is_transaction_local_on_commit_rollback_and_user_switch(backend):
    db, actor, factory = backend
    factory().save_preferences(Profile(A.owner_id, ["scuola"]))
    db.fail_commit = True
    with pytest.raises(PersonalStoreError):
        factory().save_preferences(Profile(A.owner_id, ["errore"]))
    db.fail_commit = False
    actor[0] = B
    assert factory().load_profile().interests == []
    actor[0] = A
    assert factory().load_profile().interests == ["scuola"]
    assert all(c.owner is None for c in db.connections)
    guc = [(sql, params) for sql, params in db.calls if "set_config('edicola.owner_id'" in sql]
    assert all("%s, true)" in sql for sql, _ in guc)
    assert [params[0] for _, params in guc] == [A.owner_id, A.owner_id, B.owner_id, A.owner_id]


@pytest.mark.parametrize("name", ["001_personal_accounts.sql", "002_personal_accounts_permissions.sql"])
def test_migrations_restore_minimum_grants_without_privileged_alter_role(name):
    sql = (Path(__file__).resolve().parents[1] / "migrations" / name).read_text()
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    compact = " ".join(statements.split())
    assert "GRANT SELECT ON edicola_private.schema_migrations TO edicola_app" in compact
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA edicola_private" in compact
    assert "ALTER ROLE" not in statements
    for guard in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb", "rolreplication", "pg_auth_members", "relowner", "RAISE EXCEPTION"):
        assert guard in statements
    assert "DROP TABLE" not in statements and "DELETE FROM" not in statements


def test_runtime_role_guard_includes_replication_and_inheritance(backend):
    db, _, factory = backend
    factory().load_profile()
    role_sql = next(sql for sql, _ in db.calls if sql.startswith("SELECT current_user"))
    assert "rolreplication OR rolinherit OR NOT rolcanlogin" in role_sql


def test_permission_error_is_visible_in_ui_without_false_save(auth, backend, tmp_path):
    db, _, factory = backend
    db.migration_select = False
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=lambda _: factory()):
        app = AppTest.from_string(ui(tmp_path)).run()
    assert not app.exception and not app.success
    assert any("spazio personale" in error.value for error in app.error)
    assert all("migrazione" not in error.value for error in app.error)
    assert not db.profiles


def test_catalog_audit_never_reads_personal_rows_or_changes_configuration():
    sql = (Path(__file__).resolve().parents[1] / "migrations/audit_personal_accounts.sql").read_text()
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert "BEGIN TRANSACTION READ ONLY" in statements and "ROLLBACK;" in statements
    for table in ("profiles", "saved_passages", "briefings"):
        assert "FROM edicola_private." + table not in statements
    for forbidden in ("ALTER ", "CREATE ", "INSERT ", "DELETE ", "UPDATE ", "SET ROLE", "PASSWORD"):
        assert forbidden not in statements


def test_linux_cannot_enable_local_demo_even_without_snapshot_flag(monkeypatch):
    monkeypatch.setenv("EDICOLA_PROFILE_MODE", "local_demo")
    monkeypatch.setattr(identity, "development_host", lambda: False)
    assert not identity.local_demo()
