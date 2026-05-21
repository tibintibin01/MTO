#!/bin/bash
# =============================================================================
# MTO Treasury System — Docker MariaDB Initialisation Script
# =============================================================================
# Mounted at /docker-entrypoint-initdb.d/ and executed ONCE by the MariaDB
# container on first startup (when the data volume is empty).
#
# MariaDB already creates the database and user from MARIADB_DATABASE /
# MARIADB_USER / MARIADB_PASSWORD env vars, but only grants basic access.
# This script upgrades those grants to the full least-privilege set the
# application needs (including LOCK TABLES for mysqldump backups and
# CREATE/ALTER/DROP for Alembic migrations).
#
# Environment variables injected by docker-compose:
#   MARIADB_DATABASE  — the application database name  (e.g. property_system)
#   MARIADB_USER      — the application user            (e.g. mto_app)
# =============================================================================
set -e

echo "[MTO Init] Granting least-privilege permissions to '${MARIADB_USER}'..."

mariadb --user=root --password="${MARIADB_ROOT_PASSWORD}" <<-EOSQL
    -- Ensure the database exists with the correct character set.
    CREATE DATABASE IF NOT EXISTS \`${MARIADB_DATABASE}\`
        CHARACTER SET utf8mb4
        COLLATE utf8mb4_unicode_ci;

    -- The user already exists (created by MARIADB_USER / MARIADB_PASSWORD).
    -- Upgrade its grants to the full least-privilege set.
    --
    -- Granted:
    --   SELECT, INSERT, UPDATE, DELETE  — normal CRUD
    --   CREATE, ALTER, DROP, INDEX      — Alembic schema migrations
    --   REFERENCES                      — foreign key constraints
    --   LOCK TABLES                     — mysqldump backup
    --
    -- NOT granted: FILE, SUPER, PROCESS, RELOAD, SHUTDOWN, GRANT OPTION,
    --              CREATE USER, or any global (*.*) privilege.

    GRANT SELECT, INSERT, UPDATE, DELETE,
          CREATE, ALTER, DROP, INDEX,
          REFERENCES, LOCK TABLES
        ON \`${MARIADB_DATABASE}\`.*
        TO '${MARIADB_USER}'@'%';

    FLUSH PRIVILEGES;
EOSQL

echo "[MTO Init] Grants applied successfully for '${MARIADB_USER}' on '${MARIADB_DATABASE}'."
