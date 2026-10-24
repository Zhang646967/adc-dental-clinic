"""UC-12B: bounded numerical correction, complete new version, two actors.
Does not implement clinical identity changes, tax voiding, refunds or rebooking.
"""
from copy import deepcopy
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from accounts.models import RoleAssignment,UserAccount
from accounts.policies import bindings,require_writable
from adc_core.commands import business_errors,assert_revision
from adc_core.rules import RuleError,total_amount
from care.audit import emit
from care.models import CorrectionRequest,VisitRecordVersion,TreatmentRecord,Invoice
from care.services import _lock_care,_bump
from care.correction_rules import correction_values,guard_review
from accounts.finance_access import lock_finance_write
from scheduling.coordination import lock_slots
from scheduling.models import Visit

@business_errors
@transaction.atomic
def request_line_correction(*,actor,visit_id,expected_version,line_id,quantity,unit_price,reason):
    v=_lock_care(actor,visit_id);assert_revision(v,expected_version)
    if v.status!='COMPLETED':raise RuleError('本版只支持已治疗完成账单的数量或单价误录更正。')
    invoice=Invoice.objects.select_for_update().get(visit=v)
    base=VisitRecordVersion.objects.get(pk=invoice.current_record_version_id,state='PUBLISHED')
    source=list(base.treatment_lines.order_by('line_no'))
    item=next((line for line in source if line.pk==line_id),None)
    if item is None:raise RuleError('必须选择当前有效版本中的一行。')
    q,p,amount,reason=correction_values(quantity,unit_price,reason)
    if (q,p)==(item.quantity,item.unit_price):raise RuleError('数量与单价没有变化，无需更正。')
    if CorrectionRequest.objects.filter(visit=v,status='OPEN').exists():raise RuleError('该就诊已有待审核更正。')
    if v.record_versions.filter(state='DRAFT').exists():raise RuleError('存在未处理的工作草稿。')
    req=CorrectionRequest.objects.create(visit=v,kind='RECORD_CONTENT',base_record_version=base,
        expected_visit_lock_version=v.lock_version+1,requester=actor,dentist_confirmed_by=actor,reason=reason,
        proposed_change={'line_no':item.line_no,'quantity':str(q),'unit_price':str(p),'scope':'quantity_and_price_only'})
    rev=(v.record_versions.aggregate(n=Max('revision_no'))['n'] or 0)+1
    draft=VisitRecordVersion.objects.create(visit=v,revision_no=rev,state='DRAFT',outcome=base.outcome,
        previous_version=base,correction_request=req,prepared_by=actor,
        allergy_review_snapshot=deepcopy(base.allergy_review_snapshot),billing_header_snapshot=deepcopy(base.billing_header_snapshot),
        clinical_note=base.clinical_note,no_treatment_reason=base.no_treatment_reason)
    for old in source:
        changed=old.pk==item.pk
        TreatmentRecord.objects.create(record_version=draft,line_no=old.line_no,treatment_type_id=old.treatment_type_id,
            name_snapshot=old.name_snapshot,unit_snapshot=old.unit_snapshot,
            quantity=q if changed else old.quantity,unit_price=p if changed else old.unit_price,
            line_amount=amount if changed else old.line_amount,confirmed_by=actor,confirmed_at=timezone.now(),
            price_reason=reason if changed else old.price_reason)
    draft.total_amount=total_amount(draft.treatment_lines.values_list('line_amount',flat=True));draft.save(update_fields=['total_amount'])
    _bump(v);emit(actor,'CORRECTION_REQUESTED',req,visit=v,reason=reason,summary={'base_revision':base.revision_no,'new_revision':rev})
    return req

