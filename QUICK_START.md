# MTO Treasury System - Quick Start Guide

## 🚀 Production Deployment (5 Minutes)

### Prerequisites
- Docker & Docker Compose installed
- MariaDB/MySQL database running
- Node.js 18+ and Python 3.11+ installed

---

## Step 1: Environment Setup (1 minute)

Create `.env` file in project root:

```bash
# Database
MTO_DB_HOST=your-db-host
MTO_DB_NAME=property_system
MTO_DB_USER=mto_app
MTO_DB_PASSWORD=your-secure-password

# Security
MTO_JWT_SECRET=your-jwt-secret-min-32-chars-long
CORS_ORIGIN=http://localhost:3000

# Redis (REQUIRED for production)
REDIS_URL=redis://redis:6379/0

# Environment
MTO_ENV=production
```

---

## Step 2: Start Redis (30 seconds)

```bash
docker-compose up -d redis

# Verify
redis-cli ping  # Should return: PONG
```

**⚠️ CRITICAL**: Redis is required in production. The system will not start without it.

---

## Step 3: Database Setup (1 minute)

```bash
# Run migrations
alembic upgrade head

# Verify
alembic current  # Should show: b2c3d4e5f6a1
```

---

## Step 4: Start Backend (1 minute)

```bash
# Install dependencies (first time only)
pip install -r requirements.txt

# Start server
python backend/main.py

# Or use gunicorn for production:
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8001
```

Backend will be available at: `http://localhost:8001`

---

## Step 5: Start Frontend (2 minutes)

```bash
cd frontend

# Install dependencies (first time only)
npm install

# Build
npm run build

# Start
npm start

# Or use PM2 for production:
pm2 start npm --name "mto-frontend" -- start
```

Frontend will be available at: `http://localhost:3000`

---

## Verification Checklist

### Health Checks
```bash
# Backend health
curl http://localhost:8001/healthz
# Should return: {"status":"healthy"}

# Frontend health
curl http://localhost:3000
# Should return: HTML page

# Redis health
redis-cli ping
# Should return: PONG
```

### Functional Tests
- [ ] Open `http://localhost:3000` in browser
- [ ] Login with admin credentials
- [ ] Dashboard loads with data
- [ ] Public property search works
- [ ] SOA download works

---

## Default Credentials

**Admin User:**
- Username: `admin`
- Password: Check your database or create via:
  ```bash
  python backend/scripts/create_admin.py
  ```

---

## Common Issues

### Issue: "REDIS_URL is required in production"
**Solution**: Set `REDIS_URL=redis://redis:6379/0` in your `.env` file

### Issue: "Database connection failed"
**Solution**: Check `MTO_DB_HOST`, `MTO_DB_USER`, and `MTO_DB_PASSWORD` in `.env`

### Issue: "Migration failed"
**Solution**: 
```bash
# Check current state
alembic current

# If out of sync, stamp the current version
alembic stamp head
```

### Issue: "Frontend can't connect to backend"
**Solution**: Check `CORS_ORIGIN` in `.env` matches your frontend URL

---

## Monitoring

### Key Metrics
- Request rate: Check application logs
- Error rate: Check `logs/error.log`
- Redis status: `redis-cli ping`
- Database connections: Check MariaDB status

### Log Files
- Application: `logs/system.log`
- Errors: `logs/error.log`
- Audit: `logs/mto_audit_*.json`

---

## Maintenance

### Daily
- Check error logs: `tail -f logs/error.log`
- Verify Redis is running: `redis-cli ping`
- Check disk space for backups

### Weekly
- Review audit logs
- Check database size
- Verify backup jobs completed

### Monthly
- Review security logs
- Update dependencies
- Performance testing

---

## Scaling

### Current Capacity
- **1k users**: ✅ Ready
- **10k users**: ✅ Ready (with Redis)
- **100k users**: ⚠️ Needs load balancer + DB tuning

### Horizontal Scaling
To scale beyond 10k users:
1. Add load balancer (nginx/HAProxy)
2. Run multiple backend workers
3. Use Redis for session storage
4. Optimize database queries
5. Add read replicas for database

---

## Support

### Documentation
- **Full deployment guide**: `DEPLOYMENT_CHECKLIST.md`
- **Scaling issues**: `docs/SCALING_FIXES.md`
- **Production readiness**: `docs/PRODUCTION_READINESS_SUMMARY.md`
- **Complete journey**: `docs/JOURNEY_SUMMARY.md`

### Quick Commands
```bash
# View logs
tail -f logs/system.log

# Restart backend
pkill -f "python backend/main.py"
python backend/main.py

# Restart frontend
pm2 restart mto-frontend

# Restart Redis
docker-compose restart redis

# Check database
mysql -u mto_app -p property_system
```

---

## Emergency Contacts

- **Technical Issues**: Check `docs/` folder
- **Database Issues**: Review `migrations/` folder
- **Security Issues**: Review `docs/SCALING_FIXES.md`

---

## Success Criteria

Deployment is successful when:
- ✅ All services are running
- ✅ Health checks pass
- ✅ Users can login
- ✅ Dashboard shows data
- ✅ No errors in logs

---

## Production Checklist

Before going live:
- [ ] Redis is running
- [ ] `REDIS_URL` is set
- [ ] Database migrations applied
- [ ] All tests pass
- [ ] Monitoring is active
- [ ] Backups are configured
- [ ] Team is trained

**When all boxes are checked, you're ready! 🎉**

---

**Version**: 1.0  
**Last Updated**: June 1, 2026  
**Status**: Production Ready (Score: 7.3/10)
