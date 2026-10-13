"""Opaque business identifiers. Database UNIQUE constraints remain authoritative."""
from uuid import uuid4

def patient_no() -> str:
    return "P-" + uuid4().hex.upper()

def visit_no() -> str:
    return "V-" + uuid4().hex.upper()

def invoice_no() -> str:
    return "I-" + uuid4().hex.upper()
