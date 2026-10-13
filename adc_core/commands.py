"""Public infrastructure contract: translate only known database conflicts.
Unexpected integrity failures are never mislabeled as user input errors.
"""
from functools import wraps
from django.db import IntegrityError, OperationalError
from adc_core.rules import RuleError
CONFLICT_CONSTRAINTS = {"slot_dentist_no_overlap", "visit_dentist_no_overlap", "visit_patient_no_overlap"}
def business_errors(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except IntegrityError as exc:
            cause = exc.__cause__
            name = getattr(getattr(cause, "diag", None), "constraint_name", None)
            if name in CONFLICT_CONSTRAINTS:
                raise RuleError("该牙医或患者的时间发生冲突，请刷新并选择其他时段。") from exc
            raise  # Unexpected integrity errors must not be mislabeled as scheduling conflicts.
        except OperationalError as exc:
            if getattr(exc.__cause__, "sqlstate", None) in ("40P01", "40001"):
                raise RuleError("发生并发竞争，本次操作已撤销；请刷新后重试。") from exc
            raise
    return wrapped


def assert_revision(obj, expected_version):
    """Caller must hold the aggregate row lock before using this guard."""
    if type(expected_version) is not int or obj.lock_version != expected_version:
        raise RuleError("记录已发生变化；请刷新后重新确认，不能覆盖他人操作。")
