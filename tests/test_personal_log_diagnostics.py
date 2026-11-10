"""Le anomalie del database personale finiscono solo nei log privati.

Nessun host, password, dato utente o eccezione grezza viene stampato.
"""
import logging
from unittest.mock import patch

import pytest

from edicola.personal_store import PersonalStoreError, connect_database
from test_personal_accounts import A, auth, backend


def _stages(caplog):
    return [record.getMessage() for record in caplog.records if "EDICOLA_DB_FAILED" in record.getMessage()]


def test_missing_cloud_section_is_reported_without_secrets(caplog):
    caplog.set_level(logging.WARNING, logger="edicola.personal.database")
    with patch("edicola.personal_store.secret_section", return_value={}):
        with pytest.raises(PersonalStoreError):
            connect_database()
    assert _stages(caplog) == ["EDICOLA_DB_FAILED stage=missing_configuration"]


def test_unreachable_database_logs_only_safe_stage(caplog):
    caplog.set_level(logging.WARNING, logger="edicola.personal.database")
    config = {"host": "secret-host", "dbname": "postgres", "user": "edicola_app",
              "password": "secret-password"}
    with patch("edicola.personal_store.secret_section", return_value=config), patch(
        "psycopg.connect", side_effect=OSError("secret-host secret-password")
    ):
        with pytest.raises(PersonalStoreError):
            connect_database()
    assert _stages(caplog) == ["EDICOLA_DB_FAILED stage=connection_failed"]
    assert "secret-host" not in caplog.text and "secret-password" not in caplog.text


def test_invalid_database_role_is_explained_only_in_private_logs(backend, caplog):
    db, _, store = backend
    caplog.set_level(logging.WARNING, logger="edicola.personal.database")
    db.role = ("postgres", True, True, True, True, False)
    with pytest.raises(PersonalStoreError):
        store().load_profile()
    assert _stages(caplog) == ["EDICOLA_DB_FAILED stage=role_invalid"]


def test_missing_schema_privilege_stage_does_not_touch_data(backend, caplog):
    db, _, store = backend
    caplog.set_level(logging.WARNING, logger="edicola.personal.database")
    db.migration_select = False
    with pytest.raises(PersonalStoreError):
        store().load_profile()
    assert _stages(caplog) == ["EDICOLA_DB_FAILED stage=migration_permission_denied"]
    assert not db.profiles


def test_profile_read_failure_is_identified_without_raw_error(backend, caplog):
    db, _, store = backend
    caplog.set_level(logging.WARNING, logger="edicola.personal.database")
    db.fail_commit = True
    with pytest.raises(PersonalStoreError):
        store().load_profile()
    assert _stages(caplog) == ["EDICOLA_DB_FAILED stage=profile_read"]
    assert not db.profiles
