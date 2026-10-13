"""Shared safe presentation of expected input/stale-object failures."""
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from adc_core.rules import RuleError
EXPECTED_ERRORS=(RuleError,ValidationError,ObjectDoesNotExist)
def add_error(form, exc):
    # Don't expose DB tracebacks or model identities on stale / unauthorized inputs.
    if isinstance(exc, ObjectDoesNotExist):
        form.add_error(None, "资料已变化或不可用；请刷新后重新选择。")
    elif isinstance(exc, ValidationError):
        form.add_error(None, "；".join(exc.messages))
    else:
        form.add_error(None, str(exc))
