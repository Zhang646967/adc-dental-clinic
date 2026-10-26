"""Bounded business work lists, read from one authorized PostgreSQL snapshot.

Links open existing workflows. A displayed item never authorizes a command or
changes a visit, offer, task, invoice, cost, permission or notification.
"""
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, F
from django.urls import reverse
from django.utils import timezone

from accounts.finance_access import require_finance_read
from adc_core.snapshots import reporting_snapshot
from care.models import CorrectionRequest, Invoice
from coordination.models import CoordinationTask, WaitOffer, WaitRequest
from finance.models import Quarter
from finance.selectors import _quarter_work_rows
from scheduling.models import AvailabilitySlot,Visit
from scheduling.selectors import visible_visits
from scheduling.worklists import visit_queue
from workspaces.context import valid_context
from workspaces.models import WorkspaceContext

PREVIEW_LIMIT = 5
QUARTER_LIMIT = 6


def _url(name, **query):
    return reverse(name) + ('?' + urlencode(query) if query else '')


def _group(key, title, query, mapper, all_url, note):
    total = query.count()
    return {'key': key, 'title': title, 'total': total, 'items': tuple(mapper(row) for row in query[:PREVIEW_LIMIT]),
            'all_url': all_url, 'note': note, 'limit': PREVIEW_LIMIT}


def _visit_item(visit, *, clinical=False, metadata=False):
    return {'title': visit.visit_no if metadata else visit.patient.name,
            'detail': f'{visit.clinic.name} · {visit.dentist.name}', 'when': visit.scheduled_start,
            'url': (_url('visits', q=visit.visit_no) if metadata else
                    reverse('care_workspace' if clinical else 'visit_detail', args=[visit.pk])),
            'action': '核对业务状态' if metadata else ('进入接诊' if clinical else '打开预约核实')}


def _task_item(task):
    return {'title': f'协调任务 #{task.pk}', 'detail': f'{task.slot.dentist.name} · {task.get_state_display()}' + (' · 跟进逾期' if task.due_at and task.due_at<timezone.now() else ''),
            'when': task.due_at or task.slot.starts_at, 'url': reverse('coordination_task_detail', args=[task.slot_id, task.pk]),
            'action': '核对任务'}


def _correction_group(actor, *, finance):
    rows = CorrectionRequest.objects.filter(kind='RECORD_CONTENT', status='OPEN')
    if finance:
        rows = rows.exclude(requester_id=actor.pk)
    else:
        rows = rows.filter(requester_id=actor.pk, visit__dentist_id=actor.dentist_id)
    rows = rows.select_related('visit').order_by('requested_at', 'pk')
    return _group('corrections', '可独立审核的账单更正' if finance else '本人更正申请待审核', rows,
                  lambda row: {'title': f'更正申请 #{row.pk}', 'detail': row.visit.visit_no,
                               'when': row.requested_at, 'url': reverse('correction_detail', args=[row.pk]),
                               'action': '核对账单版本'},
                  _url('corrections', queue='review' if finance else 'open'),
                  '按申请时间先后跟进；旧账单继续保留，申请人与审核人必须不同。')


def _quarters(actor, now):
    require_finance_read(actor)
    rows = _quarter_work_rows(Quarter.objects.order_by('-year', '-quarter_no', '-pk')[:QUARTER_LIMIT], now)
    pending = tuple(row for row in rows if not row['ready'])
    return {'key': 'quarters', 'title': '近期季度资料待补齐', 'total': len(pending),
            'items': tuple({'title': f"{row['year']} Q{row['number']}", 'detail': '；'.join(row['reasons']),
                            'url': reverse('quarter_detail', args=[row['id']]), 'action': '核对清单与成本'}
                           for row in pending),
            'all_url': reverse('finance_quarters'),
            'note': f'核对最近 {QUARTER_LIMIT} 个已建季度；更早季度请打开完整列表。未填、草稿与确认零分别处理。',
            'limit': QUARTER_LIMIT}


