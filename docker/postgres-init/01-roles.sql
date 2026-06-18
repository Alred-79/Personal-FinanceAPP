-- WS2 Row-Level Security role model (see .env.example).
--
-- Runs once at first container init, as the POSTGRES_USER (pf_owner — a superuser
-- that owns the schema, runs migrations, and bypasses RLS). It creates the
-- restricted request role pf_app: NOSUPERUSER, no BYPASSRLS, only CRUD — so when
-- the app connects as pf_app the tenant-isolation policies actually enforce
-- (a superuser would bypass them even with FORCE).
--
-- To run with RLS enforcing: set ENABLE_RLS=true, point the app's DATABASE_URL at
-- pf_app, and ALEMBIC_DATABASE_URL + SCHEDULER_DATABASE_URL at pf_owner (so
-- migrations and the all-users scheduler jobs bypass RLS). See docker-compose.yml.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pf_app') THEN
    CREATE ROLE pf_app LOGIN PASSWORD 'pf_app' NOSUPERUSER;
  END IF;
END $$;

GRANT CONNECT ON DATABASE finance_tracker TO pf_app;
GRANT USAGE ON SCHEMA public TO pf_app;
-- Tables/sequences that already exist (none at first init; migrations create them).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pf_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pf_app;
-- And everything pf_owner creates later (the migrations): grant pf_app CRUD.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pf_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO pf_app;
