"""Diagnostica di sola lettura per il database personale Streamlit Cloud.

Le risposte sono intenzionalmente generiche: mai host, password, token,
SQLSTATE, owner_id, nomi utente o contenuti delle preferenze nell'interfaccia.
Non crea profili, non modifica tabelle e non invia richieste Gemini.
"""

from edicola.identity import secret_section
from edicola.personal_store import PersonalStoreError, connect_database


_REQUIRED = ("host", "dbname", "user", "password")
_TABLES = (
    "profiles", "saved_passages", "briefings", "ai_consents",
    "chat_settings", "conversations", "chat_messages",
)
_ROLE_CHECK = (
    "SELECT current_user, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, "
    "(rolreplication OR rolinherit OR NOT rolcanlogin OR "
    "EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid) OR "
    "EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='edicola_private' "
    "AND nspowner=pg_roles.oid) OR "
    "EXISTS(SELECT 1 FROM pg_class JOIN pg_namespace "
    "ON pg_namespace.oid=relnamespace WHERE nspname='edicola_private' "
    "AND relowner=pg_roles.oid)) FROM pg_roles WHERE rolname=current_user"
)


def inspect_personal_database():
    """Restituisce (successo, indicazione sicura) senza alterare il database."""
    config = secret_section("personal_database")
    if not all(config.get(key) for key in _REQUIRED):
        return False, (
            "La sezione [personal_database] nei Secrets Streamlit è incompleta: "
            "verifica host, dbname, user e password."
        )
    try:
        connection = connect_database()
    except PersonalStoreError:
        return False, (
            "I Secrets sono presenti, ma la connessione PostgreSQL non riesce. "
            "Controlla dal pannello Supabase host e porta del Session pooler, "
            "utente e password del ruolo edicola_app e certificato SSL."
        )
    try:
        with connection as db:
            # Impedisce qualunque modifica anche in caso di futuri interventi.
            db.execute("SET TRANSACTION READ ONLY")
            try:
                role = db.execute(_ROLE_CHECK).fetchone()
            except Exception:
                return False, "Connessione riuscita, ma il controllo del ruolo PostgreSQL non riesce."
            if not role or role[0] != "edicola_app" or any(role[1:]):
                return False, (
                    "La connessione funziona, ma il ruolo non ha i privilegi previsti. "
                    "È necessario il ruolo edicola_app con i permessi limitati "
                    "definiti dalla migrazione 001."
                )
            try:
                rows = db.execute(
                    "SELECT version FROM edicola_private.schema_migrations ORDER BY version"
                ).fetchall()
            except Exception:
                return False, (
                    "La connessione funziona, ma il catalogo delle migrazioni non è "
                    "leggibile. Verifica le migrazioni 001 e 002."
                )
            versions = {row[0] for row in rows}
            missing = sorted({1, 2, 3, 4} - versions)
            if missing:
                return False, (
                    "Connessione riuscita, ma risultano mancanti le migrazioni: "
                    + ", ".join(f"{version:03d}" for version in missing)
                    + ". Controllale nel SQL Editor senza cancellare dati."
                )
            for table in _TABLES:
                try:
                    db.execute(f"SELECT 1 FROM edicola_private.{table} LIMIT 0")
                except Exception:
                    return False, (
                        "Connessione e migrazioni presenti, ma non è possibile "
                        "leggere tutte le tabelle personali. Controlla i permessi "
                        "di edicola_app e le policy RLS, senza disattivarle."
                    )
        return True, (
            "Connessione, ruolo, migrazioni e lettura delle tabelle verificati. "
            "Se il profilo è ancora bloccato, occorre controllare i permessi "
            "RLS dell'utente e i log del server."
        )
    except Exception:
        return False, (
            "La connessione è stata aperta, ma il controllo non è terminato. "
            "Verifica disponibilità del database e log privati Streamlit."
        )
