"""Authorization status is separate from the protected clinical projection."""
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from portal.medical_authority import latest_version
from portal import medical_proxies


def case_data(actor,case,*,account=False):
    if account:
        from portal.models import PatientAccess
        if case.delegate_id!=actor.pk and not PatientAccess.objects.filter(user=actor,patient=case.patient,is_active=True).exists():
            raise PermissionDenied('只能核对当前账号相关的医疗授权办理状态。')
        available=False
        if actor._adc_workspace.role=='PATIENT':
            try:
                from portal.medical_authority import verify_version
                medical_proxies.can_read(actor,case)
                verify_version(latest_version(case));available=True
            except PermissionDenied:pass
        if not available:
            # Pending/unavailable authority reveals no unverified patient's
            # identity, material references, plan steps or clinical text.
            v=latest_version(case)
            label='已到期' if case.state=='ACTIVE' and v.valid_until<=timezone.now() else case.get_state_display()
            return dict(id=case.pk,patient='医疗代理办理单',clinic=case.clinic.name,kind=case.get_kind_display(),
                state=case.state,status_label=label,revision=case.revision,version_number=v.number,
                history=[],can_select=False,can_edit=False,clinical_available=False,status_only=True)
    medical_proxies.can_read(actor,case);v=latest_version(case)
    state='已到期' if case.state=='ACTIVE' and v.valid_until<=timezone.now() else case.get_state_display()
    role=actor._adc_workspace.role
    return dict(id=case.pk,patient=case.patient.name,patient_no=case.patient.patient_no,clinic=case.clinic.name,
        delegate=case.delegate.username,delegate_name=v.delegate_name,kind=case.get_kind_display(),state=case.state,status_label=state,revision=case.revision,
        version=v.pk,version_number=v.number,plan=v.plan_id,steps=list(v.scopes.values_list('step_id',flat=True)),
        identity_reference=v.identity_reference,authority_reference=v.authority_reference,applicability=v.applicability,
        valid_from=v.valid_from.isoformat(),valid_until=v.valid_until.isoformat(),
        history=[dict(id=e.pk,action=e.action,state=dict(case.STATES).get(e.resulting_state,e.resulting_state),
            note=e.note if role=='DENTIST' or e.action in ('SUBMIT','MATERIALS_OK') else '已保留办理结论；临床文字不在资料核验页面展示。',
            version=e.version.number,recorded_at=e.recorded_at.isoformat()) for e in case.events.select_related('version').order_by('sequence')],
        can_select=case.delegate_id==actor.pk and case.state=='ACTIVE' and v.valid_from<=timezone.now()<v.valid_until,
        can_edit=role=='FRONT_DESK' and case.state in ('RETURNED','SUSPENDED'),
        clinical_available=case.state=='ACTIVE' and v.valid_from<=timezone.now()<v.valid_until)
