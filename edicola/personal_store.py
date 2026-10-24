"""CRUD PostgreSQL server-side: identità obbligatoria, transazioni e ownership."""

import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from edicola.identity import Identity, current_identity, secret_section
from edicola.profiles import Profile, validate


class PersonalStoreError(RuntimeError):
    """Errore pubblico: mai dettagli della connessione o dati personali."""


def connect_database():
    config = secret_section("personal_database")
    if not all(config.get(k) for k in ("host", "dbname", "user", "password")):
        raise PersonalStoreError("Database personale non configurato. Nessun dato è stato salvato.")
    try:
        import psycopg
        certificate = config.get("sslrootcert", "system")
        if certificate != "system":
            certificate = str((Path(__file__).resolve().parents[1] / certificate).resolve())
        return psycopg.connect(host=config["host"], dbname=config["dbname"], user=config["user"],
                               password=config["password"], port=int(config.get("port", 5432)),
                               sslmode="verify-full", sslrootcert=certificate,
                               connect_timeout=8, prepare_threshold=None)
    except Exception:
        raise PersonalStoreError("Database personale non raggiungibile o configurazione non valida. Nessun salvataggio confermato.") from None


def decode_result(data):
    from edicola.editorial import EditorialResult
    from edicola.rag import Source
    try:
        data = dict(data)
        data["sources"] = [Source(**source) for source in data["sources"]]
        data["from_cache"] = True
        return EditorialResult(**data)
    except (ValueError, KeyError, TypeError):
        raise PersonalStoreError("Briefing personale non leggibile. Verificare i dati conservati senza rigenerare automaticamente il contenuto.") from None


