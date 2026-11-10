"""Diagnostica del database: sola lettura, niente dati personali o rete reale."""
from unittest.mock import patch, Mock

from streamlit.testing.v1 import AppTest

from edicola.personal_diagnostics import inspect_personal_database
from edicola.personal_store import PersonalStoreError
from test_personal_accounts import auth


SETTINGS = {"host": "db.example.test", "dbname": "postgres", "user": "edicola_app.ref", "password": "DO_NOT_DISPLAY"}

class DB:
    def __init__(self, role=None, versions=None, fail_on=""):
        self.role = role if role is not None else ("edicola_app", False, False, False, False, False)
        self.versions = versions if versions is not None else [(1,), (2,), (3,), (4,)]
        self.fail_on = fail_on
        self.queries = []

    def execute(self, query):
        self.queries.append(query)
        if self.fail_on and self.fail_on in query:
            raise RuntimeError("private-password-supersecret")
        if query.startswith("SELECT current_user"):
            return Mock(fetchone=lambda: self.role)
        if "schema_migrations" in query:
            return Mock(fetchall=lambda: self.versions)
        return Mock()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def check(db=None, settings=SETTINGS, error=None):
    db = db or DB()
    with patch("edicola.personal_diagnostics.secret_section", return_value=settings), patch(
        "edicola.personal_diagnostics.connect_database",
        side_effect=error if error else lambda: db
    ) as connect:
        result = inspect_personal_database()
    return result, db, connect


def test_missing_config_does_not_attempt_network():
    (ok, message), _, connect = check(settings={})
    assert not ok and "Secrets" in message
    connect.assert_not_called()


def test_connection_problem_does_not_expose_credentials():
    (ok, message), _, connect = check(error=PersonalStoreError("private-password-supersecret"))
    assert not ok and "connessione" in message.lower()
    assert "private-password" not in message and "supersecret" not in message
    connect.assert_called_once()


def test_readonly_diagnosis_checks_role_versions_tables():
    (ok, message), db, _ = check()
    assert ok and "verificati" in message
    assert db.queries[0] == "SET TRANSACTION READ ONLY"
    assert any("schema_migrations" in q for q in db.queries)
    assert len([q for q in db.queries if "LIMIT 0" in q]) == 7
    assert all(q.startswith("SET TRANSACTION READ ONLY") or q.startswith("SELECT ") for q in db.queries)


def test_role_check_fail_closed():
    (ok, message), db, _ = check(db=DB(role=("postgres", True, True, True, True, True)))
    assert not ok and "ruolo" in message
    assert not any("edicola_private" in q and "LIMIT 0" in q for q in db.queries)


def test_missing_migration_report_is_specific():
    (ok, message), _, _ = check(db=DB(versions=[(1,), (2,), (3,)]))
    assert not ok and "004" in message


def test_missing_table_permissions_report_is_safe():
    (ok, message), _, _ = check(db=DB(fail_on="saved_passages LIMIT 0"))
    assert not ok and "permessi" in message.lower()
    assert "private-password" not in message


def test_profile_error_exposes_readonly_check(auth):
    script = """from pathlib import Path
from edicola.account_ui import render_account_profile
render_account_profile(Path("."))
"""
    with patch("edicola.account_ui.PostgresPersonalStore", side_effect=PersonalStoreError("no-db")), patch(
        "edicola.personal_diagnostics.inspect_personal_database",
        return_value=(False, "Connessione non riuscita")
    ) as diagnosis:
        app = AppTest.from_string(script).run()
        assert not app.exception and app.error
        assert app.button(key="account_database_check")
        diagnosis.assert_not_called()
        app.button(key="account_database_check").click().run()
        assert not app.exception
        assert any("Connessione non riuscita" in x.value for x in app.warning)
        diagnosis.assert_called_once()
