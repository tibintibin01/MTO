from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DECIMAL, Boolean, DateTime, ForeignKey, Text, TIMESTAMP, Index, func, SmallInteger

from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False, default="")
    username = Column(String(150), unique=True, nullable=False, index=True)
    password = Column(String(512), nullable=False)
    role = Column(String(50), nullable=False, default="viewer")
    deleted_at = Column(DateTime, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    failed_attempts = Column(Integer, default=0)
    lockout_until = Column(DateTime, nullable=True)
    last_login = Column(DateTime, nullable=True)
    # Tracks when the password was last changed so tokens issued before this
    # timestamp can be immediately invalidated — even within their 1-hour window.
    password_changed_at = Column(DateTime, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    td_number = Column(String(100), nullable=False, unique=True, index=True)
    owner_name = Column(String(255), nullable=False)
    payor_name = Column(String(255), nullable=True)
    lot_number = Column(String(100), nullable=True)
    block_number = Column(String(100), nullable=True)
    area = Column(String(100), nullable=True)
    location = Column(String(255), nullable=True)
    barangay = Column(String(255), nullable=True)
    kind_of_property = Column(String(100), nullable=True)
    accountable_officer = Column(String(255), nullable=True)
    assessed_value = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    penalty = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    discount = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    or_number = Column(String(100), nullable=True)
    or_date = Column(DateTime, nullable=True)
    tax_year = Column(String(100), nullable=True)
    pin = Column(String(100), nullable=True)
    prev_td_number = Column(String(100), nullable=True)
    effectivity_date = Column(String(100), nullable=True)
    version = Column(Integer, default=1)
    deleted_at = Column(DateTime, nullable=True, index=True)
    archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    payments = relationship("Payment", back_populates="property")
    billings = relationship("PropertyBilling", back_populates="property")
    assessment_history = relationship("PropertyAssessmentHistory", back_populates="property")

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    penalty = Column(DECIMAL(14, 2), default=0.00)
    discount = Column(DECIMAL(14, 2), default=0.00)
    or_number = Column(String(255), nullable=True, index=True)
    date_paid = Column(DateTime, nullable=True, index=True)
    tax_year = Column(String(20), nullable=True)
    posted_by = Column(String(255), nullable=True)
    remarks = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    property = relationship("Property", back_populates="payments")
    billings = relationship("PaymentBilling", back_populates="payment", cascade="all, delete-orphan")

class PropertyBilling(Base):
    __tablename__ = "property_billings"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    tax_year = Column(SmallInteger, nullable=False)
    assessed_value = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    penalty = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    discount = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    amount_paid = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    is_archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Composite unique index constraint: billing reconciliation filters by (property_id, tax_year) and duplicates are forbidden
    __table_args__ = (
        Index("ix_property_billings_property_id_tax_year", "property_id", "tax_year", unique=True),
    )

    property = relationship("Property", back_populates="billings")

class PaymentBilling(Base):
    __tablename__ = "payment_billings"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    billing_id = Column(Integer, ForeignKey("property_billings.id", ondelete="RESTRICT"), nullable=False)
    tax_year = Column(SmallInteger, nullable=False)
    amount_paid = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    payment = relationship("Payment", back_populates="billings")
    billing = relationship("PropertyBilling")

class PropertyAssessmentHistory(Base):
    __tablename__ = "property_assessment_history"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    td_number = Column(String(100))
    assessed_value = Column(DECIMAL(14, 2))
    tax_year = Column(String(100))
    kind_of_property = Column(String(100))
    changed_by = Column(String(255))
    change_reason = Column(String(255), default="Import Update")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    property = relationship("Property", back_populates="assessment_history")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String(255), nullable=False)
    action = Column(Text, nullable=False)
    table_name = Column(String(100), nullable=True)
    record_id = Column(Integer, nullable=True)
    old_values = Column(Text, nullable=True)
    new_values = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    timestamp = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_audit_logs_username_timestamp", "username", timestamp.desc()),
        Index("ix_audit_logs_timestamp", timestamp.desc()),
        Index("ix_audit_logs_table_record", "table_name", "record_id"),
    )


