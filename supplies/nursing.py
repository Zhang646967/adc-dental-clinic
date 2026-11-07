"""Attributed clinical execution, distinct from the doctor's planned treatment."""
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from accounts.policies import require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from clinical.pharmacy_models import DispenseMovement
from clinical.plan_models import PerformedProcedure
from clinical.prescription_payload import required_text
from scheduling.coordination import lock_slots
from scheduling.models import Visit
from supplies.access import nurse
from supplies.models import NursingDuty, NursingExecution, SterileHold, SterilePack, StockLot, StockMovement
from supplies.pharmacy import administered
from supplies.stock import _quantity, _text, require_available

CONTRACT = 'adc.nursing.c5.v1'
ROLES = ('NURSE',)
Kind = NursingExecution.Kind
Duty = NursingDuty.Kind


def _time(value, label):
    try:
        moment=datetime.fromisoformat(value)
    except (TypeError,ValueError) as exc:
        raise RuleError(f'请填写有效的{label}。') from exc
    if timezone.is_naive(moment):
        raise RuleError(f'{label}须包含准确时区。')
    return moment


def _execution_data(actor, visit, kind, fields, *, lock=False):
    duty=nurse(actor,visit.clinic_id,Duty.EXECUTE,lock=lock)
    moment=_time(fields.get('observed_at'),'实际发生时间')
    if (visit.status!='CHECKED_IN' or not visit.attended_at or not visit.attended_at<=moment<=timezone.now()
            or not visit.patient.is_active):
        raise RuleError('仅可记录本店在诊患者实际到诊后的事实时间。')
    data=dict(kind=kind,visit=visit.pk,clinic=visit.clinic_id,patient=visit.patient_id,duty=duty.pk,
              observed_at=moment.isoformat(),reason=required_text(fields.get('reason'),'实际执行依据'))
    if kind==Kind.ESCALATE:
        return dict(data,quantity=0)
    if kind==Kind.ADMINISTER:
        rows=DispenseMovement.objects.filter(kind='ISSUE',line__quote__approval__version__prescription__visit=visit)
        issue=rows.filter(pk=fields.get('issue')).first()
        quantity=_quantity(fields.get('quantity'))
        if issue is None or not issue.requires_batch or moment<issue.occurred_at:
            raise RuleError('请选择本次已实际发出且批次可追溯的药品记录。')
        from clinical.dispensing import movement_totals
        if quantity>issue.quantity-movement_totals(issue.returns)['returned']-administered(issue):
            raise RuleError('给药数量超过该笔实际发出扣除退药和已执行后的数量。')
        trace=StockMovement.objects.filter(dispense=issue,kind='ISSUE').first()
        if trace is None:
            raise RuleError('本笔发药缺少原批次，请登记异常并交医师核对。')
        lots=StockLot.objects.select_for_update() if lock else StockLot.objects.all()
        lot=lots.get(pk=trace.lot_id)
        require_available(lot,0)
        return dict(data,issue=issue.pk,quantity=quantity)
    performed=PerformedProcedure.objects.filter(pk=fields.get('performed'),encounter__visit=visit,state='ACTIVE').first()
    if performed is None:
        raise RuleError('请选择本次有效的实际治疗。')
    if kind==Kind.MATERIAL:
        lots=StockLot.objects.filter(item__clinic_id=visit.clinic_id,item__kind__in=['MATERIAL','IMPLANT'])
        if lock:
            lots=lots.select_for_update(of=('self',))
        lot=lots.filter(pk=fields.get('lot')).first()
        if lot is None:
            raise RuleError('请选择本店的实际耗材批次。')
        quantity=_quantity(fields.get('quantity'))
        require_available(lot,quantity)
        return dict(data,performed=performed.pk,lot=lot.pk,quantity=quantity)
    if kind==Kind.STERILE:
        packs=SterilePack.objects.filter(clinic_id=visit.clinic_id)
        if lock:
            packs=packs.select_for_update()
        pack=packs.filter(pk=fields.get('pack')).first()
        if (pack is None or moment<pack.released_at or pack.valid_until<=timezone.now()
                or hasattr(pack,'hold') or hasattr(pack,'execution')):
            raise RuleError('请选择本店已放行、仍在有效期内且未使用的无菌包。')
        return dict(data,performed=performed.pk,pack=pack.pk,quantity=1)
    raise RuleError('请选择有效的护理记录类型。')


