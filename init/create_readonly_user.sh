#!/bin/bash
set -e

if [ -z "$QQL_READONLY_PASSWORD" ]; then
  echo "QQL_READONLY_PASSWORD is not set; skipping read-only user creation."
  exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  DO
  \$\$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qql_readonly') THEN
      CREATE ROLE qql_readonly LOGIN PASSWORD '$QQL_READONLY_PASSWORD';
    END IF;
  END
  \$\$;

  GRANT CONNECT ON DATABASE $POSTGRES_DB TO qql_readonly;
  GRANT USAGE ON SCHEMA public TO qql_readonly;
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO qql_readonly;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO qql_readonly;
EOSQL