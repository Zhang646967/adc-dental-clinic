"""Identity and scope are independent. No database or framework dependency."""
ROLES = {
    'PATIENT': ('患者', 'portal_home'),
    'DENTIST': ('医生', 'doctor_home'),
    'FRONT_DESK': ('前台', 'frontdesk_home'),
    'MANAGER': ('诊所主管', 'manager_home'),
    'HQ': ('总部管理', 'hq_home'),
    'FINANCE': ('财务', 'finance_home'),
    'SYSADMIN': ('技术管理', 'technical_home'),
}
CLINIC_ROLES = frozenset(('MANAGER', 'FRONT_DESK'))

def scope_fits(role, clinic):
    return role in ROLES and (clinic is None or role in CLINIC_ROLES)

def matches_context(payload, key, uid, role, clinic, revision):
    return type(payload) is dict and payload == {'key': str(key), 'uid': uid,
        'role': role, 'clinic': clinic, 'revision': revision}