@business_errors
@transaction.atomic
def review_correction(*,actor,request_id,decision,reason):
    if decision not in ('approve','reject'):raise RuleError('未知审核操作。')
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=500:raise RuleError('请填写审核说明。')
    if not bindings(actor).filter(role='FINANCE',scope_kind='CHAIN').exists():
        raise PermissionDenied('需要财务审核授权。')
    preview=CorrectionRequest.objects.select_related('visit').get(pk=request_id)
    # Shared account rows precede grants and scheduling rows, in stable PK order.
    users={u.pk:u for u in UserAccount.objects.select_for_update().filter(
        pk__in=[actor.pk,preview.requester_id]).order_by('pk')}
    lock_finance_write(actor)
    preparer=users[preview.requester_id]
    grant=RoleAssignment.objects.select_for_update().filter(user=preparer,is_active=True,role='DENTIST',scope_kind='SELF_DENTIST').first()
    lock_slots([preview.visit.availability_slot_id])
    v=Visit.objects.select_for_update().get(pk=preview.visit_id)
    req=CorrectionRequest.objects.select_for_update().get(pk=request_id)
    invoice=Invoice.objects.select_for_update().get(visit=v)
    if req.requester_id==actor.pk:raise RuleError('申请人与审核人必须为不同账号。')
    if req.status!='OPEN':
        if decision=='approve' and req.status=='APPLIED' and req.reviewer_id==actor.pk:return invoice
        raise RuleError('该申请已处理。')
    draft=VisitRecordVersion.objects.select_for_update().get(correction_request=req,state='DRAFT')
    if decision=='reject':
        req.status='REJECTED';req.reviewer=actor;req.save(update_fields=['status','reviewer'])
        draft.state='ABANDONED';draft.save(update_fields=['state']);_bump(v)
        emit(actor,'CORRECTION_REJECTED',req,visit=v,reason=reason.strip());return invoice
    guard_review(req.requester_id,actor.pk,req.status,req.base_record_version_id,invoice.current_record_version_id,req.expected_visit_lock_version,v.lock_version)
    if req.kind!='RECORD_CONTENT' or draft.visit_id!=v.pk or draft.previous_version_id!=req.base_record_version_id or draft.outcome!='TREATED':
        raise RuleError('更正范围或版本关联不一致。')
    # Authorization of the preparer must still exist at application time.
    if not preparer.is_active or not grant or preparer.dentist_id!=v.dentist_id or req.dentist_confirmed_by_id!=preparer.pk:
        raise RuleError('原申请人的负责牙医授权已经失效，请拒绝该申请。')
    from clinical.authority import professional_controls
    if professional_controls(v.clinic_id):
        from clinical.authority import professional_scope,visit_service_id
        professional_scope(preparer.pk,v.clinic_id,visit_service_id(v),'RECORD',lock=True)
    base=invoice.current_record_version
    original=list(base.treatment_lines.order_by('line_no'));new=list(draft.treatment_lines.order_by('line_no'))
    if len(original)!=len(new) or not new:raise RuleError('更正不能增加或删除实际治疗项目。')
    changed=[]
    for a,b in zip(original,new):
        if (a.line_no,a.treatment_type_id,a.name_snapshot,a.unit_snapshot)!=(b.line_no,b.treatment_type_id,b.name_snapshot,b.unit_snapshot):raise RuleError('本版更正不能替换项目和单位。')
        _,_,expected,_=correction_values(b.quantity,b.unit_price,b.price_reason or req.reason)
        if b.line_amount!=expected or b.confirmed_by_id!=preparer.pk or b.confirmed_at is None:raise RuleError('更正金额或确认信息不一致。')
        if (a.quantity,a.unit_price)!=(b.quantity,b.unit_price):changed.append(b.line_no)
    target=next((x for x in new if x.line_no==req.proposed_change.get('line_no')),None)
    if target is None or target.quantity!=Decimal(req.proposed_change['quantity']) or target.unit_price!=Decimal(req.proposed_change['unit_price']):
        raise RuleError('更正草稿与已确认申请不一致。')
    if changed!=[req.proposed_change.get('line_no')]:raise RuleError('只允许更正申请指定的一行。')
    if draft.billing_header_snapshot!=base.billing_header_snapshot or draft.allergy_review_snapshot!=base.allergy_review_snapshot or draft.clinical_note!=base.clinical_note:
        raise RuleError('本版更正不能改动临床记录或账单身份。')
    if draft.total_amount!=total_amount(x.line_amount for x in new):raise RuleError('更正总额不一致。')
    now=timezone.now()
    req.status='APPLIED';req.reviewer=actor;req.applied_at=now;req.save(update_fields=['status','reviewer','applied_at'])
    draft.reviewed_by=actor;draft.published_at=now;draft.state='PUBLISHED';draft.save(update_fields=['reviewed_by','published_at','state'])
    invoice.current_record_version=draft;invoice.save(update_fields=['current_record_version'])
    _bump(v);emit(actor,'CORRECTION_APPLIED',req,visit=v,reason=reason.strip(),summary={'revision':draft.revision_no,'invoice_no':invoice.invoice_no})
    return invoice
