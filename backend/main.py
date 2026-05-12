import os
import sys
from typing import List, Optional

try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
    File,
    UploadFile,
    Request,
    Response,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Add parent directory to path to import existing services
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import config as mto_config
from utils.secrets_manager import secrets
from utils.resilience import CircuitBreaker
from utils.metrics import MetricsManager

# Initialize Sentry Telemetry with Circuit Protection
SENTRY_DSN = os.getenv("SENTRY_DSN")
sentry_circuit = CircuitBreaker(name="SentryTelemetry", failure_threshold=3, recovery_timeout=300)

if SENTRY_AVAILABLE and SENTRY_DSN:
    def init_sentry():
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[FastApiIntegration()],
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )
        print(f"INFO: Sentry Telemetry INITIALIZED: {SENTRY_DSN[:20]}...")
    
    try:
        sentry_circuit.call(init_sentry)
    except Exception as e:
        print(f"WARNING: Sentry Initialization skipped due to circuit trip: {e}")
elif not SENTRY_AVAILABLE and SENTRY_DSN:
    print("WARNING: Sentry DSN provided but sentry_sdk NOT FOUND. Telemetry disabled.")

# --- REAL-TIME NOTIFICATIONS (WebSockets) ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: dict):
        import json
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except:
                # Connection might be stale
                pass

manager = ConnectionManager()

import db_manager as db
import backend.services.auth_service as auth_svc
import backend.services.property_service as prop_svc
import backend.services.payment_service as pay_svc
import backend.services.billing_service as bill_svc
import backend.services.system_service as sys_svc
import backend.services.search_service as search_svc
import receipt_generator as rg
from fastapi.responses import FileResponse
from backend.schemas import (
    PropertySaveSchema,
    ReceiptRecordSchema,
    LogActionSchema,
    UserUpdateSchema,
    PasswordResetSchema,
    BulkUpdateBarangaySchema,
)

app = FastAPI(
    title="MTO Treasury Management System",
    description="Professional Enterprise API for Municipal Treasury Operations. Includes Property Assessment, Billing, and Collection management with high-entropy security controls.",
    version="2.1.0",
    contact={
        "name": "MTO IT Support",
        "email": "support@mto.gov.ph",
    },
    license_info={
        "name": "Proprietary",
    },
    docs_url="/docs",
    redoc_url="/redoc"
)

# --- API VERSIONING (v2) ---
from fastapi import APIRouter
api_v2 = APIRouter(prefix="/api/v2")

# Register Versioned Router later in the file after dependencies are defined

# Rate Limiter Configuration - Supports Redis for Multi-Instance Scaling
REDIS_URL = os.getenv("REDIS_URL")
if REDIS_URL:
    from slowapi.util import get_remote_address
    limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)
    print(f"INFO: Rate Limiter is BACKED BY REDIS: {REDIS_URL}")
else:
    limiter = Limiter(key_func=get_remote_address)
    print("INFO: Rate Limiter is using IN-MEMORY storage.")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from utils.metrics import MetricsManager
import time

# --- OBSERVABILITY & TELEMETRY MIDDLEWARE ---
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """
    Unified middleware for Request ID correlation and Prometheus performance tracking.
    """
    from utils import set_request_id, get_request_id
    start_time = time.perf_counter()
    
    # 1. Generate or capture request ID
    req_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
    set_request_id(req_id)
    
    # 2. Tag Sentry scope (if available)
    if SENTRY_DSN:
        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("request_id", get_request_id())
    
    # 3. Process Request
    response: Response = await call_next(request)
    duration = time.perf_counter() - start_time
    
    # 4. Record Metrics (excluding metrics endpoint noise)
    if not request.url.path.endswith("/metrics"):
        MetricsManager.record_request(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code,
            duration=duration
        )
        
        # Periodic circuit state reporting (Sampled or on every request for low-volume apps)
        MetricsManager.record_circuit_state("SentryTelemetry", sentry_circuit.get_state_numeric())

    # 5. Return ID in header for client-side correlation
    response.headers["X-Request-ID"] = get_request_id()
    return response

# --- METRICS ENDPOINT ---
@app.get("/api/v2/metrics", tags=["System"])
async def get_metrics(current_user: dict = Depends(admin_only)):
    """
    Exposes industrial Prometheus metrics for system monitoring.
    Locked to Admin-only for security.
    """
    content, content_type = MetricsManager.get_latest_metrics()
    return Response(content=content, media_type=content_type)

# --- OBSERVABILITY MIDDLEWARE ---

# --- CSRF PROTECTION MIDDLEWARE ---
@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """
    Enforces X-Requested-With header for all state-changing operations.
    Protects against browser-based CSRF attacks.
    """
    if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        custom_header = request.headers.get("X-Requested-With")
        if custom_header != "XMLHttpRequest":
            mto_logger.security(
                "CSRF ATTEMPT DETECTED: Missing or invalid X-Requested-With header",
                method=request.method,
                url=str(request.url),
                ip=request.client.host
            )
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Security violation: CSRF protection triggered."}
            )
            
    response = await call_next(request)
    return response

