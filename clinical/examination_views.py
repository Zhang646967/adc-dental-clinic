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
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.policies import require_clinic
from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.rules import ATTENDED_STATUSES, RuleError
from clinical import examinations as cmd
from clinical import examination_followup as followup
from clinical.authority import professional_scope, require_reviewer, require_visit_authority
from clinical.encounter_views import clinical_render
from clinical.examination_models import ExaminationDuty, ExaminationEvent, ExaminationOrder, ExaminationProject
from clinical.form_binding import check_patient_form, patient_form_binding
from clinical.plan_forms import ConfirmPlanActionForm, current_steps, services_for
from clinical.plan_models import NextVisitInstruction
from clinical.plan_views import confirmation
from portal.examination_review import published_examination
from scheduling.models import Visit
from workspaces.context import require_active

Action = cmd.Action
ACTION_LABELS = {**dict(Action.choices), followup.FOLLOWUP: '调整报告复诊安排',
    followup.CONTACT_RESULT: '登记实际联系结果'}


class OrderForm(forms.Form):
    project = forms.ModelChoiceField(queryset=ExaminationProject.objects.none(), label='检查项目')
    purpose = forms.CharField(max_length=500, label='申请目的', widget=forms.Textarea(attrs={'rows': 3}))
    record = forms.IntegerField(widget=forms.HiddenInput)
    patient_binding = forms.CharField(widget=forms.HiddenInput)


