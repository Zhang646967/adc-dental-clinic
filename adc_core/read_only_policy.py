"""Business read-only policy; HTTP POST is not necessarily a business command.

Every exception is an exact, reviewed URL name, not a user-supplied path prefix.
Session/context changes and bounded assistant quota records are technical writes.
Authorization, CSRF and workspace verification are never waived by this policy.
"""
from types import MappingProxyType

SAFE_METHODS = frozenset(("GET", "HEAD", "OPTIONS"))
READ_ONLY_POST_CONTRACTS = MappingProxyType({
    "login": "authenticate_session",
    "portal_login": "authenticate_session",
    "logout": "close_session",
    "mini_login": "authenticate_patient_session",
    "mini_logout": "close_patient_session",
    "activate_role": "select_authorized_context",
    "activate_clinic": "select_authorized_context",
    "assistant_api": "bounded_assistance_no_business_command",
    "guide_result_wait": "read_selected_wait_result",
})

def allowed_in_read_only(method: str, view_name: str | None) -> bool:
    """Decide only instance write policy, never the caller's authorization."""
    return method in SAFE_METHODS or (
        method == "POST" and view_name in READ_ONLY_POST_CONTRACTS
    )
