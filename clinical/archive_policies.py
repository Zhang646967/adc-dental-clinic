"""Responsible author and independently appointed, service-scoped archive reviewer."""
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from clinical.authority import require_visit_authority,require_reviewer,professional_scope,visit_service_id
from clinical.archive_sources import required_services
from clinical.models import ClinicalReviewerAppointment
from workspaces.context import require_active
from adc_core.rules import RuleError


def owner(actor,visit,*,lock=False):
    return require_visit_authority(actor,visit,'RECORD',always=True,lock=lock)


def reviewer(actor,visit,snapshot,*,author_id,lock=False):
    appointed=require_reviewer(actor,visit.clinic_id,lock=lock)
    if not appointed.can_review_archives:raise PermissionDenied('尚未登记本店独立医务归档审核职责，请联系机构核对委任。')
    if actor.pk==author_id or actor.dentist_id==visit.dentist_id:
        raise PermissionDenied('归档和补正须由另一名获委任医师审核，不能切换岗位审核本人记录。')
    for service_id in required_services(visit,snapshot):
        professional_scope(actor.pk,visit.clinic_id,service_id,'READ',lock=lock)
    return appointed


def stamp(actor,visit,snapshot,appointment):
    owner_scope=professional_scope(visit.dentist.useraccount.pk,visit.clinic_id,visit_service_id(visit),'RECORD')
    scopes=[professional_scope(actor.pk,visit.clinic_id,s,'READ') for s in required_services(visit,snapshot)]
    return dict(reviewer=appointment.pk,revision=appointment.revision,
        owner_scope=[owner_scope.pk,owner_scope.revision],scopes=[[s.pk,s.revision] for s in scopes])


def approval_valid(visit,actor_id,scope):
    from clinical.models import ProfessionalAuthorization
    now=timezone.now()
    if not UserAccount.objects.filter(pk=actor_id,is_active=True,dentist__is_active=True).exists():return False
    if not RoleAssignment.objects.filter(user_id=actor_id,role='DENTIST',scope_kind='SELF_DENTIST',is_active=True).exists():return False
    if not ClinicalReviewerAppointment.objects.filter(pk=scope.get('reviewer'),user_id=actor_id,clinic_id=visit.clinic_id,
        revision=scope.get('revision'),is_active=True,can_review_archives=True,valid_from__lte=now,valid_until__gt=now).exists():return False
    try:
        owner_id=visit.dentist.useraccount.pk
        auth=professional_scope(owner_id,visit.clinic_id,visit_service_id(visit),'RECORD')
        if [auth.pk,auth.revision]!=scope['owner_scope']:return False
        for pk,rev in scope['scopes']:
            old=ProfessionalAuthorization.objects.get(pk=pk)
            current=professional_scope(actor_id,visit.clinic_id,old.service_id,'READ')
            if [current.pk,current.revision]!=[pk,rev]:return False
    except (PermissionDenied,ProfessionalAuthorization.DoesNotExist,KeyError):return False
    return True


def reviewer_options(visit,snapshot,*,author_id):
    now=timezone.now();result=[]
    rows=ClinicalReviewerAppointment.objects.filter(clinic_id=visit.clinic_id,is_active=True,can_review_archives=True,
        user__is_active=True,user__dentist__is_active=True,valid_from__lte=now,valid_until__gt=now).exclude(user_id=author_id).exclude(user__dentist_id=visit.dentist_id).select_related('user__dentist').order_by('pk')
    for row in rows:
        try:
            for service in required_services(visit,snapshot):professional_scope(row.user_id,visit.clinic_id,service,'READ')
        except PermissionDenied:continue
        result.append(row)
    return result


def choose_reviewer(visit,snapshot,*,author_id,appointment_id=None):
    options=reviewer_options(visit,snapshot,author_id=author_id)
    for row in options:
        if appointment_id is None or row.pk==int(appointment_id):return row
    raise RuleError('没有所选有效的独立医务归档审核人，请联系机构登记职责及本服务查阅范围。')