class ActionForm(forms.Form):
    patient_binding = forms.CharField(widget=forms.HiddenInput)
    revision = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, action, *args, visit, actor, **kwargs):
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
        if action in (Action.PUBLISH, followup.FOLLOWUP):
            self.fields['followup_kind'] = forms.ChoiceField(label='报告发布后的安排', choices=followup.Kind.choices)
            self.fields['instruction'] = forms.ModelChoiceField(label='采用已有复诊指示', required=False,
                queryset=NextVisitInstruction.objects.filter(source_record__encounter__visit=visit, state='OPEN',
                    latest_on__gte=timezone.localdate()).exclude(completion_rule='UNSPECIFIED').select_related('service'))
            self.fields['instruction'].label_from_instance = lambda row: (
                f'{row.service.name} · {row.earliest_on} 至 {row.latest_on} · 指示 {row.pk}')
            self.fields['service'] = forms.ModelChoiceField(label='新指示的复诊服务', required=False,
                queryset=services_for(actor, visit))
            self.fields['step_version'] = forms.ModelChoiceField(label='新指示的治疗步骤（选填）', required=False,
                queryset=current_steps(visit, actor))
            self.fields['step_version'].label_from_instance = lambda row: f'方案 {row.version.plan_id} · V{row.version.revision} 第{row.sequence}步'
            for name, label in [('earliest_on', '建议最早日期'), ('latest_on', '建议最晚日期')]:
                self.fields[name] = forms.DateField(label=label, required=False,
                    widget=forms.DateInput(attrs={'type': 'date'}))
            self.fields['completion_rule'] = forms.ChoiceField(label='新指示的完成目标', required=False,
                choices=[('', '请选择'), ('EXAM_CONFIRMED', '复诊结束且确认检查记录'),
                    ('STEP_COMPLETED', '指定步骤实际完成并结束复诊')])
            self.fields['clinical_purpose'] = forms.CharField(label='新指示的临床目标', max_length=1000,
                required=False, widget=forms.Textarea(attrs={'rows': 2}))
            self.fields['booking_note'] = forms.CharField(label='前台安排说明（仅填必要信息）', max_length=500,
                required=False, widget=forms.Textarea(attrs={'rows': 2}))
        if action in (Action.PUBLISH, followup.FOLLOWUP, followup.CONTACT_RESULT):
            self.fields['contact_due_at'] = forms.DateTimeField(label='联系期限（北京时间）', required=False,
                widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
        if action == followup.CONTACT_RESULT:
            self.fields['contact_outcome'] = forms.ChoiceField(label='实际结果', choices=followup.CONTACT_OUTCOMES.items())
            self.fields['contact_note'] = forms.CharField(label='联系事实与下一步', max_length=500,
                widget=forms.Textarea(attrs={'rows': 3}))

    def fields_data(self):
        data = dict(self.cleaned_data)
        for field in ('instruction', 'step_version', 'service'):
            if data.get(field):
                data[field] = data[field].pk
        for field in ('performed_at', 'contact_due_at'):
            if data.get(field):
                data[field] = data[field].isoformat()
        return data


def _rows(orders):
    for order in orders:
        report = cmd.latest_report(order)
        yield dict(order=order, visit=order.source_record.encounter.visit,
            progress=cmd.progress(order, report, cmd.report_decision(report)),
            publication=cmd.publication_status(order))


def _followup_reports(visit, actor):
    if visit.status not in ('SCHEDULED', *ATTENDED_STATUSES):
        return
    links = followup.linked_instructions(visit).filter(instruction__state='OPEN')
    linked_orders = followup.linked_orders(visit)
    legacy_origins = links.filter(instruction__examinationfollowup__isnull=True).values(
        'instruction__source_record__encounter__visit_id')
    orders = cmd.orders().filter(Q(pk__in=linked_orders.values('pk')) |
        Q(**{cmd.RELATED + '_id__in': legacy_origins}), active_release__isnull=False)
    for order in orders:
        original = order.source_record.encounter.visit
        try:
            professional_scope(actor.pk, original.clinic_id, order.project.service_id, 'READ')
        except PermissionDenied:
            continue
        try:
            report = published_examination(original, order.pk)
        except Http404:
            continue  # The release was withdrawn before this read.
        disposition = followup.current_decision(order)
        if disposition and disposition.instruction_id and links.filter(instruction_id=disposition.instruction_id).exists():
            instruction = disposition.instruction
            try:
                professional_scope(actor.pk, visit.clinic_id, instruction.service_id, 'READ')
            except PermissionDenied:
                continue
            report['instruction'] = instruction
        elif linked_orders.filter(pk=order.pk).exists():
            report['needs_review'] = True
        yield report


def _preview(request, data, token, visit, *, order=None):
    report = order.reports.filter(pk=data['report']).first() if order and data.get('report') else None
    return clinical_render(request, 'clinical/examination_confirm.html', dict(
        data=data, visit=visit, order=order, report=report, action=data['action'], action_label=ACTION_LABELS[data['action']],
        disposition_label=followup.Kind(data['followup']['kind']).label if 'followup' in data else '',
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
        report_recheck=followup.linked_orders(visit).exists(),
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
    contact_only = request.GET.get('queue') == 'contact'
    if contact_only:
        visible = visible.filter(own).annotate(disposition=Subquery(
            followup.ExaminationFollowup.objects.filter(release_id=OuterRef('active_release_id'))
            .order_by('-pk').values('kind')[:1])).filter(disposition=followup.Kind.CONTACT)
    page = Paginator(visible, 25).get_page(request.GET.get('page'))
    rows = list(_rows(page))
    if contact_only:
        for row in rows:
            disposition = followup.current_decision(row['order'])
            if disposition and disposition.kind == followup.Kind.CONTACT:
                row['contact'] = followup.contact_progress(disposition)
    return clinical_render(request, 'clinical/examination_queue.html', dict(page=page, rows=rows, contact_only=contact_only))


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
    listed = list(page)
    dispositions = followup.ExaminationFollowup.objects.filter(
        release_id__in=[row['active_release_id'] for row in listed if row['active_release_id']]
    ).order_by('release_id', '-pk').distinct('release_id')
    contacts = {row.release_id: row for row in dispositions if row.kind == followup.Kind.CONTACT}
    rows = []
    for row in listed:
        if row['latest']:
            progress = cmd.DECISIONS.get(row['latest'], '待独立审核')
        else:
            progress = '待登记结果' if row['performed_at'] else '待执行检查'
        publication = '患者可查阅' if row['active_release_id'] else ('已撤回' if row['was_released'] else '未发布')
        disposition = contacts.get(row['active_release_id'])
        contact = followup.contact_progress(disposition) if disposition else None
        if contact:
            contact = {field: contact[field] for field in ('state', 'due_at', 'overdue')}
        rows.append(dict(row, progress=progress, publication=publication, project=row['project_name'], contact=contact))
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
    forms_by_action = {action: ActionForm(action, initial=initial, auto_id=f'id_{action.lower()}_%s',
                       actor=request.user, visit=visit)
                       for action in actions}
    status = 200
    if request.method == 'POST':
        action = request.POST.get('action')
        check_patient_form(request.user, visit, request.POST.get('patient_binding', ''))
        form = ActionForm(action, request.POST, auto_id=f'id_{action.lower()}_%s' if action in ACTION_LABELS else False,
            actor=request.user, visit=visit)
        status = 400
        if form.is_valid():
            try:
                if form.cleaned_data['revision'] != order.revision or action not in actions:
                    raise RuleError('检查进度或办理权限已变化，请刷新后重新核对。')
                data, token = cmd.prepare_action(request.user, order, action, form.fields_data())
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
                status = 409
            else:
                return _preview(request, data, token, visit, order=order)
        forms_by_action[action] = form
    release = order.active_release
    own_visit = visit.dentist_id == request.user.dentist_id
    disposition = followup.current_decision(order) if own_visit else None
    return clinical_render(request, 'clinical/examination_detail.html', dict(
        order=order, visit=visit, report=report, decision=decision, release=release,
        progress=cmd.progress(order, report, decision), publication=cmd.publication_status(order),
        reports=order.reports.order_by('-number'), events=order.events.select_related('actor', 'report').order_by('pk'),
        action_forms=[dict(action=action, label=ACTION_LABELS[action], form=form) for action, form in forms_by_action.items()
                      if action in ACTION_LABELS],
        own_visit=own_visit, disposition=disposition,
        contact=followup.contact_progress(disposition) if disposition and disposition.kind == followup.Kind.CONTACT else None,
        contact_events=followup.contact_events(disposition).select_related('actor') if disposition and disposition.kind == followup.Kind.CONTACT else (),
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
