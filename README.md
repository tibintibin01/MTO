# 🏛️ MTO Treasury Management System

An enterprise-grade, security-hardened treasury management solution for municipal governments. Built with a focus on data integrity, audit-readiness, and performance.

## 🚀 Quick Start (Local Development)

### 1. Prerequisites
- Python 3.9+
- SQLite (Built-in)

### 2. Setup Environment
```bash
# Create and activate virtual environment
python -m venv venv
source venv/Scripts/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Initialize Security (HTTPS)
The system requires SSL certificates for secure communication.
```bash
python backend/generate_certs.py
```

### 4. Run the System
```bash
# Start the Backend Server (Port 8001)
python backend/main.py

# Launch the Desktop Dashboard (Separate Terminal)
python dashboard.py
```

## 🛡️ Security Features
- **End-to-End Encryption:** Enforced HTTPS with self-signed certificate management.
- **Role-Based Access Control (RBAC):** Granular permissions via signed JWT tokens.
- **CORS Protection:** Whitelisted local origins to prevent unauthorized web access.
- **Rate Limiting:** Built-in defense against brute-force and DoS attacks.
- **Audit Logging:** Centralized, rotating logs for all administrative actions.

## 🧬 Disaster Recovery
- **Hybrid Backups:** Automated Local, USB, and Cloud synchronization.
- **Data Integrity:** SHA256 checksum generation for every backup to detect corruption.
- **Verification API:** Real-time health monitoring of the backup ecosystem.

## 🧪 Quality Assurance
To run the automated test suite:
```bash
pytest tests/test_api.py
```

## 🗺️ Documentation
- **Architecture Diagram:** [docs/architecture.md](docs/architecture.md)
- **API Reference:** [https://127.0.0.1:8001/docs](https://127.0.0.1:8001/docs) (Server must be running)
- **Client Setup:** [CLIENT_SETUP.md](CLIENT_SETUP.md)

---
*Built with ❤️ for Municipal Transparency and Efficiency.*
