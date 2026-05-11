import os
import sys
from typing import List, Optional
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
    File,
    UploadFile,
    Request,
    BackgroundTasks,
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

from dotenv import load_dotenv

load_dotenv()

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
)

app = FastAPI(title="Treasury Management API", version="2.0.0")

# Rate Limiter Configuration
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
        from migration_manager import run_migrations

        print("Starting Database Migration Check...")
        run_migrations()
        print("Database is up to date.")
    except Exception as e:
        print(f"CRITICAL: Database Migration Failed: {e}")


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
SECRET_KEY = os.getenv(
    "MTO_API_SECRET_KEY", "7b9e1d2c3f4a5b6c7d8e9f0a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p"
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

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
        role = str(current_user.get("role", "")).lower()
        if role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Required permissions missing.",
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


@app.get("/me", tags=["Auth"])
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user


# --- User Management (Admin Only) ---


@app.get("/users", tags=["Admin"], dependencies=[Depends(admin_only)])
async def list_users(current_user: dict = Depends(get_current_user)):
    return auth_svc.get_all_users()


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


@app.get("/system/audit-logs", dependencies=[Depends(admin_only)])
async def get_audit_logs(
    user_id: Optional[int] = None,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    return sys_svc.get_audit_logs(user_id=user_id, limit=limit)


# --- Property Routes ---


@app.get("/properties", tags=["Properties"])
async def list_properties(
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    kind: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    barangay: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    return prop_svc.search_properties(
        search,
        limit=limit,
        offset=offset,
        kind=kind,
        year_start=year_start,
        year_end=year_end,
        barangay=barangay,
    )

@app.get("/properties/barangays", tags=["Properties"])
async def list_barangays(current_user: dict = Depends(get_current_user)):
    from backend.services.property_service import get_barangays

    return get_barangays()



@app.get("/properties/delinquent", tags=["Properties"])
async def get_delinquent_accounts(current_user: dict = Depends(get_current_user)):
    return prop_svc.get_delinquent_accounts()


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
@limiter.limit("2/minute")
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
async def create_property(
    data: PropertySaveSchema, current_user: dict = Depends(write_access)
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
async def update_property(
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
async def bulk_update_barangay(data: dict, current_user: dict = Depends(write_access)):
    ids = data.get("ids", [])
    new_brgy = data.get("barangay")
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

        return {
            "master": prop,
            "payments": payments,
            "ancestry": ancestry,
            "audit_summary": logs,
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
async def get_assessment_roll(current_user: dict = Depends(get_current_user)):
    return prop_svc.get_assessment_roll()


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
async def trigger_backup(
    background_tasks: BackgroundTasks, current_user: dict = Depends(admin_only)
):
    """Triggers the hybrid backup process in the background."""
    from backend.services.backup_service import run_hybrid_backup

    # Run in background to avoid blocking the main thread
    background_tasks.add_task(run_hybrid_backup, user=current_user)
    return {
        "status": "backup_started",
        "message": "Hybrid backup is running in the background.",
    }


@app.get("/system/backup/status", tags=["System"], dependencies=[Depends(read_only)])
async def get_backup_health(current_user: dict = Depends(get_current_user)):
    from backend.services.backup_service import get_backup_status

    return get_backup_status()


@app.post("/system/logs")
async def log_system_action(
    log: LogActionSchema, current_user: dict = Depends(get_current_user)
):
    sys_svc.log_action(current_user, log.action)
    return {"status": "logged"}


@app.get("/system/audit-stats", dependencies=[Depends(admin_only)])
async def get_audit_stats(current_user: dict = Depends(get_current_user)):
    return sys_svc.get_audit_stats()


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
