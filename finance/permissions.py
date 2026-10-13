"""Compatibility facade; role policy belongs to accounts, not billing."""
from accounts.finance_access import require_finance_read, lock_finance_write
