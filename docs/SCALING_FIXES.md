# Scaling Fixes - Production Readiness

## Status: 6.5/10 → Target: 8.0/10

---

## ✅ COMPLETED - Production Blockers

### 1. Dead Code Removal
- **Issue**: `lib/api.ts` was never imported by any page
- **Fix**: Deleted `frontend/app/lib/api.ts`
- **Impact**: Cleaner codebase, no runtime impact

### 2. Unused Dependency
- **Issue**: `@tanstack/react-query` was installed but never used
- **Fix**: Removed from `package.json`
- **Impact**: Smaller bundle size, faster installs

---

## 🔧 SHOULD FIX BEFORE SCALING

### 3. Idempotency Middleware Double-Session Issue

**Problem**: The idempotency middleware opens two separate database sessions:
```python
# Session 1: Check for existing key
with SessionLocal() as db:
    existing = db.query(IdempotencyKey).filter(...).first()
    if existing:
        return cached_response

# ... process request ...

# Session 2: Store new key
with SessionLocal() as db:
    record = IdempotencyKey(...)
    db.add(record)
    db.commit()
```

**Why it's bad**:
- Race condition: Two requests with the same key can both pass the check
- Inefficient: Opens/closes connection twice per request
- Transaction boundary unclear: Check and store should be atomic

**Fix**: Use a single session with proper transaction handling:
```python
with SessionLocal() as db:
    # Check
    existing = db.query(IdempotencyKey).filter(...).first()
    if existing:
        return cached_response
    
    # Process request (pass db to handler if needed)
    response = await call_next(request)
    
    # Store (same transaction)
    record = IdempotencyKey(...)
    db.add(record)
    db.commit()
```

**Alternative**: Use database-level locking:
```python
# PostgreSQL: SELECT ... FOR UPDATE SKIP LOCKED
# SQLite: BEGIN IMMEDIATE
```

**Priority**: Medium (works fine at low scale, becomes a problem at 10k+ concurrent users)

---

### 4. In-Memory Rate Limiting

**Problem**: Rate limiter falls back to in-memory storage when Redis is not available:
```python
_limiter_kwargs: dict = {}
if REDIS_URL:
    try:
        _limiter_kwargs["storage_uri"] = REDIS_URL
    except Exception:
        pass  # Falls back to in-memory

limiter = Limiter(key_func=get_remote_address, **_limiter_kwargs)
```

**Why it's bad**:
- Each worker has its own rate limit counter
- A user can bypass limits by hitting different workers
- Horizontal scaling breaks rate limiting entirely

**Example**:
- Limit: 10 requests/minute
- Workers: 4
- Actual limit per user: 40 requests/minute (10 per worker)

**Fix**: Require Redis in production:
```python
if MTO_ENV == "production" and not REDIS_URL:
    raise RuntimeError("REDIS_URL is required in production for rate limiting")

_limiter_kwargs = {"storage_uri": REDIS_URL} if REDIS_URL else {}
```

**Deployment checklist**:
1. Add Redis to `docker-compose.yml` (already exists)
2. Set `REDIS_URL=redis://redis:6379/0` in `.env`
3. Update `k8s/deployment.yaml` to include Redis sidecar or external service
4. Add health check for Redis connection

**Priority**: High (breaks at scale, easy to fix)

---

### 5. System Stats Cache Staleness

**Problem**: Dashboard stats are only refreshed:
- On server startup
- After payment posting
- After bulk import

**Why it's bad**:
- Stats can be hours or days old
- "Collections Today" doesn't update until a payment is posted
- Users see stale data and lose trust in the system

**Current refresh triggers**:
```python
# backend/main.py (startup)
refresh_system_stats(db_session=db)

# backend/services/payment_service.py (after payment)
refresh_system_stats(db_session=db_session)

# backend/services/import_service.py (after import)
refresh_system_stats(db_session=db_session)
```