@sensitive_variables()
def prepare(actor,visit,kind,fields):
    data=_execution_data(actor,visit,kind,fields)
    return data,proposal(actor,CONTRACT,ROLES,data)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm(actor,token,confirmed,*,visit_id=None):
    if confirmed is not True:
        raise RuleError('请核对就诊人、实际发生时间和依据后明确确认。')
    p=read_proposal(actor,CONTRACT,ROLES,token)
    data,op=p['data'],p['operation']
    if visit_id is not None and visit_id!=data['visit']:
        raise RuleError('本次确认属于另一条就诊记录。')
    require_writable(actor)
    duty=nurse(actor,data['clinic'],Duty.EXECUTE,lock=True)
    if duty.pk!=data['duty']:
        raise RuleError('护理职责已变化，请重新核对。')
    prior=NursingExecution.objects.filter(operation_id=op,actor=actor,visit_id=data['visit']).first()
    if prior:
        return prior,True
    initial=Visit.objects.only('availability_slot_id').get(pk=data['visit'])
    lock_slots([initial.availability_slot_id])
    visit=Visit.objects.select_for_update().get(pk=data['visit'])
    actual=_execution_data(actor,visit,data['kind'],data,lock=True)
    if actual!=data:
        raise RuleError('就诊、实际治疗或批次条件已变化，请重新核对。')
    event=NursingExecution.objects.create(
        visit=visit,actor=actor,duty=duty,kind=data['kind'],performed_id=data.get('performed'),
        sterile_pack_id=data.get('pack'),issue_id=data.get('issue'),quantity=data['quantity'],
        observed_at=_time(data['observed_at'],'实际发生时间'),reason=data['reason'],operation_id=op,
    )
    if event.kind==Kind.MATERIAL:
        StockMovement.objects.create(lot_id=data['lot'],kind='USE',quantity=event.quantity,actor=actor,
                                    execution=event,reason=event.reason,operation_id=op)
    visit.lock_version+=1
    visit.save(update_fields=['lock_version'])
    emit(actor,'NURSING_'+event.kind,event,visit=visit,summary={'quantity':event.quantity})
    return event,False


PACK_CONTRACT = 'adc.sterile.c5.v1'


def _pack_data(actor,clinic,action,fields,*,lock=False):
    duty=nurse(actor,clinic,Duty.STERILITY,lock=lock)
    data=dict(action=action,clinic=clinic,duty=duty.pk)
    if action=='RELEASE':
        code=_text(fields.get('code'),'无菌包编号',60)
        reference=_text(fields.get('reference'),'灭菌批次与放行依据',120)
        processed=_time(fields.get('processed_at'),'灭菌时间')
        valid_until=_time(fields.get('valid_until'),'有效截止时间')
        if not processed<=timezone.now()<valid_until:
            raise RuleError('请核对实际灭菌时间和有效期限。')
        if SterilePack.objects.filter(clinic_id=clinic,code=code).exists():
            raise RuleError('本店已有同编号的无菌包，请查看原放行记录。')
        return dict(data,code=code,reference=reference,processed_at=processed.isoformat(),valid_until=valid_until.isoformat())
    if action!='HOLD':
        raise RuleError('请选择放行或停用。')
    packs=SterilePack.objects.filter(clinic_id=clinic)
    if lock:
        packs=packs.select_for_update()
    pack=packs.filter(pk=fields.get('pack')).first()
    if pack is None or hasattr(pack,'hold'):
        raise RuleError('本包不在当前门店或已停用。')
    return dict(data,pack=pack.pk,reason=required_text(fields.get('reason'),'停用依据'))


def prepare_pack(actor,clinic,action,fields):
    data=_pack_data(actor,clinic,action,fields)
    return data,proposal(actor,PACK_CONTRACT,ROLES,data)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_pack(actor,token,confirmed):
    if confirmed is not True:
        raise RuleError('请核对无菌包编号和来源后明确确认。')
    p=read_proposal(actor,PACK_CONTRACT,ROLES,token)
    data,op=p['data'],p['operation']
    require_writable(actor)
    duty=nurse(actor,data['clinic'],Duty.STERILITY,lock=True)
    if duty.pk!=data['duty']:
        raise RuleError('无菌放行职责已变化，请重新核对。')
    if data['action']=='RELEASE':
        old=SterilePack.objects.filter(operation_id=op,released_by=actor,clinic_id=data['clinic']).first()
    else:
        old=SterileHold.objects.filter(operation_id=op,actor=actor,pack__clinic_id=data['clinic']).first()
    if old:
        return old,True
    actual=_pack_data(actor,data['clinic'],data['action'],data,lock=True)
    if actual!=data:
        raise RuleError('无菌包条件已变化，请重新预览。')
    if data['action']=='RELEASE':
        from registry.models import Clinic
        # Different authorized releasers can prepare the same new code concurrently.
        Clinic.objects.select_for_update().get(pk=data['clinic'])
        if SterilePack.objects.filter(clinic_id=data['clinic'],code=data['code']).exists():
            raise RuleError('已有其他人员登记了同编号无菌包，请查看原记录。')
        obj=SterilePack.objects.create(
            clinic_id=data['clinic'],code=data['code'],process_reference=data['reference'],
            processed_at=_time(data['processed_at'],'灭菌时间'),valid_until=_time(data['valid_until'],'有效截止时间'),
            duty=duty,released_by=actor,operation_id=op,
        )
    else:
        obj=SterileHold.objects.create(pack_id=data['pack'],actor=actor,duty=duty,reason=data['reason'],operation_id=op)
    emit(actor,'STERILE_'+data['action'],obj,summary={'clinic':data['clinic']})
    return obj,False