# --- AUTHENTICATION ENDPOINT ---
@app.post("/api/auth/login")
async def login(credentials: Dict[str, str], request: Request):
    """
    Secure login with brute-force protection and structured logging.
    """
    username = credentials.get("username")
    password = credentials.get("password")
    
    mto_logger.info(f"Login attempt received for user: {username}", ip=request.client.host)
    
    user_data = auth_svc.verify_user_login(username, password)
    if user_data:
        mto_logger.info("Login successful", user=username, ip=request.client.host)
        return user_data
    else:
        mto_logger.security("Login failed: Invalid credentials or account locked", user=username, ip=request.client.host)
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.middleware("http")
async def maintenance_mode_middleware(request: Request, call_next):
    from utils import is_feature_enabled
    if is_feature_enabled("MAINTENANCE_MODE"):
        # Allow only admins to bypass maintenance
        # This is a simplified check; in a real app, you'd check JWT here if possible
        # or allow specific IP addresses
        if not request.url.path.startswith("/docs") and not request.url.path.startswith("/redoc"):
             return Response(
                content="System is currently under maintenance. Please try again later.",
                status_code=503
            )
    return await call_next(request)

# CORS Configuration - Lock the door to everyone except our local apps
origins = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8001",
    "https://localhost:8001",
    "http://localhost:3000",  # Common for future frontend dev
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    try:
        from alembic.config import Config
        from alembic import command
        
        mto_logger.info("Starting Industrial Database Migration Check (Alembic)...")
        
        # Load Alembic config and run upgrade
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        
        mto_logger.info("Database schema is UP TO DATE.")
    except Exception as e:
        mto_logger.error(f"CRITICAL: Database Migration Failed: {e}")


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"VALIDATION ERROR for {request.method} {request.url.path}:")
    print(exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": exc.body},
    )


# Security Configuration
from utils.secrets_manager import secrets
from utils.config import config as mto_config
SECRET_KEY = secrets.jwt_secret
ALGORITHM = mto_config.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = mto_config.TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


async def get_current_user(request: Request, token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # DECOUPLED: Read user info directly from JWT to avoid DB fetch on every request
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("id")
        username: str = payload.get("sub")
        role: str = payload.get("role")

        if username is None or role is None or user_id is None:
            raise credentials_exception

        return {"id": user_id, "username": username, "role": role}
    except JWTError:
        raise credentials_exception
    except Exception as e:
        print(f"AUTH ERROR: {str(e)}")
        raise credentials_exception


class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: dict = Depends(get_current_user)):
        # Now we read from the token payload instead of DB
        role = str(current_user.get("role", "")).strip().lower()
        print(f"DEBUG AUTH: User='{current_user.get('username')}' Role='{role}' Required={self.allowed_roles}")
        
        if role not in self.allowed_roles:
            print(f"DEBUG AUTH: ACCESS DENIED. Role '{role}' not in {self.allowed_roles}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Required permissions missing. You have '{role}', need one of {self.allowed_roles}",
            )
        return current_user


# Permission presets
admin_only = RoleChecker(["admin"])
write_access = RoleChecker(["admin", "cashier", "encoder"])
read_only = RoleChecker(["admin", "cashier", "encoder", "viewer"])


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