def workspace_worklist(actor):
    with reporting_snapshot():
        context = getattr(actor, '_adc_workspace', None)
        if (context is None or not valid_context(actor, context) or
                not WorkspaceContext.objects.filter(pk=context.pk, user_id=actor.pk, role=context.role,
                    clinic_id=context.clinic_id, revision=context.revision).exists()):
            raise PermissionDenied('当前工作身份已变化，请重新选择。')
        role = context.role
        if role in ('FRONT_DESK', 'MANAGER') and context.clinic_id is None:
            raise PermissionDenied('请先选择诊所。')
        now = timezone.now()
        result = {'as_of': now, 'groups': [], 'cards': [], 'role': role}
        groups = result['groups']
        if role == 'SYSADMIN':
            # Technical permissions never turn into a business reporting scope.
            return result
        if role == 'PATIENT':
            from portal.policies import patient_access
            access = patient_access(actor)
            patient_id = access.patient_id
            offers = access.scope(WaitOffer.objects.all(),patient_field='request__patient_id',clinic_field='request__clinic_id').filter(request__state='OFFERED',
                    state='PENDING', expires_at__gt=now).select_related('slot__clinic', 'slot__dentist').order_by('expires_at', 'pk')
            groups.append(_group('offers', '候补邀约待你答复', offers,
                lambda offer: {'title': f'{offer.slot.clinic.name} · {offer.slot.dentist.name}',
                    'detail': '答复截止时间（北京时间）', 'when': offer.expires_at,
                    'url': reverse('wait_offer', args=[offer.pk]), 'action': '核对时段并答复'},
                reverse('waitlist'), '邀约尚未形成预约；请在截止前自行决定，确认页会重新核验。'))
            stale = access.scope(WaitRequest.objects.all()).filter(
                Q(state='WAITING', latest__lte=now) |
                Q(state='OFFERED', offers__state='PENDING', offers__expires_at__lte=now)).distinct()
            groups.append(_group('wait_review', '候补期限需重新核对', stale.order_by('created_at', 'pk'),
                lambda entry: {'title': '候补时间范围已到期' if entry.state == 'WAITING' else '候补邀约已到期',
                    'detail': '请联系前台，或核对后自行退出并重新登记偏好。',
                    'url': reverse('waitlist'), 'action': '查看候补记录'}, reverse('waitlist'),
                '本页不自动退出候补、回收邀约或创建新预约。'))
            bills = Invoice.objects.filter(visit__patient_id=patient_id).select_related('current_record_version').order_by('-first_issued_at', '-pk')
            if access.delegated:bills=bills.none()
            groups.append(_group('invoices', '本人的结算单', bills,
                lambda bill: {'title': bill.invoice_no, 'detail': f'当前版本开单金额 ¥{bill.current_record_version.total_amount}',
                    'when': bill.first_issued_at, 'url': reverse('portal_invoice', args=[bill.pk]), 'action': '查看结算单'},
                reverse('portal_appointments'), '开单金额不等于实收款；版本更正后仍可核对原版。'))
            result['has_items'] = any(group['total'] for group in groups)
            return result
        if role == 'FINANCE':
            groups.extend((_correction_group(actor, finance=True), _quarters(actor, now)))
        else:
            visits = visible_visits(actor).select_related('clinic', 'dentist')
            if role in ('FRONT_DESK', 'DENTIST'):
                visits = visits.select_related('patient')
            if role == 'FRONT_DESK':
                for key, title, note in (
                    ('outcome', '到期预约结果待核实', '超过预约结束时间仍为已预约；先核实实际情况，再明确登记。不能据此自动判定爽约。'),
                    ('arrival', '今日待办理到诊', '按预约开始时间排序；到诊须由前台核实，打开页面不会登记。')):
                    groups.append(_group(key, title, visit_queue(visits, key, now).order_by('scheduled_start', 'pk'),
                                         _visit_item, _url('visits', queue=key), note))
            elif role == 'DENTIST':
                groups.append(_group('care', '已到诊，等待本人接诊或关闭',
                    visit_queue(visits, 'care', now).order_by('attended_at', 'scheduled_start', 'pk'),
                    lambda row: _visit_item(row, clinical=True), _url('visits', queue='care'),
                    '按实际到诊时间排序，包含以前日期仍未关闭的就诊；请核对治疗与结算后分别确认。'))
                groups.append(_correction_group(actor, finance=False))
            elif role in ('MANAGER', 'HQ'):
                overdue = visit_queue(visits, 'outcome', now)
                result['cards'].append({'label': '到期结果待核实', 'count': overdue.count(),
                    'url': _url('visits', queue='outcome'), 'note': '前台核实结果后，运营分母才完整。'})
                result['cards'].append({'label': '已到诊但接诊未关闭', 'count': visit_queue(visits, 'care', now).count(),
                    'url': _url('visits', queue='care'), 'note': '交由负责牙医核对；本工作台仅展示运营信息。'})
                if role == 'HQ':
                    rows = overdue.values('clinic_id', 'clinic__name', 'clinic__clinic_code').annotate(n=Count('pk')).order_by('clinic__clinic_code')
                    month = now.astimezone(timezone.get_default_timezone()).date().replace(day=1)
                    today = now.astimezone(timezone.get_default_timezone()).date()
                    groups.append(_group('clinics', '诊所结果待核实范围', rows,
                        lambda row: {'title': f"{row['clinic__clinic_code']} · {row['clinic__name']}",
                            'detail': f"{row['n']} 条预约结果待核实；请协调该店前台。",
                            'url': _url('operations_dashboard', clinic_id=row['clinic_id'], start=month, end=today),
                            'action': '核对本月运营口径'}, reverse('operations_dashboard'),
                        '待核实清单包含历史遗留；运营报告另按所选期间计算，不能将两者当成同一分母。'))
                    groups.append(_quarters(actor, now))
            if role in ('FRONT_DESK', 'MANAGER'):
                tasks = CoordinationTask.objects.filter(slot__clinic_id=context.clinic_id).select_related('slot__dentist')
                if role == 'FRONT_DESK':
                    groups.append(_group('my_tasks', '本人正在协调的任务',
                        tasks.filter(state='IN_PROGRESS', assignee_id=actor.pk).order_by(F('due_at').asc(nulls_last=True), 'pk'),
                        _task_item, _url('coordination_task_list', mode='mine'),
                        '先跟进本人任务；声明、预约变更与提交复核分别办理。'))
                    groups.append(_group('unclaimed', '本店待受理协调任务', tasks.filter(state='OPEN').order_by('slot__starts_at', 'pk'),
                        _task_item, reverse('coordination_task_list'), '核对后明确受理；浏览任务不代表承担责任。'))
                    paused = AvailabilitySlot.objects.filter(clinic_id=context.clinic_id, is_active=True,
                        booking_paused=True, starts_at__gt=now).exclude(coordination_tasks__state__in=('OPEN', 'IN_PROGRESS', 'READY')).select_related('dentist').order_by('starts_at', 'pk')
                    groups.append(_group('paused', '暂停出诊尚待核对后续', paused,
                        lambda slot: {'title': f'出诊 #{slot.pk} · {slot.dentist.name}', 'detail': '当前没有进行中的协调任务',
                            'when': slot.starts_at, 'url': reverse('availability_detail', args=[slot.pk]), 'action': '核对维护或恢复'},
                        reverse('availability_list'), '暂停并不释放牙医时间；依实际业务选择协调、维护或恢复接收。'))
                else:
                    groups.append(_group('review', '可独立复核的协调任务',
                        tasks.filter(state='READY').exclude(submitted_by_id=actor.pk).order_by('submitted_at', 'pk'),
                        _task_item, reverse('coordination_task_list'), '与提交人不同账号复核；通过后由前台单独办理出诊维护。'))
                entries = WaitRequest.objects.filter(clinic_id=context.clinic_id)
                result['cards'].append({'label': '过期邀约待回收', 'count': WaitOffer.objects.filter(
                    request__in=entries, state='PENDING', expires_at__lte=now).count(),
                    'url': reverse('waitlist'), 'note': '到期已不占用时间；核对并回收后候补才能重新匹配。'})
                if role == 'FRONT_DESK':
                    result['cards'].append({'label': '有效候补等待安排', 'count': entries.filter(
                        state='WAITING', latest__gt=now, patient__is_active=True).count(),
                        'url': reverse('schedule_plans'), 'note': '先核对偏好和可用时段，再明确生成、发布建议。'})
        if role in ('FRONT_DESK','MANAGER','HQ'):
            from reception.models import ReceptionCase
            from scheduling.resource_models import ResourceCoordination
            reception=ReceptionCase.objects.exclude(state__in=['BOOKED','UNBOOKED','WITHDRAWN'])
            issues=ResourceCoordination.objects.filter(state__in=['OPEN','CONTACT'])
            if role!='HQ':
                reception=reception.filter(clinic_id=context.clinic_id)
                issues=issues.filter(Q(plan__visit__clinic_id=context.clinic_id)|Q(plan__offer__request__clinic_id=context.clinic_id))
            if role=='FRONT_DESK':
                groups.append(_group('reception_contacts','本人电话接待及联系期限',reception.filter(owner=actor).select_related('owner').order_by('due_at','pk'),
                    lambda row:{'title':f'接待 #{row.pk}','detail':row.get_state_display(),'when':row.due_at,
                        'url':reverse('reception_detail',args=[row.pk]),'action':'核对沟通并继续办理'},
                    _url('reception_list',queue='mine'),'候选不占位；待联系、待确认及候补等待保留负责人和期限。'))
            result['cards'].append({'label':'逾期接待联系','count':reception.filter(due_at__lt=now).count(),
                'url':_url('reception_list',queue='overdue') if role=='FRONT_DESK' else reverse('resource_summary'),
                'note':'核实负责人与下次期限；统计不包含联系人和沟通文字。'})
            result['cards'].append({'label':'资源故障待协调','count':issues.count(),
                'url':reverse('resource_summary') if role=='HQ' else reverse('resource_coordination_list'),
                'note':'原承诺保留；替换资源、改期和取消分别明确办理。'})
        if role in ('FRONT_DESK','MANAGER'):
            from registry.profile_models import ClinicProfilePolicy,DentistClinicAffiliation
            if ClinicProfilePolicy.objects.filter(clinic_id=context.clinic_id,roster_enforced=True).exists():
                from scheduling.resource_models import DepartmentHours
                days=[timezone.localdate()+timezone.timedelta(days=i) for i in range(1,15)]
                weekdays=set(DepartmentHours.objects.filter(department__clinic_id=context.clinic_id,department__is_active=True).values_list('weekday',flat=True))
                staff=list(DentistClinicAffiliation.objects.filter(clinic_id=context.clinic_id,state='ACTIVE',kind='RESIDENT',dentist__is_active=True))
                expected={(a.dentist_id,d) for a in staff for d in days if d.weekday() in weekdays and a.starts_on<=d and (a.ends_on is None or d<=a.ends_on)}
                covered=set()
                for slot in AvailabilitySlot.objects.filter(clinic_id=context.clinic_id,is_active=True,booking_paused=False,
                    ends_at__gt=now,starts_at__lt=now+timezone.timedelta(days=15)):
                    begin=timezone.localtime(slot.starts_at).date();finish=timezone.localtime(slot.ends_at-timezone.timedelta(microseconds=1)).date()
                    for d in days:
                        if begin<=d<=finish:covered.add((slot.dentist_id,d))
                result['cards'].append({'label':'未来十四天常驻医师排班缺口','count':len(expected-covered),
                    'url':reverse('schedule_calendar') if role=='FRONT_DESK' else reverse('profile_home'),
                    'note':'按开放日统计尚无出诊的人日，前台核对休假与接诊需求后补排，不自动发布。'})
                ended=DentistClinicAffiliation.objects.filter(clinic_id=context.clinic_id).filter(Q(state='ENDED')|Q(ends_on__lt=timezone.localdate()))
                affected=Visit.objects.filter(clinic_id=context.clinic_id,dentist_id__in=ended.values('dentist_id'),
                    status__in=['SCHEDULED','CHECKED_IN'],scheduled_end__gt=now)
                result['cards'].append({'label':'任职变化原约待协调','count':affected.count(),
                    'url':reverse('profile_coordination'),'note':'原约保留；前台核对患者意愿后办理改期或其他安排。'})
        if role=='FINANCE':
            from finance.management_models import MonthlyCost
            count=MonthlyCost.objects.filter(state='PENDING').exclude(prepared_by=actor).count()
            if count:result['cards'].append({'label':'月度成本待独立复核','count':count,
                'url':reverse('management_home'),'note':'先核对成本期间、来源与归属，成本确认不产生付款。'})
        result['has_items'] = any(group['total'] for group in groups) or any(card['count'] for card in result['cards'])
        return result
