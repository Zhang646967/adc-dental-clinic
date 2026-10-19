"""Bounded candidate scheduling -> explicit manager offer -> explicit patient booking."""
from datetime import timedelta,datetime
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from accounts.policies import require_writable,lock_clinic_grant,bindings
from adc_core.commands import business_errors
from adc_core.rules import RuleError,validate_interval,OCCUPYING_STATUSES
from care.audit import emit
from patients.models import Patient
from portal.policies import patient_access
from registry.models import Clinic,Dentist
from scheduling.coordination import lock_slots
from scheduling.models import Visit,AvailabilitySlot
from scheduling.services import create_visit_locked
from coordination.models import WaitRequest,WaitOffer,SchedulePlan
from coordination.reservations import lock_resources,assert_free
from coordination.policies import require_owner_or_front
from coordination.solver import maximum_matching,overlaps
STEP=timedelta(minutes=30)

@business_errors
@transaction.atomic
def join_waitlist(*,actor,clinic_id,earliest,latest,patient_no=None,dentist_id=None,service_id=None):
    require_writable(actor)
    clinic=Clinic.objects.get(pk=clinic_id,is_active=True)
    ctx=getattr(actor,'_adc_workspace',None)
    if bindings(actor).filter(role='FRONT_DESK',scope_kind='CLINIC',clinic_id=clinic_id).exists():
        lock_clinic_grant(actor,clinic_id);patient=Patient.objects.get(patient_no=patient_no,is_active=True)
    else:patient=patient_access(actor,lock=True).patient
    from scheduling.resources import policy,service_for
    resource_policy=policy(clinic_id)
    service=service_for(clinic_id,service_id) if resource_policy else None
    if resource_policy and resource_policy.state!='ENABLED':raise RuleError('本店资源正在核对，请先保存接待单与联系期限。')
    if service and (not service.is_active or not service.department.is_active or
        (dentist_id and not service.dentists.filter(pk=dentist_id).exists())):raise RuleError('所选服务或医师不适配。')
    from coordination.windows import validate_wait_window, WindowError
    try:
        if service:validate_wait_window(earliest, latest, now=timezone.now(), minimum=timedelta(minutes=service.duration_minutes))
        else:validate_wait_window(earliest, latest, now=timezone.now())
    except WindowError as exc:
        raise RuleError(str(exc)) from exc
    if dentist_id:Dentist.objects.get(pk=dentist_id,is_active=True)
    lock_resources(patients=[patient.pk])
    if WaitRequest.objects.filter(patient=patient,state__in=['WAITING','OFFERED']).exists():
        raise RuleError('已有一条有效候补。请先处理或退出，避免重复占位。')
    entry=WaitRequest.objects.create(patient=patient,clinic=clinic,preferred_dentist_id=dentist_id,
        earliest=earliest,latest=latest,created_by=actor,service=service)
    emit(actor,'WAIT_JOINED',entry,summary={'clinic_id':clinic_id})
    return entry

@business_errors
@transaction.atomic
def withdraw(*,actor,entry_id):
    require_writable(actor)
    entry=WaitRequest.objects.get(pk=entry_id);require_owner_or_front(actor,entry,lock=True)
    pending=list(WaitOffer.objects.filter(request=entry,state='PENDING'))
    slots=lock_slots([o.slot_id for o in pending])
    lock_resources(patients=[entry.patient_id],dentists=[s.dentist_id for s in slots.values()])
    from scheduling.resources import lock_physical
    lock_physical(entry.clinic_id)
    entry=WaitRequest.objects.select_for_update().get(pk=entry_id)
    if entry.state=='WITHDRAWN':return entry
    if entry.state=='BOOKED':raise RuleError('候补已形成预约。请在预约页面办理取消。')
    from scheduling.resources import release_offer_locked
    for offer in WaitOffer.objects.filter(request=entry,state='PENDING'):release_offer_locked(offer,'WITHDRAWN')
    WaitOffer.objects.filter(request=entry,state='PENDING').update(state='REVOKED')
    entry.state='WITHDRAWN';entry.revision+=1;entry.save(update_fields=['state','revision'])
    emit(actor,'WAIT_WITHDRAWN',entry);return entry

