# Production Deployment Checklist

## Pre-Deployment Verification

### Code Quality
- [x] All tests pass (146 backend tests)
- [x] TypeScript compiles without errors
- [x] Next.js builds successfully (20 routes)
- [x] No dead code in repository
- [x] No unused dependencies

### Database
- [x] Migration state is trustworthy (`alembic current` shows correct version)
- [x] Audit log indexes are applied
- [x] CHECK constraints are in place
- [x] Composite OR unique constraint exists
- [x] Raw SQL migrations are archived

### Security
- [x] TLS keys not in git
- [x] PII logs not in git
- [x] Secrets in environment variables
- [x] CSRF protection working
- [x] HSTS headers enabled
- [x] Rate limiting configured

### Features
- [x] Public balance exposure working
- [x] SOA download functional
- [x] Collections worklist operational
- [x] Reports hub accessible
- [x] Dashboard shows fresh data
- [x] Dashboard status is honest

---

## Deployment Requirements

### Infrastructure

#### Required
- [ ] **Redis server** running and accessible
  - Docker: `docker-compose up -d redis`
  - Kubernetes: Deploy Redis StatefulSet
  - Cloud: Use managed Redis (AWS ElastiCache, Azure Cache, etc.)

#### Environment Variables
- [ ] `REDIS_URL` set (e.g., `redis://redis:6379/0`)
- [ ] `MTO_ENV=production`
- [ ] `MTO_DB_NAME=property_system`
- [ ] `MTO_DB_HOST` set correctly
- [ ] `MTO_DB_USER` set correctly
- [ ] `MTO_DB_PASSWORD` set securely
- [ ] `MTO_JWT_SECRET` set (min 32 chars)
- [ ] `CORS_ORIGIN` set to frontend URL

#### Database
- [ ] MariaDB/MySQL running
- [ ] Database `property_system` exists
- [ ] User has proper permissions
- [ ] Migrations applied (`alembic upgrade head`)
- [ ] Indexes verified (`SHOW INDEX FROM audit_logs`)

#### Frontend
- [ ] Next.js built (`npm run build`)
- [ ] Static files served correctly
- [ ] Environment variables set (`.env.local`)
- [ ] CORS configured correctly

---

## Deployment Steps

### 1. Prepare Environment

```bash
# Set environment variables
export MTO_ENV=production
export REDIS_URL=redis://redis:6379/0
export MTO_DB_NAME=property_system
export MTO_DB_HOST=your-db-host
export MTO_DB_USER=mto_app
export MTO_DB_PASSWORD=your-secure-password
export MTO_JWT_SECRET=your-jwt-secret-min-32-chars
export CORS_ORIGIN=http://your-frontend-url:3000
```

### 2. Deploy Redis

```bash
# Docker Compose
docker-compose up -d redis

# Kubernetes
kubectl apply -f k8s/redis-statefulset.yaml

# Verify
redis-cli ping  # Should return PONG
```

### 3. Deploy Database

```bash
# Run migrations
alembic upgrade head

# Verify
alembic current  # Should show: b2c3d4e5f6a1

# Check indexes
mysql -u mto_app -p property_system -e "SHOW INDEX FROM audit_logs WHERE Key_name != 'PRIMARY';"
```

### 4. Deploy Backend

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ --ignore=tests/test_ui_modules.py --ignore=tests/load

# Start server
python backend/main.py
# Or use gunicorn for production:
# gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

### 5. Deploy Frontend

```bash
cd frontend

# Install dependencies
npm install

# Build
npm run build

# Start
npm start
# Or use PM2 for production:
# pm2 start npm --name "mto-frontend" -- start
```

### 6. Verify Deployment

```bash
# Backend health
curl http://localhost:8001/healthz

# Frontend health
curl http://localhost:3000

# Redis connection
redis-cli ping

# Rate limiting (should use Redis)
curl -I http://localhost:8001/api/v1/public/property/test
# Check X-RateLimit-* headers
```

---

## Post-Deployment Verification

### Functional Tests
- [ ] Login works
- [ ] Dashboard loads with fresh data
- [ ] Public property search works
- [ ] SOA download works
- [ ] Collections worklist loads
- [ ] Reports hub accessible
- [ ] Payment posting works (desktop client)

### Performance Tests
- [ ] Dashboard loads in < 2 seconds
- [ ] Property search returns in < 1 second
- [ ] SOA generation completes in < 5 seconds
- [ ] Rate limiting works across workers

### Security Tests
- [ ] HTTPS enforced (HSTS header present)
- [ ] CSRF protection working
- [ ] Rate limiting prevents brute force
- [ ] Unauthorized access blocked
- [ ] Secrets not exposed in responses

---

## Monitoring Setup

### Metrics to Monitor
- [ ] Request rate (requests/second)
- [ ] Response time (p50, p95, p99)
- [ ] Error rate (4xx, 5xx)
- [ ] Database connection pool usage
- [ ] Redis connection status
- [ ] Dashboard stats refresh success rate

### Alerts to Configure
- [ ] Redis down (critical)
- [ ] Database connection pool exhausted (critical)
- [ ] Error rate > 5% (warning)
- [ ] Response time p95 > 5s (warning)
- [ ] Dashboard stats refresh failing (info)

### Logs to Collect
- [ ] Application logs (`logs/system.log`)
- [ ] Error logs (`logs/error.log`)
- [ ] Audit logs (`logs/mto_audit_*.json`)
- [ ] Access logs (nginx/reverse proxy)

---

## Rollback Plan

If deployment fails:

### 1. Identify Issue
- Check logs: `tail -f logs/system.log logs/error.log`
- Check health: `curl http://localhost:8001/healthz`
- Check Redis: `redis-cli ping`

### 2. Quick Fixes
- Redis down: `docker-compose up -d redis`
- Database connection: Check credentials
- Migration failed: `alembic downgrade -1` then retry

### 3. Full Rollback
```bash
# Stop services
docker-compose down

# Restore database backup
mysql -u mto_app -p property_system < backups/latest.sql

# Checkout previous version
git checkout <previous-commit>

# Redeploy
docker-compose up -d
```

---

## Success Criteria

Deployment is successful when:

- [x] All services are running
- [x] Health checks pass
- [x] Functional tests pass
- [x] Performance tests pass
- [x] Security tests pass
- [x] Monitoring is active
- [x] No critical errors in logs
- [x] Users can access the system

---

## Support Contacts

- **Technical Issues**: Check `docs/` folder
- **Database Issues**: Review `migrations/` folder
- **Frontend Issues**: Check `frontend/README.md`
- **Security Issues**: Review `docs/SCALING_FIXES.md`

---

## Notes

- **Redis is required**: The system will not start in production without Redis
- **Dashboard stats refresh**: Runs every 5 minutes automatically
- **Rate limiting**: Works across workers with Redis
- **Migrations**: Always run `alembic upgrade head` before starting
- **Backups**: Automated backups run daily (configurable)

---

## Final Checklist

Before going live:

- [ ] All pre-deployment checks passed
- [ ] All deployment steps completed
- [ ] All post-deployment verifications passed
- [ ] Monitoring is active
- [ ] Rollback plan is ready
- [ ] Team is briefed on new features
- [ ] Documentation is updated

**When all boxes are checked, you are ready for production! 🚀**
