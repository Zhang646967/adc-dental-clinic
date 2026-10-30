import uuid
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.proposals import read_proposal
from clinical import documents as cmd
from clinical.document_forms import DocumentForm, DocumentFollowupForm, DocumentConfirmForm
from clinical.encounter_forms import ClinicalReasonForm
from clinical.document_selectors import document_details, document_worklist, compare_versions
from clinical.encounter_views import clinical_render
from clinical.form_binding import patient_form_binding, check_patient_form


@login_required
@never_cache
@require_GET
def worklist(request):
    rows = document_worklist(request.user)
    queue = request.GET.get('queue', 'pending')
    if queue == 'overdue':
        rows = rows.filter(deadline__lt=timezone.now()).filter(Q(has_confirmed=False) | Q(has_draft=True) | Q(needs_source_review=True))
    elif queue == 'confirmed':
        rows = rows.filter(has_confirmed=True, has_draft=False, needs_source_review=False)
    elif queue != 'all':
        queue = 'pending'; rows = rows.filter(Q(has_confirmed=False) | Q(has_draft=True) | Q(needs_source_review=True))
    return clinical_render(request, 'clinical/document_worklist.html', dict(
        page=Paginator(rows, 25).get_page(request.GET.get('page')), queue=queue, now=timezone.now()))


def entry_forms(request, details, action, data=None):
    head = details['document']
    initial = dict(expected_revision=head.revision if head else 0, operation_id=uuid.uuid4(),
                   patient_binding=patient_form_binding(request.user, details['visit']))
    def bound(name):
        return (data if data is not None else request.POST) if request.method == 'POST' and action == name else None
    return dict(
        document_form=DocumentForm(bound('SAVE'), initial=dict(details['payload'], **initial),
                                   prior_versions=details['prior_versions'], auto_id='document_%s'),
        amend_form=ClinicalReasonForm(bound('AMEND'), initial=initial, auto_id='document_amend_%s'),
        discard_form=ClinicalReasonForm(bound('DISCARD'), initial=initial, auto_id='document_discard_%s'),
        followup_form=DocumentFollowupForm(bound('FOLLOWUP'), initial=initial, auto_id='document_followup_%s'))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def workspace(request, pk):
    details = document_details(request.user, pk, revision=request.GET.get('revision'))
    action = request.POST.get('action') if request.method == 'POST' else None
    resumed = request.method == 'POST' and request.POST.get('review_current') == 'yes'
    data = None
    if request.method == 'POST':
        if details['historical'] or not details['can_edit']:
            raise PermissionDenied('本页仅供查阅，请返回本人当前可办理文书。')
        check_patient_form(request.user, details['visit'], request.POST.get('patient_binding', ''))
    if resumed:
        if action != 'SAVE':
            raise PermissionDenied('请从文书草稿核对本页填写。')
        data = request.POST.copy()
        data.update(expected_revision=details['document'].revision if details['document'] else 0, operation_id=str(uuid.uuid4()))
        messages.info(request, '已载入当前版本号，本页填写尚未保存；请比较后明确保存。')
    forms = entry_forms(request, details, action, data); status = 200; rebase = False
    keys = {'SAVE': 'document_form', 'AMEND': 'amend_form', 'DISCARD': 'discard_form', 'FOLLOWUP': 'followup_form'}
    if request.method == 'POST' and not resumed:
        if action not in keys:
            raise PermissionDenied('未知文书办理操作。')
        form = forms[keys[action]]
        if form.is_valid():
            fields = form.fields_data() if action == 'SAVE' else {
                k: v for k, v in form.cleaned_data.items() if k in ('reason', 'note', 'due_at')}
            try:
                head, replay = cmd.save_document(actor=request.user, visit_id=pk,
                    expected_revision=form.cleaned_data['expected_revision'], operation_id=form.cleaned_data['operation_id'],
                    fields=fields, action=action)
            except EXPECTED_ERRORS as exc:
                add_error(form, exc); status = 409
                details = document_details(request.user, pk)
                rebase = action == 'SAVE' and details['can_edit']
            else:
                messages.success(request, '该次办理已保留，未重复提交。' if replay else {
                    'SAVE': '文书草稿已保存，尚未确认。', 'AMEND': '已建立更正草稿，原确认文书继续保留。',
                    'DISCARD': '已明确放弃未确认草稿。', 'FOLLOWUP': '待办进展已记录，原办理期限和超期事实保留。'}[action])
                return redirect('clinical_document', pk=pk)
        else:
            status = 400
    return clinical_render(request, 'clinical/document_workspace.html', dict(details, **forms,
        rebase_available=rebase, show_saved_comparison=rebase or resumed), status=status)


@login_required
@never_cache
@require_GET
def preview(request, pk):
    details = document_details(request.user, pk)
    try:
        prepared = cmd.prepare_document(actor=request.user, visit_id=pk)
    except EXPECTED_ERRORS as exc:
        form = DocumentConfirmForm(); add_error(form, exc)
        return clinical_render(request, 'clinical/document_confirm.html', dict(details, form=form, blocked=True), status=409)
    return clinical_render(request, 'clinical/document_confirm.html', dict(details,
        form=DocumentConfirmForm(initial={'proposal_token': prepared['proposal_token']}),
        preview_payload=prepared['payload'], preview_source=prepared['source'], blocked=False))


@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request):
    form = DocumentConfirmForm(request.POST); details = {}
    if form.is_valid():
        try:
            p = read_proposal(request.user, cmd.CONTRACT, ('DENTIST',), form.cleaned_data['proposal_token'])
            details = document_details(request.user, p['data']['visit'])
            version, replay = cmd.confirm_document(actor=request.user, **form.cleaned_data)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            messages.success(request, '该次确认已完成，未重复生成文书。' if replay else '完整文书已由医师确认；原临床、结算事实和历史版本保留。')
            return redirect('clinical_document', pk=version.document.encounter.visit_id)
    return clinical_render(request, 'clinical/document_confirm.html', dict(details, form=form, blocked=True), status=409)


@login_required
@never_cache
@require_GET
def compare(request, pk):
    details = document_details(request.user, pk)
    compared = compare_versions(details['document'], request.GET.get('left'), request.GET.get('right'))
    return clinical_render(request, 'clinical/document_compare.html', dict(details, **compared))


@login_required
@never_cache
@require_GET
def printable(request, pk):
    details = document_details(request.user, pk, revision=request.GET.get('revision'))
    if details['document_version'] is None:
        from django.http import Http404
        raise Http404('尚无可打印的确认文书。')
    return clinical_render(request, 'clinical/document_print.html', details)
