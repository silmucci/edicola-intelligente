-- Additiva: eseguire manualmente come proprietario dello schema, dopo 001/002/003.
BEGIN;
CREATE TABLE IF NOT EXISTS edicola_private.chat_settings (
    owner_id text PRIMARY KEY REFERENCES edicola_private.profiles(owner_id) ON DELETE CASCADE,
    enabled boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS edicola_private.conversations (
    owner_id text NOT NULL REFERENCES edicola_private.profiles(owner_id) ON DELETE CASCADE,
    id uuid NOT NULL,
    title text NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 80),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id,id)
);
CREATE TABLE IF NOT EXISTS edicola_private.chat_messages (
    owner_id text NOT NULL,
    conversation_id uuid NOT NULL,
    position integer NOT NULL CHECK (position BETWEEN 0 AND 199),
    request_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('user','assistant')),
    content text NOT NULL CHECK (length(content) <= CASE WHEN role='user' THEN 2000 ELSE 32000 END),
    details jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details)='object' AND octet_length(details::text)<=200000),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id,conversation_id,position),
    UNIQUE (owner_id,conversation_id,request_id,role),
    FOREIGN KEY (owner_id,conversation_id) REFERENCES edicola_private.conversations(owner_id,id) ON DELETE CASCADE,
    CHECK ((role='user' AND position % 2=0) OR (role='assistant' AND position % 2=1))
);
CREATE INDEX IF NOT EXISTS conversations_recent ON edicola_private.conversations(owner_id,updated_at DESC,id);
REVOKE ALL ON edicola_private.chat_settings,edicola_private.conversations,edicola_private.chat_messages FROM PUBLIC,anon,authenticated,edicola_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON edicola_private.chat_settings,edicola_private.conversations,edicola_private.chat_messages TO edicola_app;
ALTER TABLE edicola_private.chat_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE edicola_private.chat_settings FORCE ROW LEVEL SECURITY;
ALTER TABLE edicola_private.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE edicola_private.conversations FORCE ROW LEVEL SECURITY;
ALTER TABLE edicola_private.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE edicola_private.chat_messages FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_chat_settings ON edicola_private.chat_settings;
CREATE POLICY own_chat_settings ON edicola_private.chat_settings TO edicola_app
USING (owner_id=current_setting('edicola.owner_id',true)) WITH CHECK (owner_id=current_setting('edicola.owner_id',true));
DROP POLICY IF EXISTS own_conversations ON edicola_private.conversations;
CREATE POLICY own_conversations ON edicola_private.conversations TO edicola_app
USING (owner_id=current_setting('edicola.owner_id',true)) WITH CHECK (owner_id=current_setting('edicola.owner_id',true));
DROP POLICY IF EXISTS own_chat_messages ON edicola_private.chat_messages;
CREATE POLICY own_chat_messages ON edicola_private.chat_messages TO edicola_app
USING (owner_id=current_setting('edicola.owner_id',true)) WITH CHECK (owner_id=current_setting('edicola.owner_id',true));
INSERT INTO edicola_private.schema_migrations(version) VALUES (4) ON CONFLICT (version) DO NOTHING;
COMMIT;
