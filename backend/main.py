# -*- coding: utf-8 -*-
"""
MTO Treasury System API Server Entry Point.
Wait for the database, configure SSL certificates, and launch uvicorn.
"""
import os
import uvicorn
from dotenv import load_dotenv

# Load environment variables before doing anything else
load_dotenv()

# Import the configured FastAPI application instance
from backend.app_factory import app
from backend.database import wait_for_db

if __name__ == "__main__":
    # Wait for MariaDB to be ready before accepting traffic.
    # On Windows with XAMPP, the DB takes 5–15s to start after boot.
    # This prevents the server from crashing due to a startup race condition.
    wait_for_db(max_attempts=10, base_delay=2.0)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_path = os.path.join(base_dir, "certs", "cert.pem")
    key_path = os.path.join(base_dir, "certs", "key.pem")

    if os.path.exists(cert_path) and os.path.exists(key_path):
        print("Starting Secure API (HTTPS) on port 8001...")
        uvicorn.run(app, host="0.0.0.0", port=8001, ssl_keyfile=key_path, ssl_certfile=cert_path)
    else:
        print("Starting Standard API (HTTP) on port 8001 - SSL Certs not found.")
        uvicorn.run(app, host="0.0.0.0", port=8001)
