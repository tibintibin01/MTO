from datetime import datetime
from sqlalchemy import Column, Integer, String, DECIMAL, Boolean, DateTime, ForeignKey, Text, TIMESTAMP, Index, func

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
    amount = Column(DECIMAL(12, 2), nullable=False, default=0.00)
    penalty = Column(DECIMAL(12, 2), default=0.00)
    discount = Column(DECIMAL(12, 2), default=0.00)
    or_number = Column(String(255), nullable=True, index=True)
    date_paid = Column(DateTime, nullable=True, index=True)
    tax_year = Column(String(20), nullable=True)
    posted_by = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    property = relationship("Property", back_populates="payments")
    billings = relationship("PaymentBilling", back_populates="payment", cascade="all, delete-orphan")

class PropertyBilling(Base):
    __tablename__ = "property_billings"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    tax_year = Column(String(20), nullable=False)
    assessed_value = Column(DECIMAL(12, 2), nullable=False, default=0.00)
    penalty = Column(DECIMAL(12, 2), nullable=False, default=0.00)
    discount = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    amount_paid = Column(DECIMAL(12, 2), nullable=False, default=0.00)
    is_archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # Composite index: billing reconciliation always filters by (property_id, tax_year)
    __table_args__ = (
        Index("ix_property_billings_property_id_tax_year", "property_id", "tax_year"),
    )

    property = relationship("Property", back_populates="billings")

class PaymentBilling(Base):
    __tablename__ = "payment_billings"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    billing_id = Column(Integer, ForeignKey("property_billings.id", ondelete="RESTRICT"), nullable=False)
    tax_year = Column(String(20), nullable=False)
    amount_paid = Column(DECIMAL(12, 2), nullable=False, default=0.00)
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


class ReceiptHistory(Base):
    __tablename__ = "receipt_history"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False)
    payment_id = Column(Integer, nullable=True, index=True)
    td_number = Column(String(255))
    owner_name = Column(String(255))
    or_number = Column(String(255))
    tax_year = Column(String(20))
    amount = Column(DECIMAL(12, 2), nullable=False, default=0.00)
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
    key = Column(String(128), unique=True, nullable=False, index=True)
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
    health = Column(String(100), default="UNKNOWN")
    user_name = Column(String(255), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.now)


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

    id = Column(String(36), primary_key=True)          # UUID
    job_type = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    submitted_by = Column(String(150), nullable=False)
    payload = Column(Text, nullable=True)              # JSON input params
    result = Column(Text, nullable=True)               # JSON output / file path
    error = Column(Text, nullable=True)                # Error message on failure
    progress = Column(Integer, default=0)              # 0–100
    progress_message = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

# --- SECURE GOVERNMENT COMPLIANCE: AUDIT LOG IMMUTABILITY ---
from sqlalchemy import event

@event.listens_for(AuditLog, "before_update")
def prevent_audit_log_update(mapper, connection, target):
    raise ValueError("Security Violation: Audit logs are strictly immutable (append-only) and cannot be updated.")

@event.listens_for(AuditLog, "before_delete")
def prevent_audit_log_delete(mapper, connection, target):
    raise ValueError("Security Violation: Audit logs are strictly immutable (append-only) and cannot be deleted.")
