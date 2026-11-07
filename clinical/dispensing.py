"""C4.2 pharmacy commands and the care-facing settlement source."""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max, Q, Sum
from django.http import Http404
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from accounts.models import UserAccount
from accounts.policies import bindings, require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from clinical.pharmacy_models import DispenseMovement, PharmacyQuote, PharmacyQuoteLine, PharmacyStop
from clinical.prescription_access import active_duties, pharmacist, rehearsal_enabled
from clinical.prescription_models import Prescription, PrescriptionDuty
from clinical.prescription_payload import catalogue_for, required_text
from clinical.prescriptions import _approval_basis, current_version
from scheduling.coordination import lock_slots
from scheduling.models import Visit

CONTRACT = 'adc.pharmacy.c42.v1'
ROLES = ('PHARMACIST',)
ISSUE, RETURN = DispenseMovement.Kind
APPROVAL_LIFETIME = timedelta(hours=24)


def enabled():
    return rehearsal_enabled() and settings.ADC_DISPENSING_REHEARSAL


def dispenser(actor, clinic_id, *, lock=False):
    if not enabled():
        raise Http404('调配与发药演练当前未启用。')
    return pharmacist(actor, clinic_id, kind=PrescriptionDuty.Kind.DISPENSE, lock=lock)


def _approved(case):
    version = current_version(case)
    if not version or version.state != 'APPROVED':
        raise RuleError('请先取得当前处方版本的独立审方通过结果。')
    return version.decision


def _active_approval(case, approval, *, lock=False):
    if case.visit.status != 'CHECKED_IN' or PharmacyStop.objects.filter(approval=approval).exists():
        raise RuleError('本次发药已停止或接诊已关闭。')
    if timezone.now() >= approval.decided_at + APPROVAL_LIFETIME:
        raise RuleError('该合成处方的发药窗口已到期，请核对并停止剩余调配。')
    reviewers = active_duties(approval.actor_id, PrescriptionDuty.Kind.REVIEW).filter(
        pk=approval.duty_id, clinic_id=case.visit.clinic_id,
    )
    if lock:
        reviewers = reviewers.select_for_update(of=('self',))
    if not reviewers.exists() or not bindings(approval.actor).filter(
        role='PHARMACIST', scope_kind='CLINIC', clinic_id=case.visit.clinic_id,
    ).exists():
        raise RuleError('审方依据的授权已失效，请重新核对本次处方。')
    approval.version.prescription = case
    _approval_basis(approval.version, lock=lock)


def movement_totals(rows):
    return rows.aggregate(
        issued=Sum('quantity', filter=Q(kind=ISSUE), default=0),
        returned=Sum('quantity', filter=Q(kind=RETURN), default=0),
    )


def quote_rows(quote):
    return quote.lines.annotate(
        issued=Sum('movements__quantity', filter=Q(movements__kind=ISSUE), default=0),
        returned=Sum('movements__quantity', filter=Q(movements__kind=RETURN), default=0),
    ).order_by('pk')


def _action_data(actor, case, kind, reason, line_id=None, issue_id=None, quantity=None, *, lock=False):
    duty = dispenser(actor, case.visit.clinic_id, lock=lock)
    if case.prescriber_id == actor.pk:
        raise PermissionDenied('发药须由不同于开方医师的药师办理。')
    approval = _approved(case)
    quote = PharmacyQuote.objects.filter(approval=approval).first()
    data = dict(case=case.pk, approval=approval.pk, duty=duty.pk, kind=kind, reason=required_text(reason, '办理依据'))
    if kind in ('QUOTE', ISSUE):
        _active_approval(case, approval, lock=lock)
    if kind == 'QUOTE':
        if quote:
            raise RuleError('该版本已有划价，请查看已保存的明细。')
        entries = approval.version.items
        catalogue = catalogue_for(case.visit.clinic_id).filter(pk__in=[e['item_id'] for e in entries]).order_by('pk')
        if lock:
            catalogue = catalogue.select_for_update(of=('self',))
        by_id = {item.pk: item for item in catalogue}
        if len(by_id) != len(entries) or any(item.rehearsal_unit_price is None for item in by_id.values()):
            raise RuleError('请先维护全部条目的本店演练单价。')
        data['lines'] = [
            dict(item=entry['item_id'], name=entry['name'], unit=entry['quantity_unit'], quantity=entry['quantity'],
                 price=str(by_id[entry['item_id']].rehearsal_unit_price))
            for entry in entries
        ]
        return data
    if kind == 'STOP':
        if case.visit.status != 'CHECKED_IN' or PharmacyStop.objects.filter(approval=approval).exists():
            raise RuleError('只能停止本次在诊处方尚未发出的数量。')
        if quote and all(row.issued >= row.ordered_quantity for row in quote_rows(quote)):
            raise RuleError('该版本已经全部发出，无剩余数量可取消。')
        return data
    if kind not in (ISSUE, RETURN) or type(quantity) is not int or not 1 <= quantity <= 9999:
        raise RuleError('请选择发药或退药，并填写有效的实际数量。')
    line = PharmacyQuoteLine.objects.filter(pk=line_id, quote=quote).first() if quote else None
    if line is None:
        raise RuleError('请先完成划价，再选择本版本的药品条目。')
    if kind == ISSUE:
        issued = movement_totals(line.movements)['issued']
        if quantity > line.ordered_quantity - issued:
            raise RuleError('发药数量超过处方剩余授权，请核对办理记录。')
        issue_id = None
    else:
        if case.visit.status not in ('CHECKED_IN', 'COMPLETED'):
            raise RuleError('该次就诊当前不能登记退药。')
        issue = line.movements.filter(pk=issue_id, kind=ISSUE).first()
        if issue is None or quantity > issue.quantity - movement_totals(issue.returns)['returned']:
            raise RuleError('请核对原发药记录及可退数量。')
    return dict(data, line=line.pk, issue=issue_id, quantity=quantity)