@app.post("/token", response_model=Token, tags=["Auth"])
@limiter.limit("10/minute")
async def login_for_access_token(
    request: Request, form_data: OAuth2PasswordRequestForm = Depends()
):
    try:
        user = auth_svc.verify_user_login(form_data.username, form_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user["username"], "role": user["role"], "id": user["id"]},
            expires_delta=access_token_expires,
        )
        return {"access_token": access_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/healthz", tags=["System"])
async def health_check():
    """Enterprise-grade health check for orchestration tools."""
    health = {"status": "healthy", "timestamp": datetime.now().isoformat()}
    
    # 1. Check Database
    try:
        db.db_query("SELECT 1", fetch=True, commit=False)
        health["database"] = "connected"
    except Exception as e:
        health["status"] = "unhealthy"
        health["database"] = f"disconnected: {str(e)}"
        
    # 2. Check Last Backup
    try:
        from backend.services.backup_service import get_backup_status
        status = get_backup_status()
        health["last_backup"] = status.get("health", "UNKNOWN")
        if health["last_backup"] != "OK":
            health["status"] = "degraded"
    except:
        health["last_backup"] = "error_fetching"

    if health["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health)
        
    return health


@app.get("/me", tags=["Auth"])
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user


@api_v2.post("/system/undo", tags=["System"])
async def undo_last_system_action(
    current_user: dict = Depends(get_current_user)
):
    """Reverses the last critical action (UPDATE/DELETE) performed by the current user."""
    from backend.services.history_service import undo_last_action
    success, message = undo_last_action(current_user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    # Notify other clients of the data change
    await manager.broadcast({
        "type": "NOTIFICATION",
        "title": "Action Reversed",
        "message": message,
        "level": "success"
    })
    
    return {"status": "success", "message": message}

# Register Versioned Router
app.include_router(api_v2)


# --- User Management (Admin Only) ---


@app.get("/users", tags=["Admin"], dependencies=[Depends(admin_only)])
async def list_users(
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    return auth_svc.get_all_users(limit=limit, offset=offset)


@app.post("/users", tags=["Admin"], dependencies=[Depends(admin_only)])
async def create_user(
    data: UserCreateSchema, current_user: dict = Depends(get_current_user)
):
    user_id = auth_svc.create_user(
        username=data.username,
        full_name=data.full_name,
        password=data.password,
        role=data.role,
        admin_user=current_user,
    )
    return {"status": "created", "user_id": user_id}


@app.patch("/users/{user_id}", dependencies=[Depends(admin_only)])
async def update_user(
    user_id: int, data: UserUpdateSchema, current_user: dict = Depends(get_current_user)
):
    if data.role is not None:
        auth_svc.update_user_role(user_id, data.role, current_user)
    if data.is_active is not None:
        auth_svc.update_user_status(user_id, data.is_active, current_user)
    return {"status": "updated"}


@app.post("/users/{user_id}/reset-password", dependencies=[Depends(admin_only)])
async def reset_user_password(
    user_id: int,
    data: PasswordResetSchema,
    current_user: dict = Depends(get_current_user),
):
    auth_svc.reset_user_password(user_id, data.new_password, current_user)
    return {"status": "password_reset"}




# --- Property Routes ---


@app.get("/properties", tags=["Properties"])
async def list_properties(
    search: str = "",
    limit: int = 50,
    cursor: Optional[int] = None,
    kind: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    barangay: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    # Fetch limit + 1 to detect if there's a next page
    results = prop_svc.search_properties(
        search,
        limit=limit + 1,
        cursor=cursor,
        kind=kind,
        year_start=year_start,
        year_end=year_end,
        barangay=barangay,
    )
    
    has_more = len(results) > limit
    items = results[:limit]
    next_cursor = items[-1][0] if has_more and items else None # items[0] is ID in raw row
    
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items)
    }

@app.get("/properties/{property_id}/history", tags=["Properties"])
async def get_property_history(property_id: int, current_user: dict = Depends(get_current_user)):
    query = """
        SELECT id, td_number, assessed_value, kind_of_property, tax_year, changed_by, created_at
        FROM property_assessment_history
        WHERE property_id = %s
        ORDER BY created_at DESC
    """
    rows = db.db_query(query, (property_id,), fetch=True, commit=False) or []
    return [
        {
            "id": r[0],
            "td_number": r[1],
            "assessed_value": float(r[2]),
            "kind": r[3],
            "tax_year": r[4],
            "changed_by": r[5],
            "date": r[6].strftime("%Y-%m-%d %H:%M:%S") if hasattr(r[6], "strftime") else str(r[6])
        }
        for r in rows
    ]

@app.get("/properties/barangays", tags=["Properties"])
async def list_barangays(current_user: dict = Depends(get_current_user)):
    from backend.services.property_service import get_barangays

    return get_barangays()



@app.get("/properties/delinquent", tags=["Properties"])
async def get_delinquent_accounts(
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    return bill_svc.get_delinquent_accounts(limit=limit, offset=offset)


@app.get("/properties/deleted", dependencies=[Depends(admin_only)])
async def list_deleted_properties(current_user: dict = Depends(get_current_user)):
    return prop_svc.get_deleted_properties()


@app.post("/properties/{property_id}/restore", dependencies=[Depends(admin_only)])
async def restore_property(
    property_id: int, current_user: dict = Depends(get_current_user)
):
    prop_svc.restore_property(property_id, current_user)
    return {"status": "restored"}


@app.post("/properties/import-assessment", tags=["Properties"])
@limiter.limit("5/minute")
async def import_assessment_roll(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(write_access),
):
    """Imports Assessment Roll data from Excel."""
    import shutil

    temp_path = f"temp_import_{datetime.now().timestamp()}.xlsx"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        import backend.services.import_service as import_svc
        import inspect

        print(f"DEBUG: Using import_service from: {inspect.getfile(import_svc)}")
        print(f"DEBUG: sys.path: {sys.path}")

        summary = import_svc.import_assessment_roll_from_excel(temp_path, current_user)
        return summary
    except Exception as e:
        import traceback

        print("IMPORT CRASH:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Import Error: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.delete("/properties/{property_id}/purge", dependencies=[Depends(admin_only)])
async def purge_property(
    property_id: int, current_user: dict = Depends(get_current_user)
):
    prop_svc.purge_property(property_id, current_user)
    return {"status": "purged"}


@app.get("/properties/unspecified")
async def get_unspecified_properties(current_user: dict = Depends(get_current_user)):
    return prop_svc.get_unspecified_properties()


@app.get("/properties/{property_id}")
async def get_property(
    property_id: int, current_user: dict = Depends(get_current_user)
):
    prop = prop_svc.get_property_by_id(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


@app.post("/properties")
@limiter.limit("15/minute")
async def create_property(
    request: Request,
    data: PropertySaveSchema, 
    current_user: dict = Depends(write_access)
):
    # Convert Pydantic model to dict for the service layer
    payload = data.dict(by_alias=True)

    # Auto-generate Tax Year from Effectivity Date if missing
    if not payload.get("Tax Year") and payload.get("Effectivity Date"):
        eff_date = payload["Effectivity Date"]
        if len(str(eff_date)) >= 4:
            payload["Tax Year"] = str(eff_date)[:4]
        else:
            payload["Tax Year"] = str(datetime.now().year)
    elif not payload.get("Tax Year"):
        payload["Tax Year"] = str(datetime.now().year)

    res = prop_svc.save_property(payload, user=current_user)
    if not res:
        raise HTTPException(status_code=400, detail="Failed to create property")
    return res


@app.put("/properties/{property_id}")
@limiter.limit("20/minute")
async def update_property(
    request: Request,
    property_id: int,
    data: PropertySaveSchema,
    current_user: dict = Depends(write_access),
):
    payload = data.dict(by_alias=True)

    if not payload.get("Tax Year") and payload.get("Effectivity Date"):
        eff_date = payload["Effectivity Date"]
        if len(str(eff_date)) >= 4:
            payload["Tax Year"] = str(eff_date)[:4]

    res = prop_svc.save_property(payload, editing_id=property_id, user=current_user)
    if not res:
        raise HTTPException(status_code=400, detail="Failed to update property")
    return res


# --- Search Routes ---


@app.get("/search/global")
async def global_search(q: str = "", current_user: dict = Depends(get_current_user)):
    """Unified search for the Command Palette."""
    if not q:
        return {"results": search_svc.get_quick_actions()}

    results = search_svc.global_search(q)
    return {"results": results}


@app.delete("/properties/{property_id}")
async def delete_property(
    property_id: int, request: Request, current_user: dict = Depends(write_access)
):
    ip = request.client.host
    res = prop_svc.soft_delete_property(property_id, user=current_user, ip_address=ip)
    if not res:
        raise HTTPException(status_code=400, detail="Failed to delete property")
    return {"status": "deleted"}


@app.post("/properties/bulk-update-barangay")
async def bulk_update_barangay(data: BulkUpdateBarangaySchema, current_user: dict = Depends(write_access)):
    ids = data.ids
    new_brgy = data.barangay
    count = prop_svc.bulk_update_barangay(ids, new_brgy, user=current_user)
    return {"updated": count}


# --- PROPERTY DOSSIER ENDPOINT ---
@app.get("/properties/dossier/{td_number}")
async def get_property_dossier(
    td_number: str, current_user: dict = Depends(get_current_user)
):
    """
    Super-endpoint with enhanced serialization for Dossier data.
    """
    try:
        # 1. Get the Master Property Record
        raw_prop = prop_svc.get_property_by_td(td_number)
        if not raw_prop:
            raise HTTPException(
                status_code=404, detail=f"Property {td_number} not found"
            )

        # Helper to clean DB results for JSON
        def clean_data(obj):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return {
                    k: (
                        float(v)
                        if hasattr(v, "to_integral_value")
                        else str(v) if hasattr(v, "strftime") else v
                    )
                    for k, v in obj.items()
                }
            if isinstance(obj, (list, tuple)):
                return [
                    (
                        float(v)
                        if hasattr(v, "to_integral_value")
                        else str(v) if hasattr(v, "strftime") else v
                    )
                    for v in obj
                ]
            return obj

        prop = clean_data(raw_prop)

        # 2. Get payments (Ledger search returns list of tuples for the specific Dossier layout)
        raw_payments = pay_svc.get_payment_ledger(td_number)
        payments = [clean_data(p) for p in raw_payments]

        # 3. Trace Genealogy (1-level up)
        ancestry = []
        # We now use the actual column name 'prev_td_number'
        prev_td = prop.get("prev_td_number")
        if prev_td and str(prev_td).strip():
            prev_td = str(prev_td).strip()
            if prev_td != td_number:
                parent_prop = prop_svc.get_property_by_td(prev_td)
                if parent_prop:
                    ancestry.append(clean_data(parent_prop))

        # 4. Fetch recent audit logs
        logs = sys_svc.get_audit_logs(limit=10)

        # 5. Fetch full assessment history
        hist_query = """
            SELECT id, td_number, assessed_value, kind_of_property, tax_year, changed_by, created_at
            FROM property_assessment_history
            WHERE property_id = %s
            ORDER BY created_at DESC
        """
        raw_history = db.db_query(hist_query, (prop.get("id"),), fetch=True, commit=False) or []
        history = [
            {
                "id": r[0],
                "td_number": r[1],
                "assessed_value": float(r[2]),
                "kind": r[3],
                "tax_year": r[4],
                "changed_by": r[5],
                "date": r[6].strftime("%Y-%m-%d %H:%M:%S") if hasattr(r[6], "strftime") else str(r[6])
            }
            for r in raw_history
        ]

        return {
            "master": prop,
            "payments": payments,
            "ancestry": ancestry,
            "audit_summary": logs,
            "assessment_history": history
        }
    except Exception as e:
        import traceback

        print(f"DOSSIER CRASH for {td_number}: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal Dossier Error: {str(e)}")


# --- Payment Routes ---


@app.get("/payments/recent")
async def get_recent_payments(
    limit: int = 8, current_user: dict = Depends(get_current_user)
):
    return pay_svc.get_recent_payments(limit)


@app.get("/payments/records")
async def get_payment_records(
    term: str, current_user: dict = Depends(get_current_user)
):
    return pay_svc.get_payment_receipt_records(term)


@app.get("/payments/{payment_id}/details")
async def get_payment_details(
    payment_id: int, current_user: dict = Depends(get_current_user)
):
    res = pay_svc.get_payment_receipt_details(payment_id)
    if not res:
        raise HTTPException(status_code=404, detail="Payment details not found")
    return res


@app.post("/payments/receipt-record", tags=["Financial"])
async def save_receipt_record(
    data: ReceiptRecordSchema, current_user: dict = Depends(write_access)
):
    return pay_svc.save_receipt_record(
        data.property_id,
        data.payment_id,
        data.details,
        data.file_path,
        data.user_name,
        current_user=current_user,
    )


@app.get("/payments/ledger")
async def get_payment_ledger(term: str, current_user: dict = Depends(get_current_user)):
    return pay_svc.get_unified_payment_history(term)


@app.get("/payments/next-or")
async def get_next_or_number(current_user: dict = Depends(get_current_user)):
    return {"next_or": pay_svc.get_next_or_number()}


@app.get("/payments/trend")
async def get_collection_trend(
    months: int = 6, current_user: dict = Depends(get_current_user)
):
    return pay_svc.get_monthly_collection_trend(months)


# --- Billing Routes ---


@app.get("/billing/summary")
async def get_billing_summary(current_user: dict = Depends(get_current_user)):
    return sys_svc.get_dashboard_summary()


@app.get("/properties/{property_id}/statement")
async def get_property_statement(
    property_id: int, current_user: dict = Depends(get_current_user)
):
    return bill_svc.get_property_statement_data(property_id)


@app.get("/billing/assessment-roll")
async def get_assessment_roll(
    limit: int = 100, 
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    return prop_svc.get_assessment_roll(limit=limit, offset=offset)


@app.get("/billing/report-details")
async def get_report_details(
    month: str = "All",
    year: str = "All",
    current_user: dict = Depends(get_current_user),
):
    return bill_svc.get_report_details(month, year)


@app.get("/billing/receivables-summary")
async def get_receivables_summary(
    year: str, current_user: dict = Depends(get_current_user)
):
    return bill_svc.get_rpt_receivables_summary(year)


@app.get("/reports/receivables-by-barangay")
async def get_receivables_by_barangay(current_user: dict = Depends(get_current_user)):
    return prop_svc.get_receivables_by_barangay()


# --- System Routes ---


@app.post("/system/backup/trigger", tags=["System"])
@limiter.limit("3/minute")
async def trigger_backup(
    request: Request,
    background_tasks: BackgroundTasks, 
    current_user: dict = Depends(admin_only)
):
    """Triggers the hybrid backup process in the background."""
    from backend.services.backup_service import run_hybrid_backup

    # Run in background to avoid blocking the main thread
    async def backup_wrapper():
        await run_hybrid_backup(user=current_user)
        # Notify all clients when done
        await manager.broadcast({
            "type": "NOTIFICATION",
            "title": "Backup Complete",
            "message": "The Hybrid Backup process has finished successfully.",
            "level": "success"
        })

    background_tasks.add_task(backup_wrapper)
    return {
        "status": "backup_started",
        "message": "Hybrid backup is running in the background.",
    }


@app.get("/system/backup/status", tags=["System"], dependencies=[Depends(read_only)])
async def get_backup_health(current_user: dict = Depends(get_current_user)):
    from backend.services.backup_service import get_backup_status

    return get_backup_status()


@app.post("/system/import/validate", tags=["System"], dependencies=[Depends(write_access)])
async def validate_bulk_import(
    request: Request, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)
):
    from utils import is_feature_enabled
    if not is_feature_enabled("BULK_IMPORT"):
        raise HTTPException(status_code=403, detail="Bulk Import feature is currently disabled.")
        
    import os
    from backend.services.import_service import validate_property_import

    content = await file.read()
    ext = os.path.splitext(file.filename)[1]
    mode = request.query_params.get("mode", "property")
    
    if mode == "assessment":
        from backend.services.import_service import validate_assessment_import
        return validate_assessment_import(content, ext)
    
    return validate_property_import(content, ext)


@app.post("/system/import/commit", tags=["System"], dependencies=[Depends(write_access)])
async def commit_bulk_import(
    request: Request, data: List[PropertySaveSchema], current_user: dict = Depends(get_current_user)
):
    from utils import is_feature_enabled
    if not is_feature_enabled("BULK_IMPORT"):
        raise HTTPException(status_code=403, detail="Bulk Import feature is currently disabled.")
        
    mode = request.query_params.get("mode", "property")
    # Convert Pydantic models back to dictionaries for the service layer
    # We use exclude_unset=True to avoid sending defaults for missing fields
    payload = [d.model_dump(exclude_unset=True) for d in data]
    
    if mode == "assessment":
        from backend.services.import_service import commit_assessment_import
        res = commit_assessment_import(payload, current_user)
        return {"status": "success", "imported": res["inserted"] + res["updated"], "details": res}

    from backend.services.import_service import commit_property_import
    count = commit_property_import(payload, current_user)
    return {"status": "success", "imported": count}


@app.post("/system/logs")
async def log_system_action(
    log: LogActionSchema, current_user: dict = Depends(get_current_user)
):
    sys_svc.log_action(current_user, log.action)
    return {"status": "logged"}


@app.get("/system/audit-stats", dependencies=[Depends(admin_only)])
async def get_audit_stats(current_user: dict = Depends(get_current_user)):
    return sys_svc.get_audit_stats()


@app.get("/system/audit-logs", dependencies=[Depends(admin_only)])
async def list_audit_logs(
    username: Optional[str] = None,
    search: Optional[str] = "",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    results = sys_svc.get_audit_logs(
        username=username,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit + 1,
        cursor=cursor,
    )
    
    has_more = len(results) > limit
    items = results[:limit]
    next_cursor = items[-1]["id"] if has_more and items else None
    
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more
    }


@app.get("/system/audit-users", dependencies=[Depends(admin_only)])
async def list_audit_users(current_user: dict = Depends(get_current_user)):
    return sys_svc.get_distinct_log_users()


@app.get("/analytics/trends", tags=["Analytics"], dependencies=[Depends(read_only)])
async def get_analytics_trends(months: int = 12, current_user: dict = Depends(get_current_user)):
    from backend.services.payment_service import get_monthly_collection_trend
    return get_monthly_collection_trend(months)


@app.get("/analytics/barangay-breakdown", tags=["Analytics"], dependencies=[Depends(read_only)])
async def get_barangay_breakdown(current_user: dict = Depends(get_current_user)):
    from backend.services.payment_service import get_revenue_by_barangay
    return get_revenue_by_barangay()


@app.get("/analytics/kpis", tags=["Analytics"], dependencies=[Depends(read_only)])
async def get_analytics_kpis(current_user: dict = Depends(get_current_user)):
    from backend.services.payment_service import get_collection_kpis
    return get_collection_kpis()


@app.get("/system/logs", tags=["System"], dependencies=[Depends(admin_only)])
async def get_system_logs(
    lines: int = 100, current_user: dict = Depends(get_current_user)
):
    """Returns the last N lines of the system.log file."""
    try:
        from utils import ERROR_LOG_PATH

        if not os.path.exists(ERROR_LOG_PATH):
            return {"logs": "Log file not found."}

        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            # Read all lines and take the last N
            log_lines = f.readlines()
            return {"logs": "".join(log_lines[-lines:])}
    except Exception as e:
        return {"logs": f"Error reading logs: {str(e)}"}


@app.get("/system/backup/status", tags=["System"], dependencies=[Depends(read_only)])
async def get_backup_verification_status(current_user: dict = Depends(get_current_user)):
    """Returns the latest backup health, timestamp, and SHA-256 checksum."""
    from backend.services.backup_service import get_backup_status

    return get_backup_status()


class RestoreRequest(BaseModel):
    file_path: str

@app.post("/system/restore", tags=["System"], dependencies=[Depends(admin_only)])
async def restore_system_backup(
    request: RestoreRequest, current_user: dict = Depends(get_current_user)
):
    """Performs a full database restore from a SQL file."""
    from backend.services.system_service import restore_database
    import traceback

    try:
        # Normalize the path to handle cross-platform slash issues
        file_path = request.file_path.replace("\\", "/").strip()
        result = restore_database(file_path)
        return {"status": "success", "data": result}
    except Exception as e:
        error_detail = traceback.format_exc()
        # Log to a dedicated file for the user to see
        try:
            with open("logs/restore_debug.log", "a") as f:
                f.write(f"\n[{datetime.now()}] RESTORE FAILURE\n")
                f.write(f"File: {request.file_path}\n")
                f.write(f"Error: {str(e)}\n")
                f.write(f"Traceback:\n{error_detail}\n")
                f.write("-" * 40 + "\n")
        except:
            pass
            
        print(f"Restore Error: {error_detail}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/billing/bulk-soa", tags=["Billing"], dependencies=[Depends(write_access)])
async def generate_bulk_soa_pdf(
    request: BillingBulkRequest, current_user: dict = Depends(get_current_user)
):
    """Generates a merged PDF of Statements of Account for multiple properties."""
    from backend.services.billing_service import get_property_statement_data
    import os

    data_list = []
    for prop_id in request.property_ids:
        stmt_data = get_property_statement_data(prop_id)
        if stmt_data:
            data_list.append(stmt_data)

    if not data_list:
        raise HTTPException(status_code=400, detail="No valid property data found for bulk generation.")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Delegate to the proxy generator
    pdf_path = rg.bulk_generate_soa(data_list, base_dir, filename_prefix=request.filename_prefix)
    
    return FileResponse(
        pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path)
    )


@app.post("/payments/{payment_id}/receipt-pdf", dependencies=[Depends(write_access)])
async def generate_receipt_pdf(
    payment_id: int, current_user: dict = Depends(get_current_user)
):
    details = pay_svc.get_payment_receipt_details(payment_id)
    if not details:
        raise HTTPException(status_code=404, detail="Payment details not found")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_path = rg.generate_or_receipt(details, base_dir)
    return FileResponse(
        pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path)
    )


# --- WebSocket Endpoint ---
@app.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            # Echo for testing or handle specific client signals
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- ANALYTICS DASHBOARD ---

@app.get("/api/analytics/dashboard")
async def get_analytics_dashboard(user: str = Depends(get_current_user)):
    """Returns a comprehensive set of treasury analytics data."""
    return {
        "summary": analytics.get_collection_summary(),
        "trend": analytics.get_monthly_revenue_trend(),
        "barangays": analytics.get_barangay_distribution(),
        "years": analytics.get_tax_year_distribution()
    }

@app.get("/analytics", response_class=HTMLResponse)
async def serve_analytics_dashboard():
    """Serves a premium, web-based analytics dashboard using Apache ECharts."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MTO Treasury Insights</title>
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-color: #f8fafc;
                --card-bg: #ffffff;
                --text-primary: #1e293b;
                --text-secondary: #64748b;
                --accent: #38bdf8;
                --emerald: #10b981;
                --border: #e2e8f0;
            }
            [data-theme='dark'] {
                --bg-color: #0f172a;
                --card-bg: #1e293b;
                --text-primary: #f1f5f9;
                --text-secondary: #94a3b8;
                --accent: #38bdf8;
                --border: #334155;
            }
            body { 
                margin: 0; padding: 20px; 
                background: var(--bg-color); 
                color: var(--text-primary);
                font-family: 'Inter', sans-serif;
                transition: background 0.3s, color 0.3s;
            }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; }
            .card { 
                background: var(--card-bg); 
                border-radius: 12px; padding: 24px; 
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                border: 1px solid var(--border);
                transition: transform 0.2s;
                animation: fadeInUp 0.6s ease-out forwards;
                opacity: 0;
            }
            .card:hover { transform: translateY(-4px); }
            @keyframes fadeInUp {
                from { opacity: 0; transform: translateY(20px); }
                to { opacity: 1; transform: translateY(0); }
            }
            .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
            .stat-card { background: var(--card-bg); padding: 20px; border-radius: 12px; border: 1px solid var(--border); border-left: 4px solid var(--accent); }
            .stat-val { font-size: 1.8rem; font-weight: 600; color: var(--accent); margin-top: 5px; }
            .stat-label { font-size: 0.85rem; color: var(--text-secondary); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
            .chart-container { height: 350px; width: 100%; margin-top: 10px; }
            h2 { margin: 0; font-weight: 600; font-size: 1.1rem; color: var(--text-primary); }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🏛️ Treasury Insights Portal</h1>
            <div id="last-update" style="opacity: 0.5; font-size: 0.9rem;"></div>
        </div>

        <div class="stat-grid">
            <div class="stat-card"><div class="stat-label">Today's Collection</div><div id="stat-today" class="stat-val">₱0.00</div></div>
            <div class="stat-card" style="border-left-color: var(--emerald);"><div class="stat-label">Transactions Today</div><div id="stat-count" class="stat-val">0</div></div>
            <div class="stat-card"><div class="stat-label">Monthly Velocity</div><div id="stat-month" class="stat-val">₱0.00</div></div>
            <div class="stat-card"><div class="stat-label">Annual Revenue</div><div id="stat-year" class="stat-val">₱0.00</div></div>
        </div>

        <div class="grid">
            <div class="card"><h2>Revenue Velocity (Last 12 Months)</h2><div id="trend-chart" class="chart-container"></div></div>
            <div class="card"><h2>Top Barangay Collections</h2><div id="barangay-chart" class="chart-container"></div></div>
            <div class="card"><h2>Tax Year Distribution</h2><div id="year-chart" class="chart-container"></div></div>
        </div>

        <script>
            async function fetchData() {
                // Secure Token Retrieval from URL
                const urlParams = new URLSearchParams(window.location.search);
                const token = urlParams.get('t');
                const theme = urlParams.get('theme') || 'dark';
                
                document.documentElement.setAttribute('data-theme', theme);

                const headers = {};
                if (token) {
                    headers["Authorization"] = "Bearer " + token;
    
                    // CSRF Protection: Include custom header for all state-changing requests
                    headers["X-Requested-With"] = "XMLHttpRequest";
                }

                const res = await fetch('/api/analytics/dashboard', { headers: headers });
                
                if (res.status === 401) {
                    document.body.innerHTML = '<div style="display:flex; height:100vh; align-items:center; justify-content:center; color:white;"><h1>🚫 UNAUTHORIZED: Please launch from the Treasury Desktop App.</h1></div>';
                    return;
                }

                const data = await res.json();
                
                document.getElementById('last-update').innerText = 'System Pulse: ' + new Date().toLocaleTimeString();
                document.getElementById('stat-today').innerText = '₱' + data.summary.today.toLocaleString();
                document.getElementById('stat-count').innerText = data.summary.count;
                document.getElementById('stat-month').innerText = '₱' + data.summary.month.toLocaleString();
                document.getElementById('stat-year').innerText = '₱' + data.summary.year.toLocaleString();

                renderTrendChart(data.trend);
                renderBarangayChart(data.barangays);
                renderYearChart(data.years);
            }

            function renderTrendChart(trend) {
                const theme = document.documentElement.getAttribute('data-theme');
                const chart = echarts.init(document.getElementById('trend-chart'), theme === 'dark' ? 'dark' : null);
                chart.setOption({
                    backgroundColor: 'transparent',
                    tooltip: { trigger: 'axis' },
                    xAxis: { type: 'category', data: trend.map(d => d.month), axisLine: { show: false } },
                    yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
                    series: [{
                        data: trend.map(d => d.total),
                        type: 'line',
                        smooth: true,
                        lineStyle: { width: 4, color: '#38bdf8' },
                        areaStyle: {
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                { offset: 0, color: 'rgba(56, 189, 248, 0.4)' },
                                { offset: 1, color: 'rgba(56, 189, 248, 0)' }
                            ])
                        },
                        symbol: 'none'
                    }]
                });
            }

            function renderBarangayChart(data) {
                const theme = document.documentElement.getAttribute('data-theme');
                const chart = echarts.init(document.getElementById('barangay-chart'), theme === 'dark' ? 'dark' : null);
                chart.setOption({
                    backgroundColor: 'transparent',
                    tooltip: { trigger: 'item' },
                    series: [{
                        type: 'pie',
                        radius: ['40%', '70%'],
                        avoidLabelOverlap: false,
                        itemStyle: { borderRadius: 10, borderColor: '#1e293b', borderWidth: 2 },
                        label: { show: false },
                        emphasis: { label: { show: true, fontSize: 14, fontWeight: 'bold' } },
                        data: data
                    }]
                });
            }

            function renderYearChart(data) {
                const theme = document.documentElement.getAttribute('data-theme');
                const chart = echarts.init(document.getElementById('year-chart'), theme === 'dark' ? 'dark' : null);
                chart.setOption({
                    backgroundColor: 'transparent',
                    tooltip: { trigger: 'axis' },
                    xAxis: { type: 'value', splitLine: { show: false } },
                    yAxis: { type: 'category', data: data.map(d => d.year) },
                    series: [{
                        type: 'bar',
                        data: data.map(d => d.total),
                        itemStyle: {
                            color: new echarts.graphic.LinearGradient(1, 0, 0, 0, [
                                { offset: 0, color: '#10b981' },
                                { offset: 1, color: '#38bdf8' }
                            ]),
                            borderRadius: [0, 5, 5, 0]
                        }
                    }]
                });
            }

            fetchData();
            setInterval(fetchData, 60000);
            window.addEventListener('resize', () => {
                echarts.getInstanceByDom(document.getElementById('trend-chart')).resize();
                echarts.getInstanceByDom(document.getElementById('barangay-chart')).resize();
                echarts.getInstanceByDom(document.getElementById('year-chart')).resize();
            });
        </script>
    </body>
    </html>
    """

# Deleted redundant delete_property route to avoid FastAPI startup conflict
@app.get("/")
async def root():
    return {"message": "MTO Treasury API is running", "status": "online"}


if __name__ == "__main__":
    import uvicorn

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_path = os.path.join(base_dir, "certs", "cert.pem")
    key_path = os.path.join(base_dir, "certs", "key.pem")

    if os.path.exists(cert_path) and os.path.exists(key_path):
        print("Starting Secure API (HTTPS) with CORS Enabled...")
        uvicorn.run(
            app, host="0.0.0.0", port=8001, ssl_keyfile=key_path, ssl_certfile=cert_path
        )
    else:
        print("Starting Standard API (HTTP) - SSL Certs not found.")
        uvicorn.run(app, host="0.0.0.0", port=8001)
