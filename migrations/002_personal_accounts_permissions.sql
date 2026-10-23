-- Riparazione non distruttiva di una 001 eseguita senza SELECT schema_migrations.
-- Eseguire MANUALMENTE nel SQL Editor Supabase come proprietario delle tabelle.
-- Nessuna password, ALTER ROLE, cancellazione o modifica dei dati personali.
BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edicola_app') THEN
        RAISE EXCEPTION 'Applicare prima la migrazione 001';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles r WHERE r.rolname = 'edicola_app'
        AND (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication
             OR r.rolbypassrls OR r.rolinherit OR NOT r.rolcanlogin
             OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid)
             OR EXISTS (SELECT 1 FROM pg_namespace
                        WHERE nspname = 'edicola_private' AND nspowner = r.oid)
             OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'edicola_private' AND c.relowner = r.oid))
    ) THEN
        RAISE EXCEPTION 'edicola_app non rispetta i privilegi minimi: verificare ruolo, membership e ownership';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM edicola_private.schema_migrations WHERE version = 1) THEN
        RAISE EXCEPTION 'Migrazione 001 non registrata';
    END IF;
END
$$;

REVOKE ALL ON SCHEMA edicola_private FROM PUBLIC, anon, authenticated, edicola_app;
GRANT USAGE ON SCHEMA edicola_private TO edicola_app;
REVOKE ALL ON ALL TABLES IN SCHEMA edicola_private FROM PUBLIC, anon, authenticated, edicola_app;
GRANT SELECT ON edicola_private.schema_migrations TO edicola_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON edicola_private.profiles,
    edicola_private.saved_passages, edicola_private.briefings TO edicola_app;

INSERT INTO edicola_private.schema_migrations(version) VALUES (2)
ON CONFLICT (version) DO NOTHING;
COMMIT;
