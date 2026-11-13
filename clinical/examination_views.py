"""Exam workspaces reuse clinical actor, visit and signed confirmation contracts."""
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Exists, F, OuterRef, Q, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.policies import require_clinic
from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.rules import ATTENDED_STATUSES, RuleError
from clinical import examinations as cmd
from clinical.authority import professional_scope, require_reviewer, require_visit_authority
from clinical.encounter_views import clinical_render
from clinical.examination_models import ExaminationDuty, ExaminationEvent, ExaminationOrder, ExaminationProject
from clinical.form_binding import check_patient_form, patient_form_binding
from clinical.plan_forms import ConfirmPlanActionForm
from clinical.plan_models import PlanAppointment
from clinical.plan_views import confirmation
from portal.examination_review import published_examination
from scheduling.models import Visit
from workspaces.context import require_active

Action = cmd.Action


class OrderForm(forms.Form):
    project = forms.ModelChoiceField(queryset=ExaminationProject.objects.none(), label='检查项目')
    purpose = forms.CharField(max_length=500, label='申请目的', widget=forms.Textarea(attrs={'rows': 3}))
    record = forms.IntegerField(widget=forms.HiddenInput)
    patient_binding = forms.CharField(widget=forms.HiddenInput)


class ActionForm(forms.Form):
    patient_binding = forms.CharField(widget=forms.HiddenInput)
    revision = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, action, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if action == Action.EXECUTE:
            self.fields['performed_at'] = forms.DateTimeField(
                label='实际检查时间（北京时间）', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
            self.fields['source_reference'] = forms.CharField(max_length=120, label='检查依据编号')
        if action == Action.SUBMIT:
            self.fields['body'] = forms.CharField(max_length=2000, label='检查结果（发布后患者可读）',
                widget=forms.Textarea(attrs={'rows': 6}))
        if action in (Action.SUBMIT, Action.APPROVE, Action.RETURN, Action.WITHDRAW):
            self.fields['reason'] = forms.CharField(max_length=500, required=action in (Action.RETURN, Action.WITHDRAW),
                label={Action.SUBMIT: '更正依据（首版留空）', Action.WITHDRAW: '撤回原因'}.get(action, '审核说明'),
                widget=forms.Textarea(attrs={'rows': 3}))


def _rows(orders):
    for order in orders:
        report = cmd.latest_report(order)
        yield dict(order=order, visit=order.source_record.encounter.visit,
            progress=cmd.progress(order, report, cmd.report_decision(report)),
            publication=cmd.publication_status(order))


def _followup_reports(visit, actor):
    if visit.status not in ('SCHEDULED', *ATTENDED_STATUSES):
        return
    followup_ids = [visit.pk]
    predecessor = visit.replaces_visit
    while (predecessor and predecessor.pk not in followup_ids and predecessor.status == 'RESCHEDULED'
           and predecessor.patient_id == visit.patient_id and predecessor.clinic_id == visit.clinic_id):
        followup_ids.append(predecessor.pk)
        predecessor = predecessor.replaces_visit
    original_ids = PlanAppointment.objects.filter(
        visit_id__in=followup_ids,
        instruction__state='OPEN', instruction__source_record__encounter__visit__patient_id=visit.patient_id,
        instruction__source_record__encounter__visit__clinic_id=visit.clinic_id,
    ).values('instruction__source_record__encounter__visit_id')
    for order in cmd.orders().filter(**{cmd.RELATED + '_id__in': original_ids}, active_release__isnull=False):
        original = order.source_record.encounter.visit
        try:
            professional_scope(actor.pk, original.clinic_id, order.project.service_id, 'READ')
        except PermissionDenied:
            continue
        try:
            yield published_examination(original, order.pk)
        except Http404:
            continue  # The release was withdrawn before this read.


def _preview(request, data, token, visit, *, order=None):
    report = order.reports.filter(pk=data['report']).first() if order and data['report'] else None
    return clinical_render(request, 'clinical/examination_confirm.html', dict(
        data=data, visit=visit, order=order, report=report, action=Action(data['action']),
        performed_at=parse_datetime(data['performed_at']) if 'performed_at' in data else None,
        form=ConfirmPlanActionForm(initial={'proposal_token': token}),
        back=reverse('clinical_examination', args=[order.pk]) if order else
        reverse('clinical_examination_visit', args=[visit.pk]),
    ))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def visit_workspace(request, pk):
    cmd.require_course()
    visit = get_object_or_404(Visit.objects.select_related('clinic', 'patient'), pk=pk)
    require_visit_authority(request.user, visit, 'READ', always=True)
    record = cmd.visit_record(visit)
    projects = cmd.eligible_projects(visit)
    form = None
    status = 200
    if record and projects.exists() and not settings.ADC_READ_ONLY:
        form = OrderForm(request.POST or None,
            initial=dict(record=record.pk, patient_binding=patient_form_binding(request.user, visit)))
        form.fields['project'].queryset = projects
    if request.method == 'POST':
        status = 400
        if not form:
            raise PermissionDenied('请在本次已到诊且已确认检查记录的就诊中申请。')
        check_patient_form(request.user, visit, request.POST.get('patient_binding', ''))
        if form.is_valid():
            try:
                if form.cleaned_data['record'] != record.pk:
                    raise RuleError('检查记录已有新版本，请重新核对。')
                data, token = cmd.prepare_order(request.user, visit,
                    form.cleaned_data['project'].pk, form.cleaned_data['purpose'])
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
                status = 409
            else:
                return _preview(request, data, token, visit)
    rows = list(_rows(cmd.orders().filter(**{cmd.RELATED + '_id': visit.pk}).order_by('-pk')))
    return clinical_render(request, 'clinical/examination_visit.html', dict(
        visit=visit, rows=rows, record=record, form=form, related_reports=list(_followup_reports(visit, request.user)),
    ), status=status)


@login_required
@never_cache
@require_GET
def queue(request):
    cmd.require_course()
    require_active(request.user, cmd.ROLES)
    own = Q(**{cmd.RELATED + '__dentist_id': request.user.dentist_id})
    assigned = ExaminationDuty.objects.filter(user=request.user, is_active=True).values('project_id')
    candidates = cmd.orders().filter(
        Q(project_id__in=assigned) | own, project__service__department__clinic_id=F(cmd.RELATED + '__clinic_id'),
    )
    # Each project has one service scope. Check it once for the actor's own
    # visits and once for delegated execution or review.
    access = {}
    for order in candidates.order_by('project_id').distinct('project_id'):
        visit = order.source_record.encounter.visit
        try:
            professional_scope(request.user.pk, visit.clinic_id, order.project.service_id, 'READ')
        except PermissionDenied:
            continue
        access[order.project_id] = False
        if cmd.duties(request.user, order.project, cmd.Kind.EXECUTE).exists():
            access[order.project_id] = True
        elif cmd.duties(request.user, order.project, cmd.Kind.REVIEW).exists():
            try:
                require_reviewer(request.user, visit.clinic_id)
            except PermissionDenied:
                continue
            access[order.project_id] = True
    duties = [pk for pk, active in access.items() if active]
    visible = candidates.filter(Q(project_id__in=duties) | (own & Q(project_id__in=access))).order_by('-pk')
    page = Paginator(visible, 25).get_page(request.GET.get('page'))
    return clinical_render(request, 'clinical/examination_queue.html', dict(page=page, rows=list(_rows(page))))


@login_required
@never_cache
@require_GET
def frontdesk(request):
    cmd.require_course()
    clinic_id = request.workspace.clinic_id
    require_active(request.user, ('FRONT_DESK',), clinic_id)
    require_clinic(request.user, clinic_id)
    events = ExaminationEvent.objects.filter(order_id=OuterRef('pk'))
    latest = events.filter(action__in=(Action.SUBMIT, *cmd.REVIEW)).order_by('-pk').values('action')[:1]
    data = ExaminationOrder.objects.filter(**{cmd.RELATED + '__clinic_id': clinic_id}).annotate(
        latest=Subquery(latest), was_released=Exists(events.filter(action=Action.PUBLISH)),
        visit_no=F(cmd.RELATED + '__visit_no'),
    ).values('number', 'project_name', 'visit_no', 'requested_at', 'performed_at', 'latest',
        'active_release_id', 'was_released').order_by('-pk')
    page = Paginator(data, 25).get_page(request.GET.get('page'))
    rows = []
    for row in page:
        if row['latest']:
            progress = cmd.DECISIONS.get(row['latest'], '待独立审核')
        else:
            progress = '待登记结果' if row['performed_at'] else '待执行检查'
        publication = '患者可查阅' if row['active_release_id'] else ('已撤回' if row['was_released'] else '未发布')
        rows.append(dict(row, progress=progress, publication=publication, project=row['project_name']))
    return clinical_render(request, 'clinical/examination_queue.html', dict(page=page, rows=rows, frontdesk=True))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def detail(request, pk):
    order = get_object_or_404(cmd.orders().select_related('active_release__report'), pk=pk)
    cmd.read_order(request.user, order)
    visit = order.source_record.encounter.visit
    report = cmd.latest_report(order)
    decision = cmd.report_decision(report)
    actions = [] if settings.ADC_READ_ONLY else cmd.available_actions(request.user, order, report, decision)
    initial = dict(patient_binding=patient_form_binding(request.user, visit), revision=order.revision)
    forms_by_action = {action: ActionForm(action, initial=initial, auto_id=f'id_{action.lower()}_%s')
                       for action in actions}
    status = 200
    if request.method == 'POST':
        action = request.POST.get('action')
        check_patient_form(request.user, visit, request.POST.get('patient_binding', ''))
        form = ActionForm(action, request.POST, auto_id=f'id_{action.lower()}_%s' if action in Action.values else False)
        status = 400
        if form.is_valid():
            try:
                if form.cleaned_data['revision'] != order.revision or action not in actions:
                    raise RuleError('检查进度或办理权限已变化，请刷新后重新核对。')
                fields = dict(form.cleaned_data)
                if action == Action.EXECUTE:
                    fields['performed_at'] = fields['performed_at'].isoformat()
                data, token = cmd.prepare_action(request.user, order, action, fields)
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
                status = 409
            else:
                return _preview(request, data, token, visit, order=order)
        forms_by_action[action] = form
    release = order.active_release
    return clinical_render(request, 'clinical/examination_detail.html', dict(
        order=order, visit=visit, report=report, decision=decision, release=release,
        progress=cmd.progress(order, report, decision), publication=cmd.publication_status(order),
        reports=order.reports.order_by('-number'), events=order.events.select_related('actor', 'report').order_by('pk'),
        action_forms=[dict(action=Action(action), form=form) for action, form in forms_by_action.items()
                      if action in Action.values],
        own_visit=visit.dentist_id == request.user.dentist_id,
    ), status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request, pk, order_id=None):
    cmd.require_course()
    visit = get_object_or_404(Visit, pk=pk)
    expected = dict(visit=pk, patient=visit.patient_id)
    if order_id is None:
        expected['action'] = Action.ORDER
        back = reverse('clinical_examination_visit', args=[pk])
    else:
        expected['order'] = order_id
        back = reverse('clinical_examination', args=[order_id])
    result, response = confirmation(request, contract=cmd.CONTRACT, roles=cmd.ROLES, expected=expected,
        handler=cmd.confirm, title='核对检查办理', back=back)
    return response if response is not None else redirect('clinical_examination', pk=result.pk)
