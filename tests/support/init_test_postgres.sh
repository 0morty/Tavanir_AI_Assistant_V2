#!/bin/sh
# Executed by the official Postgres entrypoint only when this test volume is new.
set -eu

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${TEST_POSTGRES_USERNAME:?TEST_POSTGRES_USERNAME is required}"
: "${TEST_POSTGRES_PASSWORD:?TEST_POSTGRES_PASSWORD is required}"
: "${TEST_ENVIRONMENT_ID:?TEST_ENVIRONMENT_ID is required}"

case "$TEST_POSTGRES_USERNAME" in
    test_admin|postgres)
        echo "The test login must be a separate non-administrator role." >&2
        exit 1
        ;;
esac

# psql variable quoting treats credentials and names as data, never SQL syntax.
# The marker is owned by test_admin; the test login can read but cannot change it.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set ON_ERROR_STOP=1 \
    --set test_username="$TEST_POSTGRES_USERNAME" \
    --set test_password="$TEST_POSTGRES_PASSWORD" \
    --set test_database="$POSTGRES_DB" \
    --set test_environment_id="$TEST_ENVIRONMENT_ID" <<'SQL'
BEGIN;

CREATE ROLE :"test_username"
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS
    PASSWORD :'test_password';

GRANT CONNECT, TEMPORARY ON DATABASE :"test_database" TO :"test_username";
GRANT USAGE, CREATE ON SCHEMA public TO :"test_username";

CREATE TABLE public.test_environment_guard (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    environment text NOT NULL CHECK (environment = 'test'),
    environment_id text NOT NULL CHECK (length(environment_id) > 0)
);

INSERT INTO public.test_environment_guard (singleton, environment, environment_id)
VALUES (true, 'test', :'test_environment_id');

REVOKE ALL ON TABLE public.test_environment_guard FROM PUBLIC, :"test_username";
GRANT SELECT ON TABLE public.test_environment_guard TO :"test_username";

COMMIT;
SQL