@sensitive_variables()
def prepare(actor, case, kind, reason, *, line_id=None, issue_id=None, quantity=None):
    data = _action_data(actor, case, kind, reason, line_id, issue_id, quantity)
    return data, proposal(actor, CONTRACT, ROLES, data)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm(actor, token, confirmed, *, case_id=None):
    if confirmed is not True:
        raise RuleError('请核对本次药事办理并明确确认。')
    payload = read_proposal(actor, CONTRACT, ROLES, token)
    data, op = payload['data'], payload['operation']
    if case_id is not None and case_id != data['case']:
        raise RuleError('这次确认属于另一条处方，请返回原记录。')
    case = Prescription.objects.select_related('visit').get(pk=data['case'])
    approval = _approved(case)
    list(UserAccount.objects.select_for_update().filter(
        pk__in=[actor.pk, case.prescriber_id, approval.actor_id],
    ).order_by('pk'))
    require_writable(actor)
    duty = dispenser(actor, case.visit.clinic_id, lock=True)
    if duty.pk != data['duty'] or case.prescriber_id == actor.pk:
        raise PermissionDenied('发药职责已变化，请重新进入当前工作台。')
    lock_slots([case.visit.availability_slot_id])
    visit = Visit.objects.select_for_update().get(pk=case.visit_id)
    case = Prescription.objects.select_for_update().get(pk=case.pk)
    case.visit = visit
    approval = _approved(case)
    if approval.pk != data['approval']:
        raise RuleError('处方版本已变化，请重新预览。')
    kind = data['kind']
    if kind == 'QUOTE':
        previous = PharmacyQuote.objects.filter(operation_id=op, approval=approval, prepared_by=actor).first()
    elif kind == 'STOP':
        previous = PharmacyStop.objects.filter(operation_id=op, approval=approval, actor=actor).first()
    else:
        previous = DispenseMovement.objects.filter(
            operation_id=op, line__quote__approval=approval, actor=actor, kind=kind,
        ).first()
    if previous:
        return previous, True
    actual = _action_data(actor, case, kind, data['reason'], data.get('line'), data.get('issue'),
                          data.get('quantity'), lock=True)
    if actual != data:
        raise RuleError('划价、处方或办理条件已变化，请重新预览。')
    if kind == 'QUOTE':
        obj = PharmacyQuote.objects.create(approval=approval, prepared_by=actor, duty=duty,
                                           operation_id=op, reason=data['reason'])
        PharmacyQuoteLine.objects.bulk_create([
            PharmacyQuoteLine(quote=obj, item_id=row['item'], name_snapshot=row['name'], unit_snapshot=row['unit'],
                              ordered_quantity=row['quantity'], unit_price=row['price'])
            for row in data['lines']
        ])
    elif kind == 'STOP':
        obj = PharmacyStop.objects.create(approval=approval, actor=actor, duty=duty, reason=data['reason'],
                                          operation_id=op)
    else:
        obj = DispenseMovement.objects.create(line_id=data['line'], kind=kind, original_issue_id=data['issue'],
                                              quantity=data['quantity'], actor=actor, duty=duty,
                                              reason=data['reason'], operation_id=op)
    visit.lock_version += 1
    visit.save(update_fields=['lock_version'])
    emit(actor, 'PHARMACY_' + kind, obj, visit=visit, summary={'approval': approval.pk, 'quantity': data.get('quantity')})
    return obj, False


def settlement_sources(visit):
    """Exact issued-minus-returned quantities and cursors under the Visit lock."""
    return list(DispenseMovement.objects.filter(line__quote__approval__version__prescription__visit=visit)
        .values('line_id', 'line__unit_price').annotate(
            through=Max('pk'), issued=Sum('quantity', filter=Q(kind=ISSUE), default=0),
            returned=Sum('quantity', filter=Q(kind=RETURN), default=0),
        ).filter(issued__gt=0).order_by('line_id'))


def completion_blocker(visit):
    case = Prescription.objects.filter(visit=visit).first()
    version = current_version(case) if case else None
    if not version:
        return ''
    if version.state == 'PENDING' and enabled():
        return '处方仍待审方或撤回，请先处理处方。'
    if version.state != 'APPROVED':
        return ''
    approval = version.decision
    quote = PharmacyQuote.objects.filter(approval=approval).first()
    if not enabled() and not quote:
        return ''
    if PharmacyStop.objects.filter(approval=approval).exists():
        return ''
    if quote and quote.lines.exists() and all(row.issued == row.ordered_quantity for row in quote_rows(quote)):
        return ''
    return '请由药师核对实际发药或明确取消剩余调配，再完成结算。'
