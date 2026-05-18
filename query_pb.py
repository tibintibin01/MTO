import sys
import os

sys.path.append(r"C:\Users\user\Desktop\MTO")

from backend.database import SessionLocal
from backend.models import Property, PropertyBilling, Payment, PaymentBilling

db = SessionLocal()

print("Total PaymentBilling rows:", db.query(PaymentBilling).count())
pbs = db.query(PaymentBilling).limit(10).all()
for pb in pbs:
    print(f"PB: Payment {pb.payment_id} -> Billing {pb.billing_id}, Year: {pb.tax_year}, Amount: {pb.amount_paid}")
