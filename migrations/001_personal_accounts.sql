
-- EDICOLA DIGITALE INTELLIGENTE
-- Migrazione 001: profili personali PostgreSQL
-- Eseguire nel SQL Editor Supabase come amministratore.
-- Non inserire password o credenziali in questo file.

BEGIN;

-- 1. Ruolo applicativo con privilegi limitati

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'edicola_app'
    ) THEN
        CREATE ROLE edicola_app WITH LOGIN NOINHERIT;
    END IF;
END
$$;

-- I default PostgreSQL sono NOSUPERUSER/NOCREATEDB/NOCREATEROLE/
-- NOREPLICATION/NOBYPASSRLS. Non usare ALTER ROLE privilegiati su Supabase.
-- Un ruolo preesistente non sicuro deve invece interrompere la migrazione.
DO $$
BEGIN
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
END
$$;

-- 2. Schema privato

CREATE SCHEMA IF NOT EXISTS edicola_private;

REVOKE ALL ON SCHEMA edicola_private
FROM PUBLIC, anon, authenticated;

REVOKE ALL ON SCHEMA edicola_private
FROM edicola_app;

GRANT USAGE ON SCHEMA edicola_private
TO edicola_app;

-- 3. Tabella delle migrazioni

CREATE TABLE IF NOT EXISTS edicola_private.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- 4. Profili personali

CREATE TABLE IF NOT EXISTS edicola_private.profiles (
    owner_id text PRIMARY KEY
        CHECK (owner_id ~ '^[0-9a-f]{64}$'),

    interests jsonb NOT NULL DEFAULT '[]'
        CHECK (
            jsonb_typeof(interests) = 'array'
            AND jsonb_array_length(interests) <= 10
        ),

    minutes integer NOT NULL DEFAULT 5
        CHECK (minutes IN (2, 5, 10)),

    preferred_format text NOT NULL DEFAULT 'testo'
        CHECK (
            preferred_format IN ('testo', 'visuale', 'audio')
        ),

    feedback jsonb NOT NULL DEFAULT '{}'
        CHECK (jsonb_typeof(feedback) = 'object'),

    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 5. Notizie e passaggi salvati

CREATE TABLE IF NOT EXISTS edicola_private.saved_passages (
    owner_id text NOT NULL
        REFERENCES edicola_private.profiles(owner_id)
        ON DELETE CASCADE,

    chunk_id text NOT NULL,

    reference jsonb NOT NULL
        CHECK (jsonb_typeof(reference) = 'object'),

    created_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (owner_id, chunk_id)
);

-- 6. Briefing personali

CREATE TABLE IF NOT EXISTS edicola_private.briefings (
    owner_id text NOT NULL
        REFERENCES edicola_private.profiles(owner_id)
        ON DELETE CASCADE,

    cache_key text NOT NULL,

    result_json jsonb NOT NULL
        CHECK (jsonb_typeof(result_json) = 'object'),

    created_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (owner_id, cache_key)
);

-- 7. Permessi sulle tabelle

REVOKE ALL ON ALL TABLES IN SCHEMA edicola_private
FROM PUBLIC, anon, authenticated;

REVOKE ALL ON ALL TABLES IN SCHEMA edicola_private
FROM edicola_app;

GRANT SELECT ON edicola_private.schema_migrations TO edicola_app;

GRANT SELECT, INSERT, UPDATE, DELETE
ON edicola_private.profiles,
   edicola_private.saved_passages,
   edicola_private.briefings
TO edicola_app;

-- 8. Attivazione Row Level Security

ALTER TABLE edicola_private.profiles
ENABLE ROW LEVEL SECURITY;

ALTER TABLE edicola_private.saved_passages
ENABLE ROW LEVEL SECURITY;

ALTER TABLE edicola_private.briefings
ENABLE ROW LEVEL SECURITY;

ALTER TABLE edicola_private.profiles
FORCE ROW LEVEL SECURITY;

ALTER TABLE edicola_private.saved_passages
FORCE ROW LEVEL SECURITY;

ALTER TABLE edicola_private.briefings
FORCE ROW LEVEL SECURITY;

-- 9. Policy RLS sui profili

DROP POLICY IF EXISTS own_profile
ON edicola_private.profiles;

CREATE POLICY own_profile
ON edicola_private.profiles
TO edicola_app
USING (
    owner_id = current_setting('edicola.owner_id', true)
)
WITH CHECK (
    owner_id = current_setting('edicola.owner_id', true)
);

-- 10. Policy RLS sulle notizie salvate

DROP POLICY IF EXISTS own_saved
ON edicola_private.saved_passages;

CREATE POLICY own_saved
ON edicola_private.saved_passages
TO edicola_app
USING (
    owner_id = current_setting('edicola.owner_id', true)
)
WITH CHECK (
    owner_id = current_setting('edicola.owner_id', true)
);

-- 11. Policy RLS sui briefing personali

DROP POLICY IF EXISTS own_briefing
ON edicola_private.briefings;

CREATE POLICY own_briefing
ON edicola_private.briefings
TO edicola_app
USING (
    owner_id = current_setting('edicola.owner_id', true)
)
WITH CHECK (
    owner_id = current_setting('edicola.owner_id', true)
);

-- 12. Registrazione migrazione

INSERT INTO edicola_private.schema_migrations(version)
VALUES (1)
ON CONFLICT (version) DO NOTHING;

COMMIT;