@business_errors
@transaction.atomic
def create_plan(*,actor,clinic_id):
    lock_clinic_grant(actor,clinic_id,roles=('MANAGER',))
    from scheduling.resources import policy
    resource_policy=policy(clinic_id)
    if resource_policy:
        if resource_policy.state!='ENABLED':raise RuleError('资源核对未完成，不能发布新的资源建议。')
        from scheduling.resource_waitlist import create_resource_plan
        return create_resource_plan(actor,clinic_id)
    now=timezone.now()
    entries=list(WaitRequest.objects.filter(clinic_id=clinic_id,state='WAITING',patient__is_active=True,latest__gt=now).order_by('created_at','pk')[:60])
    # Bounded finite candidate graph. Truncation is visible in metadata.
    slots=list(AvailabilitySlot.objects.filter(clinic_id=clinic_id,is_active=True,booking_paused=False,dentist__is_active=True,
        clinic__is_active=True,ends_at__gt=now,starts_at__lt=now+timedelta(days=14)).order_by('starts_at','id')[:80])
    occupied=list(Visit.objects.filter(status__in=OCCUPYING_STATUSES,scheduled_end__gt=now,scheduled_start__lt=now+timedelta(days=14)).values('patient_id','dentist_id','scheduled_start','scheduled_end'))
    held=list(WaitOffer.objects.filter(state='PENDING',expires_at__gt=now).values('request__patient_id','slot__dentist_id','starts_at','ends_at'))
    cells={};limit_hit=False
    for slot in slots:
        start=slot.starts_at
        if start<=now:
            start+=((now-start)//STEP+1)*STEP
        while start+STEP<=min(slot.ends_at,now+timedelta(days=14)):
            end=start+STEP
            if not any(v['dentist_id']==slot.dentist_id and overlaps(start,end,v['scheduled_start'],v['scheduled_end']) for v in occupied) and not any(h['slot__dentist_id']==slot.dentist_id and overlaps(start,end,h['starts_at'],h['ends_at']) for h in held):
                cells[(slot.pk,start.isoformat())]=(slot,start,end)
            if len(cells)>=200:limit_hit=True;break
            start=end
        if limit_hit:break
    edges={}
    for e in entries:
        edges[e.pk]=[key for key,(slot,start,end) in cells.items() if start>=e.earliest and end<=e.latest
            and (not e.preferred_dentist_id or slot.dentist_id==e.preferred_dentist_id)
            and not any(v['patient_id']==e.patient_id and overlaps(start,end,v['scheduled_start'],v['scheduled_end']) for v in occupied)
            and not any(h['request__patient_id']==e.patient_id and overlaps(start,end,h['starts_at'],h['ends_at']) for h in held)]
    result=maximum_matching([e.pk for e in entries],edges)
    byid={e.pk:e for e in entries}
    suggestions=[{'request_id':i,'request_revision':byid[i].revision,'slot_id':cell[0],'start':cell[1],
        'end':cells[cell][2].isoformat(),'intake_revision':cells[cell][0].intake_revision} for i,cell in result.pairs]
    plan=SchedulePlan.objects.create(clinic_id=clinic_id,created_by=actor,suggestions=suggestions,
        metadata={'algorithm':result.algorithm,'status':result.status,'unassigned':list(result.unassigned),
        'request_count':len(entries),'cell_count':len(cells),'request_limit_hit':len(entries)==60,'slot_limit_hit':len(slots)==80,'bounded':True,'cell_limit_hit':limit_hit,
        'limits':{'requests':60,'slots':80,'cells':200},'duration_minutes':30,'as_of':now.isoformat(),
        'notice':'仅对当前枚举的固定30分钟候选图最大化安排数；不含椅位、医学资格或通勤优化。'})
    emit(actor,'SCHEDULE_SUGGESTED',plan,summary={'matched':len(suggestions),'clinic_id':clinic_id})
    return plan

@business_errors
@transaction.atomic
def publish_plan(*,actor,plan_id):
    require_writable(actor)
    preview=SchedulePlan.objects.get(pk=plan_id)
    lock_clinic_grant(actor,preview.clinic_id,roles=('MANAGER',))
    slots=lock_slots([s['slot_id'] for s in preview.suggestions])
    ids=[s['request_id'] for s in preview.suggestions]
    entries={e.pk:e for e in WaitRequest.objects.filter(pk__in=ids)}
    lock_resources(patients=[e.patient_id for e in entries.values()],dentists=[s.dentist_id for s in slots.values()])
    from scheduling.resources import lock_physical,release_expired_locked
    lock_physical(preview.clinic_id);release_expired_locked(preview.clinic_id)
    plan=SchedulePlan.objects.select_for_update().get(pk=plan_id)
    if plan.state=='PUBLISHED':return plan
    if not plan.suggestions:raise RuleError('没有可发布的候选安排。请调整出诊或候补范围。')
    if timezone.now()-plan.created_at>timedelta(minutes=15):raise RuleError('建议已超过15分钟，请重新生成。')
    now=timezone.now()
    for row in plan.suggestions:
        e=WaitRequest.objects.select_for_update().get(pk=row['request_id'],clinic_id=plan.clinic_id)
        s=slots[row['slot_id']];start=datetime.fromisoformat(row['start']);end=datetime.fromisoformat(row['end'])
        from scheduling.intake_rules import require_new_admission, IntakeError
        try:
            require_new_admission(active=s.is_active, paused=s.booking_paused)
        except IntakeError as exc:
            raise RuleError('草案涉及暂停接收的出诊；本批未发布，请重新生成。') from exc
        if e.state!='WAITING' or e.revision!=row['request_revision'] or not e.patient.is_active:
            raise RuleError('候补需求已经变化；未发布本批邀约，请重新生成。')
        if s.clinic_id!=plan.clinic_id or not s.is_active or not s.dentist.is_active or not s.clinic.is_active or start<=now or start<s.starts_at or end>s.ends_at or (end-start!=STEP if plan.metadata.get('algorithm')!='RESOURCE_GREEDY_V1' else e.service_id!=row.get('service_id')) or start<e.earliest or end>e.latest or (e.preferred_dentist_id and e.preferred_dentist_id!=s.dentist_id):
            raise RuleError('出诊安排或时间条件已经变化。')
        revision = row.get('intake_revision', 0)
        if type(revision) is not int or revision != s.intake_revision:
            raise RuleError('草案形成后出诊接收状态已变化；请重新生成建议。')
        assert_free(e.patient_id,s.dentist_id,start,end)
        from scheduling.resources import choose_bundle,claim_locked
        bundle=choose_bundle(slot=s,start=start,end=end,service_id=row.get('service_id'),expected=row.get('resources'),locked=True)
        offer=WaitOffer.objects.create(request=e,plan=plan,slot=s,starts_at=start,ends_at=end,expires_at=min(now+timedelta(minutes=15),start))
        claim_locked(actor=actor,snapshot=bundle,start=start,end=end,offer=offer,reason='主管发布限时邀约')
        e.state='OFFERED';e.revision+=1;e.save(update_fields=['state','revision'])
    plan.state='PUBLISHED';plan.published_at=now;plan.save(update_fields=['state','published_at'])
    emit(actor,'SCHEDULE_OFFERS_PUBLISHED',plan,summary={'offers':len(plan.suggestions)})
    return plan

@business_errors
@transaction.atomic
def answer_offer(*,actor,offer_id,accept):
    require_writable(actor)
    if type(accept) is not bool:raise RuleError('必须明确接受或拒绝。')
    preview=WaitOffer.objects.select_related('request').get(pk=offer_id)
    require_owner_or_front(actor,preview.request,lock=True)
    from reception.services import lock_waitlist_case
    reception_case=lock_waitlist_case(preview.request_id)
    s=lock_slots([preview.slot_id])[preview.slot_id]
    lock_resources(patients=[preview.request.patient_id],dentists=[s.dentist_id])
    from scheduling.resources import lock_physical
    lock_physical(preview.request.clinic_id)
    e=WaitRequest.objects.select_for_update().get(pk=preview.request_id)
    o=WaitOffer.objects.select_for_update().get(pk=offer_id)
    if o.state=='ACCEPTED' and accept:return o
    if o.state=='DECLINED' and not accept:return o
    if o.state!='PENDING' or e.state!='OFFERED' or o.expires_at<=timezone.now():
        raise RuleError('邀约已失效；没有创建预约。请刷新候补页面或联系前台。')
    if accept:
        # Honor this exact existing promise despite an intake pause; never release it early.
        # The common helper revalidates the locked offer and ignores only its own hold.
        v=create_visit_locked(actor=actor,patient=e.patient,slot=s,start=o.starts_at,end=o.ends_at,
            chief_complaint='候补邀约明确确认；具体治疗由接诊人员复核。',honor_offer_id=o.pk)
        o.visit=v;o.state='ACCEPTED';e.state='BOOKED'
        from reception.services import link_waitlist_result_locked
        link_waitlist_result_locked(reception_case,e,v,actor)
    else:
        from scheduling.resources import release_offer_locked
        release_offer_locked(o,'DECLINED')
        o.state='DECLINED';e.state='WAITING'
    o.save(update_fields=['visit','state']);e.revision+=1;e.save(update_fields=['state','revision'])
    emit(actor,'WAIT_OFFER_ANSWERED',o,visit=o.visit,summary={'accepted':accept})
    return o

@business_errors
@transaction.atomic
def expire_clinic_offers(*,actor,clinic_id):
    lock_clinic_grant(actor,clinic_id,roles=('MANAGER','FRONT_DESK'))
    previews=list(WaitOffer.objects.filter(request__clinic_id=clinic_id,state='PENDING',expires_at__lte=timezone.now()).select_related('request')[:200])
    slots=lock_slots([o.slot_id for o in previews])
    lock_resources(patients=[o.request.patient_id for o in previews],dentists=[s.dentist_id for s in slots.values()])
    from scheduling.resources import lock_physical
    lock_physical(clinic_id)
    count=0
    for preview in previews:
        e=WaitRequest.objects.select_for_update().get(pk=preview.request_id)
        o=WaitOffer.objects.select_for_update().get(pk=preview.pk)
        if o.state!='PENDING' or o.expires_at>timezone.now():continue
        from scheduling.resources import release_offer_locked
        release_offer_locked(o,'EXPIRED')
        o.state='EXPIRED';o.save(update_fields=['state'])
        if e.state=='OFFERED':e.state='WAITING';e.revision+=1;e.save(update_fields=['state','revision'])
        emit(actor,'WAIT_OFFER_EXPIRED',o);count+=1
    return count
