-- =============================================================================
-- MTO Treasury System — Least-Privilege Database User Provisioning
-- =============================================================================
-- Run this script ONCE as the MariaDB/MySQL root user before starting the app.
--
-- XAMPP (Windows):
--   C:\xampp\mysql\bin\mysql.exe -u root < scripts\create_db_user.sql
--
-- Docker / Linux:
--   mysql -u root -p < scripts/create_db_user.sql
--
-- Or use the automated helper which substitutes the real password from .env:
--   python scripts/create_db_user.py
--
-- IMPORTANT: Replace 'CHANGE_ME' below with the same value you set for
-- MTO_DB_PASSWORD in your .env file before running this script directly.
-- The Python helper (create_db_user.py) does this substitution automatically.
-- =============================================================================

-- 1. Create the application database if it does not already exist.
--    CHARACTER SET and COLLATION match the Alembic migration defaults.
CREATE DATABASE IF NOT EXISTS `property_system`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- 2. Create the application user.
--    'localhost' restricts the account to local connections only.
--    For Docker deployments where the API container connects over the internal
--    network, change 'localhost' to '%' or the specific container subnet.
CREATE USER IF NOT EXISTS 'mto_app'@'localhost'
    IDENTIFIED BY 'CHANGE_ME';

-- Also allow connections from the Docker bridge network (172.x.x.x).
-- Remove this line if you are running locally only (XAMPP).
CREATE USER IF NOT EXISTS 'mto_app'@'%'
    IDENTIFIED BY 'CHANGE_ME';

-- 3. Grant only the permissions the application actually needs.
--
--    SELECT, INSERT, UPDATE, DELETE  — normal CRUD operations
--    CREATE, ALTER, DROP, INDEX      — Alembic schema migrations
--    REFERENCES                      — foreign key constraints
--    LOCK TABLES                     — mysqldump backup (SELECT + LOCK TABLES)
--
--    NOT granted: FILE, SUPER, PROCESS, RELOAD, SHUTDOWN, GRANT OPTION,
--                 CREATE USER, or any global (*.*) privilege.
--    This means a compromised mto_app session cannot:
--      - Read files from the server filesystem (FILE)
--      - Kill other connections or change global variables (SUPER)
--      - Access any database other than property_system
--      - Create new users or escalate privileges (GRANT OPTION)

GRANT SELECT, INSERT, UPDATE, DELETE,
      CREATE, ALTER, DROP, INDEX,
      REFERENCES, LOCK TABLES
    ON `property_system`.*
    TO 'mto_app'@'localhost';

GRANT SELECT, INSERT, UPDATE, DELETE,
      CREATE, ALTER, DROP, INDEX,
      REFERENCES, LOCK TABLES
    ON `property_system`.*
    TO 'mto_app'@'%';

-- 4. Apply the new grants immediately.
FLUSH PRIVILEGES;

-- 5. Verification — run this block manually to confirm the setup.
--    Expected output: two rows for mto_app@localhost and mto_app@%,
--    each showing only property_system grants.
--
-- SHOW GRANTS FOR 'mto_app'@'localhost';
-- SHOW GRANTS FOR 'mto_app'@'%';
