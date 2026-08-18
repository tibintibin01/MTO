# 🏛️ MTO Treasury Management System

An enterprise-grade, security-hardened treasury management solution for municipal governments. Built with a focus on data integrity, audit-readiness, and performance.

## Architecture

The system consists of three components:

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Backend API** | FastAPI (Python 3.11+) | REST API, business logic, PDF generation, job queue |
| **Web Portal** | Next.js 14 (React 18, TypeScript) | Public taxpayer lookup + admin dashboard (PWA) |
| **Desktop Client** | CustomTkinter (Python) | Full-featured cashier/admin workstation |

**Database:** MariaDB 10.11 (production) / SQLite (tests)
**Auth:** JWT (HS256) with httpOnly cookies, refresh tokens, RBAC
**Observability:** Prometheus + Grafana, Sentry, structured JSON logging

See [docs/architecture.md](docs/architecture.md) for the full component diagram.

## 🚀 Quick Start (Local Development)

### Prerequisites
- Python 3.9+
- Node.js 20+ (for the web portal)
- MariaDB/MySQL (or XAMPP on Windows)

### Backend Setup
```bash
# Create and activate virtual environment
python -m venv venv
source venv/Scripts/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template and fill in values
cp .env.template .env

# Generate HTTPS certificates (required)
python backend/generate_certs.py

# Start the Backend Server (Port 8001)
python backend/main.py
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev    # Development server on port 3000
```

### Docker (Production)
```bash
# Fill in .env first, then:
docker compose up -d
```

## 🛡️ Security Features
- **End-to-End Encryption:** Enforced HTTPS with self-signed certificate management
- **Role-Based Access Control (RBAC):** Granular permissions via signed JWT tokens
- **CSRF Protection:** Double-submit cookie pattern on the web portal
- **CORS Protection:** Whitelisted origins with explicit methods/headers
- **Rate Limiting:** Per-IP and per-user limits (Redis-backed in production)
- **HSTS:** Strict Transport Security headers on all responses
- **Audit Logging:** Immutable, append-only audit trail for all admin actions
- **Account Lockout:** 5 failed attempts → 5-minute lockout
- **Password Policy:** 12+ chars, mixed case, digits, special characters, bcrypt cost 12

## 🧬 Disaster Recovery
- **Hybrid Backups:** Automated Local, USB, and S3-compatible cloud sync
- **Encrypted Cloud Copies:** SQL dumps are compressed and protected with AES-256-GCM before upload; raw SQL is never sent to object storage
- **Data Integrity:** SHA256 checksum verification for every backup
- **Cloud Safety Limits:** Signed manifests, post-upload checks, a configurable byte ceiling, and complete-set retention
- **Cloudflare R2 Setup:** Follow the guarded [Phase 2 R2 runbook](docs/CLOUDFLARE_R2_BACKUP.md); configuration does not enable live uploads
- **Scheduled Automation:** Configurable daily/weekly backup schedule
- **Pre-Restore Safety:** Automatic safety backup before any restore operation

## 🧪 Quality Assurance
```bash
# Run the full test suite (113 tests)
pytest tests/ --ignore=tests/test_ui_modules.py --ignore=tests/load

# Run with coverage
pytest tests/ --ignore=tests/test_ui_modules.py --ignore=tests/load --cov=backend

# Frontend lint
cd frontend && npm run lint
```

## 🗺️ Documentation
- **Architecture Diagram:** [docs/architecture.md](docs/architecture.md)
- **API Reference:** [https://127.0.0.1:8001/docs](https://127.0.0.1:8001/docs) (Server must be running)
- **Client Setup:** [CLIENT_SETUP.md](CLIENT_SETUP.md)

## Deployment

The CI/CD pipeline (`.github/workflows/`) runs:
1. Lint (Black, Flake8, Mypy) + Security scan (Bandit, pip-audit)
2. Full test suite with coverage
3. Docker image build (SHA-tagged, never `:latest`)
4. Trivy container scan (blocks on HIGH/CRITICAL CVEs)
5. Staging deploy → health check → manual approval → production deploy

See `k8s/` for Kubernetes manifests and `infra/` for Prometheus/nginx configs.

---
*Built for Municipal Transparency and Efficiency.*
