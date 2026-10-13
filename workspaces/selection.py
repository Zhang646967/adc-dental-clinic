"""The role shortcut is a UX policy, not a grant or scope selector."""
from workspaces.rules import ROLES

def sole_role(roles):
    available = set(roles)
    if not available.issubset(ROLES):
        raise ValueError("Unknown role in selection policy")
    return next(iter(available)) if len(available) == 1 else None