class PostgresPersonalStore:
    def __init__(self, identity, *, connect=None, identity_provider=None):
        if not isinstance(identity, Identity):
            raise PersonalStoreError("Accesso personale non autorizzato.")
        self.identity = identity
        self.connect = connect or connect_database
        self.identity_provider = identity_provider or current_identity

    def assert_owner(self, owner=None):
        actor = self.identity_provider()
        if not isinstance(actor, Identity) or actor.owner_id != self.identity.owner_id or owner is not None and owner != actor.owner_id:
            raise PersonalStoreError("Accesso personale non autorizzato: identità proprietaria non valida.")
        return actor.owner_id

    @contextmanager
    def transaction(self, *, repeatable=False):
        owner = self.assert_owner()
        try:
            # Psycopg committa solo all'uscita senza errori; altrimenti rollback e close.
            with self.connect() as connection:
                if repeatable:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                connection.execute("SELECT set_config('statement_timeout', %s, true)", ("8000",))
                role = connection.execute("SELECT current_user, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, "
                    "(rolreplication OR rolinherit OR NOT rolcanlogin OR "
                    "EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid) OR "
                    "EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='edicola_private' AND nspowner=pg_roles.oid) OR "
                    "EXISTS(SELECT 1 FROM pg_class JOIN pg_namespace ON pg_namespace.oid=relnamespace "
                    "WHERE nspname='edicola_private' AND relowner=pg_roles.oid)) "
                    "FROM pg_roles WHERE rolname=current_user").fetchone()
                if not role or role[0] != "edicola_app" or any(role[1:]):
                    raise PersonalStoreError("Ruolo database non consentito: usare il ruolo applicativo a privilegi minimi.")
                try:
                    version = connection.execute("SELECT version FROM edicola_private.schema_migrations WHERE version=1").fetchone()
                except Exception as error:
                    if getattr(error, "sqlstate", None) == "42501":
                        raise PersonalStoreError("Permessi dello schema personale incompleti: il gestore deve verificare la migrazione 002. Nessun salvataggio confermato.") from None
                    raise
                if version != (1,):
                    raise PersonalStoreError("Schema personale non aggiornato.")
                connection.execute("SELECT set_config('edicola.owner_id', %s, true)", (owner,))
                yield connection, owner
                self.assert_owner(owner)  # Nessuna conferma se la sessione ha cambiato identità.
        except PersonalStoreError:
            raise
        except Exception:
            raise PersonalStoreError("Operazione personale non completata. Nessun salvataggio confermato; riprovare più tardi.") from None

    @staticmethod
    def ensure_profile(db, owner):
        db.execute("INSERT INTO edicola_private.profiles(owner_id) VALUES (%s) ON CONFLICT(owner_id) DO NOTHING", (owner,))

    def load_profile(self):
        with self.transaction() as (db, owner):
            row = db.execute("SELECT interests, minutes, preferred_format, feedback FROM edicola_private.profiles WHERE owner_id=%s", (owner,)).fetchone()
            saved = db.execute("SELECT chunk_id, reference FROM edicola_private.saved_passages WHERE owner_id=%s ORDER BY created_at,chunk_id", (owner,)).fetchall()
        profile = Profile(user_id=owner) if row is None else Profile(owner, row[0], row[1], row[2], row[3])
        profile.saved = {key: {"metadata": reference, "text": ""} for key, reference in saved}
        validate(profile)
        return profile

    def save_preferences(self, profile):
        self.assert_owner(profile.user_id)
        validate(profile)
        with self.transaction() as (db, owner):
            self.ensure_profile(db, owner)
            feedback = db.execute("SELECT feedback FROM edicola_private.profiles WHERE owner_id=%s FOR UPDATE", (owner,)).fetchone()[0]
            feedback = {k: v for k, v in feedback.items() if k in profile.interests}
            db.execute("UPDATE edicola_private.profiles SET interests=%s::jsonb, minutes=%s, preferred_format=%s, feedback=%s::jsonb, updated_at=now() WHERE owner_id=%s",
                       (json.dumps(profile.interests), profile.minutes, profile.format, json.dumps(feedback), owner))

    def set_feedback(self, topic, value):
        if type(value) is not int or value not in (-1, 0, 1):
            raise ValueError("Gradimento non valido.")
        with self.transaction() as (db, owner):
            row = db.execute("SELECT interests,feedback FROM edicola_private.profiles WHERE owner_id=%s FOR UPDATE", (owner,)).fetchone()
            if row is None or topic not in row[0]:
                raise ValueError("Scegliere un interesse del proprio profilo.")
            feedback = dict(row[1])
            if value:
                feedback[topic] = value
            else:
                feedback.pop(topic, None)
            db.execute("UPDATE edicola_private.profiles SET feedback=%s::jsonb,updated_at=now() WHERE owner_id=%s", (json.dumps(feedback), owner))

    def save_passage(self, chunk):
        reference = {k: v for k, v in chunk.metadata.items() if k in {"filename", "pdf_sha256", "page", "position", "start", "end", "chunk_config", "total_pages"}}
        name = reference.get("filename", "")
        if (not isinstance(chunk.id, str) or not chunk.id or len(chunk.id) > 256 or not isinstance(name, str)
                or not name.lower().endswith(".pdf") or any(c in name for c in "/\\:\0")
                or type(reference.get("page")) is not int or reference["page"] < 1):
            raise ValueError("Riferimento al quotidiano non valido.")
        with self.transaction() as (db, owner):
            self.ensure_profile(db, owner)
            db.execute("INSERT INTO edicola_private.saved_passages(owner_id,chunk_id,reference) VALUES (%s,%s,%s::jsonb) "
                       "ON CONFLICT(owner_id,chunk_id) DO UPDATE SET reference=excluded.reference", (owner, chunk.id, json.dumps(reference)))

    def remove_passage(self, chunk_id):
        with self.transaction() as (db, owner):
            db.execute("DELETE FROM edicola_private.saved_passages WHERE owner_id=%s AND chunk_id=%s", (owner, chunk_id))

    def get_briefing(self, key):
        with self.transaction() as (db, owner):
            row = db.execute("SELECT result_json FROM edicola_private.briefings WHERE owner_id=%s AND cache_key=%s", (owner, key)).fetchone()
        return decode_result(row[0]) if row else None

    def save_briefing(self, key, result):
        if result.kind != "briefing" or not result.sufficient or not result.sections:
            raise ValueError("Salvare soltanto briefing verificati.")
        with self.transaction() as (db, owner):
            self.ensure_profile(db, owner)
            db.execute("INSERT INTO edicola_private.briefings(owner_id,cache_key,result_json) VALUES (%s,%s,%s::jsonb) "
                       "ON CONFLICT(owner_id,cache_key) DO UPDATE SET result_json=excluded.result_json", (owner, key, json.dumps(asdict(result))))

    def list_products(self):
        from edicola.podcast_text import CachedProduct
        with self.transaction() as (db, owner):
            rows = db.execute("SELECT cache_key,created_at,result_json FROM edicola_private.briefings WHERE owner_id=%s ORDER BY created_at DESC,cache_key", (owner,)).fetchall()
        return [CachedProduct(key, created.isoformat(), decode_result(data)) for key, created, data in rows]

    def delete_all(self):
        with self.transaction() as (db, owner):
            db.execute("DELETE FROM edicola_private.profiles WHERE owner_id=%s", (owner,))

    def get_consent(self, purpose, version):
        with self.transaction() as (db, owner):
            row = db.execute("SELECT granted FROM edicola_private.ai_consents WHERE owner_id=%s AND purpose=%s AND version=%s",
                             (owner, purpose, version)).fetchone()
        return row[0] if row else None

    def set_consent(self, purpose, version, granted):
        if purpose not in {"text", "personal_text", "audio"} or type(granted) is not bool or not isinstance(version, str) or not 1 <= len(version) <= 80:
            raise ValueError("Autorizzazione non valida.")
        with self.transaction() as (db, owner):
            self.ensure_profile(db, owner)
            db.execute("INSERT INTO edicola_private.ai_consents(owner_id,purpose,version,granted) VALUES (%s,%s,%s,%s) "
                       "ON CONFLICT(owner_id,purpose) DO UPDATE SET version=excluded.version,granted=excluded.granted,updated_at=now()",
                       (owner, purpose, version, granted))

    def export_data(self):
        # Una sola transazione/snapshot coerente per tutto l'export.
        with self.transaction(repeatable=True) as (db, owner):
            profile = db.execute("SELECT owner_id,interests,minutes,preferred_format,feedback,updated_at FROM edicola_private.profiles WHERE owner_id=%s", (owner,)).fetchone()
            saved = db.execute("SELECT chunk_id,reference,created_at FROM edicola_private.saved_passages WHERE owner_id=%s ORDER BY chunk_id", (owner,)).fetchall()
            briefs = db.execute("SELECT cache_key,created_at,result_json FROM edicola_private.briefings WHERE owner_id=%s ORDER BY cache_key", (owner,)).fetchall()
            consents = db.execute("SELECT purpose,version,granted,updated_at FROM edicola_private.ai_consents WHERE owner_id=%s ORDER BY purpose", (owner,)).fetchall()
            from edicola.chat_store import ChatStore
            chat_history = ChatStore.export_history(db, owner)
        profile_data = dict(zip(("owner_id", "interests", "minutes", "format", "feedback"), profile[:5])) if profile else None
        if profile_data is not None:
            profile_data["updated_at"] = profile[5].isoformat()
        return {"version": 2, "profile": profile_data, "chat_history": chat_history,
                "saved": [{"chunk_id": key, "reference": ref, "created_at": created.isoformat()} for key, ref, created in saved],
                "briefings": [{"key": key, "created_at": created.isoformat(), "result": data} for key, created, data in briefs],
                "ai_consents": [{"purpose": purpose, "version": version, "granted": granted, "updated_at": updated.isoformat()}
                                for purpose, version, granted, updated in consents]}
