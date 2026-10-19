"""Read-only appointment queues. Every filter starts with the active role scope."""
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django import forms
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from adc_core.rules import BUSINESS_TZ, STATUS_CHOICES
from scheduling.selectors import visible_visits

QUEUE_CHOICES = (
    ('all', '全部预约'), ('today', '今日全部安排'),
    ('arrival', '今日待到诊'), ('outcome', '到期结果待核实'),
    ('care', '已到诊，接诊未关闭'),
)


def visit_filter_navigation(data):
    """Links carry only validated display filters, never workspace authority."""
    query = {key: str(data[key]) for key in ('queue', 'day', 'status', 'q') if data.get(key)}
    queue = query.get('queue', 'all')
    search = {'q': query['q']} if query.get('q') else {}
    shortcuts = [dict(label=label, active=value == queue,
                      url='?' + urlencode(dict(queue=value, **search))) for value, label in QUEUE_CHOICES]
    labels = {'queue': '清单', 'day': '日期', 'status': '状态', 'q': '搜索'}
    choices = {'queue': dict(QUEUE_CHOICES), 'status': dict(STATUS_CHOICES)}
    chips = []
    for key, value in query.items():
        if key == 'queue' and value == 'all':
            continue
        remaining = {k: v for k, v in query.items() if k != key}
        chips.append(dict(label=labels[key], value=choices.get(key, {}).get(value, value),
                          url='?' + urlencode(remaining)))
    return shortcuts, chips


def day_bounds(day):
    start = datetime.combine(day, time.min, tzinfo=BUSINESS_TZ)
    return start, start + timedelta(days=1)


def visit_queue(visits, queue, now):
    if queue not in dict(QUEUE_CHOICES):
        raise ValueError('Unknown appointment queue.')
    start, end = day_bounds(now.astimezone(BUSINESS_TZ).date())
    if queue in ('today', 'arrival'):
        visits = visits.filter(scheduled_start__gte=start, scheduled_start__lt=end)
    if queue == 'arrival':
        visits = visits.filter(status='SCHEDULED', scheduled_end__gt=now)
    elif queue == 'outcome':
        # A late record is an unresolved fact, never an inferred no-show.
        visits = visits.filter(status='SCHEDULED', scheduled_end__lte=now)
    elif queue == 'care':
        visits = visits.filter(status='CHECKED_IN')
    return visits


class VisitFilterForm(forms.Form):
    queue = forms.ChoiceField(label='办理清单', choices=QUEUE_CHOICES, required=False)
    day = forms.DateField(label='预约开始日期（北京时间，可不填）', required=False,
                          widget=forms.DateInput(attrs={'type': 'date'}))
    status = forms.ChoiceField(label='业务状态', required=False,
                              choices=(('', '全部状态'),) + STATUS_CHOICES)
    q = forms.CharField(label='就诊编号', max_length=80, required=False)

    def __init__(self, *args, role, **kwargs):
        super().__init__(*args, **kwargs)
        if role in ('FRONT_DESK', 'DENTIST'):
            self.fields['q'].label = '就诊编号、患者编号或姓名'


def filtered_visits(actor, data, now=None):
    context = getattr(actor, '_adc_workspace', None)
    from workspaces.context import valid_context
    from workspaces.models import WorkspaceContext
    if (context is None or not valid_context(actor, context) or
            context.role not in ('FRONT_DESK', 'DENTIST', 'MANAGER', 'HQ') or
            (context.role in ('FRONT_DESK', 'MANAGER') and context.clinic_id is None) or
            not WorkspaceContext.objects.filter(pk=context.pk, user_id=actor.pk, role=context.role,
                clinic_id=context.clinic_id, revision=context.revision).exists()):
        raise PermissionDenied('请先选择有权限的工作身份和诊所。')
    visits = visit_queue(visible_visits(actor), data.get('queue') or 'all', now or timezone.now())
    if data.get('day'):
        start, end = day_bounds(data['day'])
        visits = visits.filter(scheduled_start__gte=start, scheduled_start__lt=end)
    if data.get('status'):
        visits = visits.filter(status=data['status'])
    if data.get('q'):
        query = Q(visit_no=data['q'])
        if context.role in ('FRONT_DESK', 'DENTIST'):
            query |= Q(patient__patient_no=data['q']) | Q(patient__name__icontains=data['q'])
        visits = visits.filter(query)
    if data.get('queue') == 'care':
        return visits.order_by('attended_at', 'scheduled_start', 'pk')
    if data.get('queue') in ('arrival', 'outcome', 'today'):
        return visits.order_by('scheduled_start', 'pk')
    return visits.order_by('-scheduled_start', '-pk')