class ReceiptHistory(Base):
    __tablename__ = "receipt_history"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    payment_id = Column(Integer, nullable=True, index=True)
    td_number = Column(String(255))
    owner_name = Column(String(255))
    or_number = Column(String(255))
    tax_year = Column(String(20))
    amount = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    file_path = Column(Text, nullable=False)
    generated_by = Column(String(255))
    generated_at = Column(DateTime, nullable=False)
    status = Column(String(50), default="PDF READY")



class SystemStats(Base):
    __tablename__ = "system_stats"

    id = Column(Integer, primary_key=True, index=True)
    stat_key = Column(String(100), unique=True, index=True)
    stat_value = Column(DECIMAL(18, 2), default=0.00)
    last_updated = Column(DateTime, onupdate=func.now(), server_default=func.current_timestamp())
    metadata_json = Column(Text, nullable=True) # For complex stats

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(512), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    is_revoked = Column(Boolean, default=False)


class IdempotencyKey(Base):
    """
    Stores idempotency keys for payment and property-save operations.

    When a POST/PUT request arrives with an X-Idempotency-Key header, the
    server checks this table. If the key exists and hasn't expired, the
    cached response is returned immediately without re-executing the handler.
    This prevents duplicate payments from double-clicks or network retries.

    Keys expire after 24 hours — long enough to cover any realistic retry
    window, short enough to not grow the table indefinitely.
    """
    __tablename__ = "idempotency_keys"

    id = Column(Integer, primary_key=True, index=True)
    # Composite key format: "{uuid}:{user_id}:{sha256_hex}"
    # Max length: 36 (uuid) + 1 + 20 (user_id) + 1 + 64 (sha256) = 122 chars.
    # Using 200 to give headroom without wasting space.
    key = Column(String(200), unique=True, nullable=False, index=True)
    method = Column(String(10), nullable=False)
    path = Column(String(255), nullable=False)
    status_code = Column(Integer, nullable=False, default=200)
    response_body = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    expires_at = Column(DateTime, nullable=False)

class BackupHistory(Base):
    __tablename__ = "backup_history"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=True)
    status = Column(String(50), default="PENDING")
    health = Column(String(255), default="UNKNOWN")
    user_name = Column(String(255), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Job(Base):
    """
    Persistent background job queue.

    Long-running operations (PDF generation, backup, bulk import) submit a
    Job record and return the job_id immediately. A background worker thread
    picks up PENDING jobs and executes them. Clients poll GET /jobs/{id} for
    status and results.

    This gives async execution + persistence across server restarts without
    requiring Celery, Redis, or any additional infrastructure.

    Job types:
        backup          — hybrid backup (mysqldump + USB + cloud)
        import_commit   — bulk property/payment import
        pdf_receipt     — single receipt PDF
        pdf_soa         — statement of account PDF
        pdf_computation — delinquency computation PDF
        pdf_notice      — delinquency notice PDF
        pdf_bulk_soa    — bulk SOA for multiple properties

    Status flow:
        PENDING → RUNNING → COMPLETED
                          → FAILED
    """
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_type_created", "status", "job_type", "created_at"),
        Index("ix_jobs_status_started", "status", "started_at"),
    )

    id = Column(String(36), primary_key=True)          # UUID
    job_type = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    submitted_by = Column(String(150), nullable=False)
    payload = Column(Text(length=16777215), nullable=True)              # JSON input params
    result = Column(Text, nullable=True)               # JSON output / file path
    error = Column(Text, nullable=True)                # Error message on failure
    progress = Column(Integer, default=0)              # 0–100
    progress_message = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class TaxPolicy(Base):
    """
    Stores configurable municipal tax rates per tax year.
    If no entry is configured for a tax year, calculations default to:
    basic_rate = 1.0% (0.0100)
    sef_rate   = 1.0% (0.0100)
    penalty_rate = 2.0% per month of delay (0.0200)
    """
    __tablename__ = "tax_policies"

    id = Column(Integer, primary_key=True, index=True)
    tax_year = Column(SmallInteger, unique=True, nullable=False, index=True)
    basic_rate = Column(DECIMAL(6, 4), nullable=False, default=0.0100)
    sef_rate = Column(DECIMAL(6, 4), nullable=False, default=0.0100)
    penalty_rate = Column(DECIMAL(6, 4), nullable=False, default=0.0200)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.now())