**Fix**: Add scheduled refresh to maintenance thread:
```python
# backend/services/job_service.py
def _refresh_dashboard_stats():
    """
    Refreshes dashboard stats every 5 minutes.
    Ensures the dashboard shows current data even when no payments are posted.
    """
    try:
        from backend.database import SessionLocal
        from backend.services.stats_service import refresh_system_stats
        
        with SessionLocal() as db:
            refresh_system_stats(db_session=db)
        
        mto_logger.info("Dashboard stats refreshed by maintenance thread.")
    except Exception as e:
        mto_logger.warning(f"Dashboard stats refresh failed (non-fatal): {e}")

# Add to maintenance loop
def _maintenance_loop():
    while True:
        time.sleep(300)  # 5 minutes
        _recover_stale_jobs()
        _cleanup_expired_idempotency_keys()
        _cleanup_expired_refresh_tokens()
        _refresh_dashboard_stats()  # NEW
```

**Alternative**: Use a proper cache with TTL:
```python
# Redis-backed cache with 5-minute TTL
@cache(ttl=300)
def get_dashboard_summary(db_session: Session):
    ...
```

**Priority**: Medium (UX issue, not a blocker)

---

## 📝 CODE QUALITY DEBT

### 6. Deferred Imports Throughout Backend

**Problem**: Many files use deferred imports to avoid circular dependencies:
```python
def some_function():
    from backend.models import Property  # Deferred import
    from backend.services.stats_service import refresh_system_stats
    ...
```

**Why it's bad**:
- Slower function execution (import on every call)
- Harder to track dependencies
- Hides circular dependency issues

**Fix**: Restructure modules to eliminate circular dependencies:
1. Move shared types to `backend/types.py`
2. Move shared utilities to `backend/utils.py`
3. Use dependency injection instead of direct imports
4. Consider splitting large service files

**Priority**: Low (code quality, not a blocker)

---

### 7. Heavy Inline Styles Mixed with Tailwind

**Problem**: Frontend mixes Tailwind classes with inline styles:
```tsx
<div className="flex gap-4" style={{ marginTop: '20px', padding: '10px' }}>
```

**Why it's bad**:
- Inconsistent styling approach
- Harder to maintain
- Breaks Tailwind's utility-first philosophy
- Can't use Tailwind's responsive/hover variants on inline styles

**Fix**: Convert all inline styles to Tailwind classes:
```tsx
// Before
<div className="flex gap-4" style={{ marginTop: '20px', padding: '10px' }}>

// After
<div className="flex gap-4 mt-5 p-2.5">
```

**Priority**: Low (code quality, not a blocker)

---

## 🎯 IMPLEMENTATION PLAN

### Phase 1: Quick Wins (1 hour)
1. ✅ Remove dead code (`lib/api.ts`)
2. ✅ Remove unused dependency (`@tanstack/react-query`)
3. Add Redis requirement check for production
4. Add scheduled stats refresh to maintenance thread

### Phase 2: Medium Effort (2-4 hours)
5. Fix idempotency middleware double-session
6. Add Redis deployment documentation
7. Add health checks for Redis

### Phase 3: Code Quality (4-8 hours)
8. Audit and fix deferred imports
9. Convert inline styles to Tailwind
10. Add linting rules to prevent regression

---

## 📊 EXPECTED IMPACT

| Fix | Current Score | After Fix | Effort |
|-----|---------------|-----------|--------|
| Dead code removal | 6.5 | 6.6 | 5 min |
| Unused dependency | 6.6 | 6.7 | 5 min |
| Redis requirement | 6.7 | 7.0 | 15 min |
| Stats refresh | 7.0 | 7.3 | 30 min |
| Idempotency fix | 7.3 | 7.6 | 2 hours |
| Code quality | 7.6 | 8.0 | 8 hours |

**Target**: 8.0/10 (production-ready for 10k users)

---

## 🚀 DEPLOYMENT CHECKLIST

Before deploying to production:

- [ ] Redis is running and accessible
- [ ] `REDIS_URL` is set in environment
- [ ] Rate limiting is tested with Redis backend
- [ ] Dashboard stats refresh every 5 minutes
- [ ] Idempotency middleware uses single session
- [ ] All tests pass (backend + frontend)
- [ ] Load testing confirms no rate limit bypass
- [ ] Monitoring alerts for Redis downtime

---

## 📈 SCALE TARGETS

| Users | Current Status | After Fixes |
|-------|----------------|-------------|
| 1k | ✅ Works fine | ✅ Works fine |
| 10k | ⚠️ Rate limit bypass | ✅ Works fine |
| 100k | ❌ Needs Redis + horizontal scaling | ⚠️ Needs load balancer + DB tuning |

