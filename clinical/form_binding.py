"""Bind clinical editing to its named patient, visit and current workspace."""
from django.core import signing
from django.core.exceptions import PermissionDenied
from adc_core.proposals import workspace_binding

SALT='adc.clinical-patient-form.c21.v1'


def patient_form_binding(actor,visit):
    return signing.dumps(dict(workspace=workspace_binding(actor,('DENTIST',)),visit=visit.pk,patient=visit.patient_id),salt=SALT)


def check_patient_form(actor,visit,token):
    try:data=signing.loads(token,salt=SALT,max_age=43200)
    except (signing.BadSignature,TypeError,ValueError):raise PermissionDenied('就诊人核对信息已失效，请返回本次负责就诊重新打开。')
    expected=dict(workspace=workspace_binding(actor,('DENTIST',)),visit=visit.pk,patient=visit.patient_id)
    if data!=expected:raise PermissionDenied('本页属于其他就诊人或工作身份，不能把其内容提交到当前就诊。')
