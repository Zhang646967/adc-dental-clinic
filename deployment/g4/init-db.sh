#!/bin/sh
# Official PostgreSQL image: runs ONLY when its new data directory is empty.
set -eu
[ "$POSTGRES_DB" = adc_rc_demo ]
[ "$POSTGRES_USER" = adc_g4_admin ]
[ "${#G4_OWNER_DB_PASSWORD}" -ge 32 ]
[ "${#G4_RUNTIME_DB_PASSWORD}" -ge 32 ]
psql --no-psqlrc --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
\getenv owner_password G4_OWNER_DB_PASSWORD
\getenv runtime_password G4_RUNTIME_DB_PASSWORD
CREATE ROLE adc_g4_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'owner_password';
CREATE ROLE adc_g4_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'runtime_password';
ALTER DATABASE adc_rc_demo OWNER TO adc_g4_owner;
REVOKE ALL ON DATABASE adc_rc_demo FROM PUBLIC;
GRANT CONNECT ON DATABASE adc_rc_demo TO adc_g4_owner, adc_g4_runtime;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO adc_g4_owner;
GRANT USAGE ON SCHEMA public TO adc_g4_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE adc_g4_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO adc_g4_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE adc_g4_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO adc_g4_runtime;
SQL
printf 'G4 owner/runtime roles initialized in the new isolated database.\n'
