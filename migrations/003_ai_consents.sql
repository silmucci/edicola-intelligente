-- Nuova migrazione: non sostituisce né modifica 001/002 già applicate.
-- Eseguire manualmente come proprietario dello schema nel SQL Editor Supabase.
BEGIN;
CREATE TABLE IF NOT EXISTS edicola_private.ai_consents (
    owner_id text NOT NULL REFERENCES edicola_private.profiles(owner_id) ON DELETE CASCADE,
    purpose text NOT NULL CHECK (purpose IN ('text', 'personal_text', 'audio')),
    version text NOT NULL CHECK (length(version) BETWEEN 1 AND 80),
    granted boolean NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, purpose)
);
REVOKE ALL ON edicola_private.ai_consents FROM PUBLIC, anon, authenticated, edicola_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON edicola_private.ai_consents TO edicola_app;
ALTER TABLE edicola_private.ai_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE edicola_private.ai_consents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_ai_consent ON edicola_private.ai_consents;
CREATE POLICY own_ai_consent ON edicola_private.ai_consents TO edicola_app
USING (owner_id = current_setting('edicola.owner_id', true))
WITH CHECK (owner_id = current_setting('edicola.owner_id', true));
INSERT INTO edicola_private.schema_migrations(version) VALUES (3) ON CONFLICT (version) DO NOTHING;
COMMIT;
