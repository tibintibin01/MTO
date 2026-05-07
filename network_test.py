import json
import os
import socket
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(BASE_DIR, "_vendor")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.append(VENDOR_DIR)

try:
    import mysql.connector
except ImportError:
    try:
        import pymysql as mysql
    except ImportError:
        mysql = None
else:
    mysql = mysql.connector

DB_CONFIG_PATH = os.path.join(BASE_DIR, "db_config.json")


def load_runtime_config():
    if not os.path.exists(DB_CONFIG_PATH):
        raise FileNotFoundError(f"Missing config: {DB_CONFIG_PATH}")

    with open(DB_CONFIG_PATH, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    runtime = config.get("runtime", config)
    return {
        "host": str(runtime.get("host", "")).strip(),
        "port": int(runtime.get("port", 3306) or 3306),
        "user": str(runtime.get("user", "")).strip(),
        "password": runtime.get("password", ""),
        "database": str(runtime.get("database", "")).strip(),
        "connect_timeout": int(runtime.get("connect_timeout", 5) or 5),
    }


def test_socket_connection(host, port, timeout):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"Socket connection to {host}:{port} succeeded."
    except Exception as exc:
        return False, f"Socket connection to {host}:{port} failed: {exc}"


def test_mysql_connection(cfg):
    if mysql is None:
        return False, (
            "mysql-connector-python is not installed on this PC. "
            "Run: python -m pip install mysql-connector-python"
        )

    try:
        conn = mysql.connect(
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            connect_timeout=cfg["connect_timeout"],
        )
        conn.close()
        return True, "MySQL login succeeded."
    except Exception as exc:
        return False, f"MySQL login failed: {exc}"


def main():
    try:
        cfg = load_runtime_config()
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    print("MTO network test")
    print(f"Host: {cfg['host']}")
    print(f"Port: {cfg['port']}")
    print(f"Database: {cfg['database']}")
    print(f"User: {cfg['user']}")
    print("")

    if cfg["host"] in {"127.0.0.1", "localhost"}:
        print("[WARNING] Host is set to localhost/127.0.0.1.")
        print("          On a client PC, this points to the client itself, not your server.")
        print("          Replace it with the server PC's LAN IP, for example 192.168.x.x.")
        print("")

    ok, message = test_socket_connection(cfg["host"], cfg["port"], cfg["connect_timeout"])
    print(("[OK] " if ok else "[FAIL] ") + message)

    ok2, message2 = test_mysql_connection(cfg)
    print(("[OK] " if ok2 else "[FAIL] ") + message2)

    if ok and ok2:
        print("")
        print("Network and database access look good.")
        return 0

    print("")
    print("If socket failed, check server IP, firewall, MySQL bind address, and port 3306 access.")
    print("If socket worked but MySQL login failed, check username/password/database permissions.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