class ORSequence(Base):
    """
    Stores sequential counters for Official Receipt (OR) numbers.
    Used with row-level locks (SELECT ... FOR UPDATE) to guarantee atomic
    serial generation of receipt numbers across concurrent cashier sessions.
    """
    __tablename__ = "or_sequences"

    id = Column(Integer, primary_key=True, index=True)
    prefix = Column(String(50), unique=True, nullable=False, index=True)
    next_value = Column(Integer, nullable=False, default=1)
    digits = Column(Integer, nullable=False, default=6)


class RetentionPolicy(Base):
    """
    Configurable data retention schedule per data type.

    Implements RA 10173 (Data Privacy Act) and DICT MC 2022-002 compliance.

    Retention rules:
      - Financial records (payments, receipts): 10 years minimum (COA)
      - Property assessments: permanent (land records, never purge)
      - Audit logs: 10 years (COA)
      - Deleted user accounts: 5 years
      - Refresh tokens: 7 days (already auto-expired)

    action values:
      ARCHIVE  — mark records as archived (read-only, stays in DB)
      PURGE    — hard delete (only for non-financial, non-audit data)

    is_active = False disables the policy without deleting it, so the
    schedule is preserved for audit trail purposes.
    """
    __tablename__ = "retention_policies"

    id = Column(Integer, primary_key=True, index=True)
    data_type = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=False)
    retention_years = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False, default="ARCHIVE")  # ARCHIVE | PURGE
    legal_basis = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())


class RetentionLog(Base):
    """
    Immutable audit trail for every retention action taken.

    Records what was archived/purged, when, by whom (system or admin),
    and how many records were affected. Required for COA and NPC audits.
    """
    __tablename__ = "retention_logs"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("retention_policies.id", ondelete="RESTRICT"),
                       nullable=False, index=True)
    data_type = Column(String(100), nullable=False)
    action = Column(String(20), nullable=False)          # ARCHIVE | PURGE | DRY_RUN
    records_affected = Column(Integer, nullable=False, default=0)
    cutoff_date = Column(DateTime, nullable=False)       # Records older than this were processed
    executed_by = Column(String(150), nullable=False)    # username or "system"
    notes = Column(Text, nullable=True)
    executed_at = Column(DateTime, nullable=False)

class BankDeposit(Base):
    __tablename__ = "bank_deposits"

    id = Column(Integer, primary_key=True, index=True)
    date_deposited = Column(DateTime, nullable=False, index=True)
    bank_name = Column(String(255), nullable=False)
    reference_number = Column(String(255), nullable=False)
    amount = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    deposited_by = Column(String(150), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class RateLimitBlock(Base):
    __tablename__ = "rate_limit_blocks"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    ip_address = Column(String(45), nullable=False, index=True)
    username = Column(String(150), nullable=True, index=True)
    endpoint = Column(String(255), nullable=False)
    limit_rule = Column(String(255), nullable=False)
    retry_after = Column(Integer, nullable=False)


# --- SECURE GOVERNMENT COMPLIANCE: AUDIT LOG IMMUTABILITY ---
from sqlalchemy import event

@event.listens_for(AuditLog, "before_update")
def prevent_audit_log_update(mapper, connection, target):
    raise ValueError("Security Violation: Audit logs are strictly immutable (append-only) and cannot be updated.")

@event.listens_for(AuditLog, "before_delete")
def prevent_audit_log_delete(mapper, connection, target):
    raise ValueError("Security Violation: Audit logs are strictly immutable (append-only) and cannot be deleted.")
