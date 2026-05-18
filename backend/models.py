from datetime import datetime
from sqlalchemy import Column, Integer, String, DECIMAL, Boolean, DateTime, ForeignKey, Text, TIMESTAMP, func

from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False, default="")
    username = Column(String(150), unique=True, nullable=False, index=True)
    password = Column(String(512), nullable=False)
    role = Column(String(50), nullable=False, default="viewer")
    is_deleted = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    failed_attempts = Column(Integer, default=0)
    lockout_until = Column(DateTime, nullable=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    td_number = Column(String(100), nullable=False, index=True)
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
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    payments = relationship("Payment", back_populates="property", cascade="all, delete-orphan")
    billings = relationship("PropertyBilling", back_populates="property", cascade="all, delete-orphan")
    assessment_history = relationship("PropertyAssessmentHistory", back_populates="property", cascade="all, delete-orphan")

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    amount = Column(DECIMAL(12, 2), nullable=False, default=0.00)
    penalty = Column(DECIMAL(12, 2), default=0.00)
    discount = Column(DECIMAL(12, 2), default=0.00)
    or_number = Column(String(255), nullable=True)
    date_paid = Column(DateTime, nullable=True)
    tax_year = Column(String(20), nullable=True)
    posted_by = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    property = relationship("Property", back_populates="payments")
    billings = relationship("PaymentBilling", back_populates="payment", cascade="all, delete-orphan")

class PropertyBilling(Base):
    __tablename__ = "property_billings"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    tax_year = Column(String(20), nullable=False)
    assessed_value = Column(DECIMAL(12, 2), nullable=False, default=0.00)
    penalty = Column(DECIMAL(12, 2), nullable=False, default=0.00)
    discount = Column(DECIMAL(14, 2), nullable=False, default=0.00)
    amount_paid = Column(DECIMAL(12, 2), nullable=False, default=0.00)
    is_archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    property = relationship("Property", back_populates="billings")

class PaymentBilling(Base):
    __tablename__ = "payment_billings"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    billing_id = Column(Integer, nullable=False)
    tax_year = Column(String(20), nullable=False)
    amount_paid = Column(DECIMAL(12, 2), nullable=False, default=0.00)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    payment = relationship("Payment", back_populates="billings")

class PropertyAssessmentHistory(Base):
    __tablename__ = "property_assessment_history"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
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
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    payment_id = Column(Integer, nullable=True)
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
