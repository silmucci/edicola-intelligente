-- SOLO LETTURA. Eseguire nel SQL Editor Supabase dopo 001/002.
-- Legge cataloghi e versioni, MAI profili, fonti, briefing o credenziali.
-- Un risultato vuoto NON equivale a un controllo superato: devono esistere
-- un ruolo, quattro tabelle, tre policy e le versioni 1 e 2.
BEGIN TRANSACTION READ ONLY;

SELECT r.rolname, r.rolcanlogin, r.rolsuper, r.rolcreatedb, r.rolcreaterole,
       r.rolreplication, r.rolbypassrls, r.rolinherit,
       NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid) AS no_memberships,
       NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'edicola_private'
                   AND nspowner = r.oid) AS not_schema_owner,
       NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = 'edicola_private' AND c.relowner = r.oid) AS not_table_owner
FROM pg_roles r WHERE r.rolname = 'edicola_app';

SELECT has_schema_privilege('edicola_app', 'edicola_private', 'USAGE') AS app_usage,
       has_schema_privilege('edicola_app', 'edicola_private', 'CREATE') AS app_create;

SELECT c.relname, c.relrowsecurity AS rls, c.relforcerowsecurity AS force_rls,
       has_table_privilege('edicola_app', c.oid, 'SELECT') AS app_select,
       has_table_privilege('edicola_app', c.oid, 'INSERT') AS app_insert,
       has_table_privilege('edicola_app', c.oid, 'UPDATE') AS app_update,
       has_table_privilege('edicola_app', c.oid, 'DELETE') AS app_delete,
       has_table_privilege('edicola_app', c.oid, 'TRUNCATE') AS app_truncate,
       has_table_privilege('edicola_app', c.oid, 'TRIGGER') AS app_trigger,
       has_table_privilege('edicola_app', c.oid, 'REFERENCES') AS app_references
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'edicola_private' AND c.relkind IN ('r', 'p') ORDER BY c.relname;

-- Devono esserci esattamente tre policy, una per tabella personale, TO edicola_app,
-- cmd ALL, con owner_id = current_setting('edicola.owner_id', true)
-- sia in qual che in with_check. Policy permissive ulteriori possono aprire accessi.
SELECT tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies WHERE schemaname = 'edicola_private' ORDER BY tablename, policyname;

-- Per PUBLIC/anon/authenticated nessun accesso; per edicola_app nessun grant option.
SELECT grantee, table_name, privilege_type, is_grantable
FROM information_schema.table_privileges
WHERE table_schema = 'edicola_private'
  AND grantee IN ('PUBLIC', 'anon', 'authenticated', 'edicola_app')
ORDER BY grantee, table_name, privilege_type;

SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns WHERE table_schema = 'edicola_private'
ORDER BY table_name, ordinal_position;

SELECT c.relname, con.conname, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'edicola_private' ORDER BY c.relname, con.conname;

SELECT version FROM edicola_private.schema_migrations ORDER BY version;
ROLLBACK;
