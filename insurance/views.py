from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db import DatabaseError
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods
from adc_core.http_support import EXPECTED_ERRORS, add_error
from equipment.forms import ExplicitProposalForm
from insurance import services, selectors
from insurance.forms import CatalogueImportForm, CatalogueResubmitForm, ArrangementForm, MappingForm, EligibilityForm, ReviewForm, DisableForm
from insurance.models import EligibilityFact
from insurance.policies import scope
from patients.selectors import visible_patients


def _flow(request, *, title, form, prepare, confirm, summary):
    if request.method == 'POST' and request.POST.get('action') == 'confirm':
        bound = ExplicitProposalForm(request.POST)
        if bound.is_valid():
            try:
                row, repeated = confirm(actor=request.user, **bound.cleaned_data)
            except EXPECTED_ERRORS as exc:
                add_error(bound, exc)
            except DatabaseError:
                return render(request, 'business/problem.html', {'problem': '暂不能确认保存结果，请先回到医保资料核对原记录；不要据此收退款或重复建档。'}, status=503)
            else:
                messages.success(request, '此前已保存，显示当前记录。' if repeated else '医保资料已保存；未生成治疗、账单或资金。')
                if isinstance(row, EligibilityFact):
                    return redirect('insurance_eligibility', pk=row.patient_id)
                kind = next(k for k, model in services.MODELS.items() if isinstance(row, model))
                return redirect('insurance_catalogue', pk=row.pk) if kind == 'catalogue' else redirect('insurance_detail', kind=kind, pk=row.pk)
        return render(request, 'business/proposal.html', dict(title=title, form=bound, button='明确确认并保存', recovery_route='insurance_home'), status=409)
    if request.method == 'POST' and request.POST.get('action') != 'preview':
        raise PermissionDenied('请先预览并核对资料。')
    if request.method == 'POST' and form.is_valid():
        try:
            p = prepare(actor=request.user, **form.cleaned_data)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            return render(request, 'business/proposal.html', dict(title=title, summary=summary(p),
                form=ExplicitProposalForm(initial={'proposal_token': p['proposal_token']}), button='明确确认并保存', recovery_route='insurance_home'))
    return render(request, 'insurance/form.html', dict(title=title, form=form))


def _bound(request):
    return request.POST if request.method == 'POST' and request.POST.get('action') == 'preview' else None


def _subject(actor, kind, pk):
    if kind not in ('catalogue', 'arrangement', 'mapping'):
        raise Http404
    try:
        return services.reviewed_subject(actor, kind, pk)
    except ObjectDoesNotExist:
        raise Http404 from None


@login_required
@never_cache
@require_GET
def home(request):
    return render(request, 'insurance/home.html', selectors.dashboard(request.user,
        arrangements_page=request.GET.get('arrangements_page', '1'), mappings_page=request.GET.get('mappings_page', '1')))


@login_required
@never_cache
@require_GET
def catalogue(request, pk):
    get_object_or_404(selectors.catalogues(request.user), pk=pk)
    try:
        data = selectors.catalogue_detail(request.user, pk, page=request.GET.get('page', '1'), query=request.GET.get('q', ''), issue=request.GET.get('issue', ''))
    except services.RuleError as exc:
        return render(request, 'business/problem.html', {'problem': str(exc)}, status=400)
    return render(request, 'insurance/catalogue.html', data)


@login_required
@never_cache
@require_GET
def source_download(request, pk):
    row = get_object_or_404(selectors.catalogues(request.user), pk=pk)
    response = HttpResponse(bytes(row.original_bytes), content_type='application/msword')
    response['Content-Disposition'] = 'attachment; filename="hunan-oral-policy-2026.doc"'
    return response


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def import_catalogue(request):
    scope(request.user, ('FINANCE',))
    return _flow(request, title='导入湖南口腔医保目录（待独立核对）', form=CatalogueImportForm(_bound(request)),
        prepare=services.prepare_catalogue, confirm=lambda **kw: services.confirm_preparation(expected_kind='catalogue', **kw),
        summary=lambda p: [('政策通知', p['source']['notice']), ('生效日期', p['source']['effective_on']),
            ('规范编码', p['source']['unique_codes']), ('原表行数／相同重复行', f"{p['source']['physical_rows']}／{p['source']['identical_extra_rows']}"),
            ('源文件 SHA-256', p['data']['source_digest']), ('保留缺失', '一条支付规则未知、两条单位为空，不自动补值'),
            ('保存后', '另一财务账号复核后才启用；甲类先自付为零不等于100%报销')])


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def resubmit_catalogue(request, pk):
    scope(request.user, ('FINANCE',))
    row = get_object_or_404(selectors.catalogues(request.user), pk=pk)
    return _flow(request, title='重新提交同一政策来源核对', form=CatalogueResubmitForm(_bound(request)),
        prepare=lambda **kw: services.prepare_catalogue(previous_id=pk, **kw),
        confirm=lambda **kw: services.confirm_preparation(expected_kind='catalogue', expected_previous_id=pk, **kw),
        summary=lambda p: [('原政策通知', row.notice), ('前次审阅记录', row.pk), ('本次核对序号', p['data']['review_attempt']),
            ('同一原文摘要', p['data']['source_digest']), ('重新提交依据', p['data']['reason']),
            ('保存后', '保留原决定，等待另一财务账号独立复核；原门店安排和映射不自动恢复')])


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def arrangement_new(request):
    scope(request.user, ('MANAGER',))
    return _flow(request, title='准备本店课程医保安排', form=ArrangementForm(_bound(request)),
        prepare=services.prepare_arrangement, confirm=lambda **kw: services.confirm_preparation(expected_kind='arrangement', **kw),
        summary=lambda p: [('目录', p['catalogue']), ('有效日期', f"{p['data']['starts_on']} 至 {p['data']['ends_on']}"),
            ('合成依据', p['data']['reference']), ('安排性质', '课程模拟，待另一财务账号核对，不证明真实定点资质')])


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def mapping_new(request):
    scope(request.user, ('MANAGER',))
    return _flow(request, title='核对本店收费项目与医保目录的适配', form=MappingForm(_bound(request)),
        prepare=services.prepare_mapping, confirm=lambda **kw: services.confirm_preparation(expected_kind='mapping', **kw),
        summary=lambda p: [('原收费项目', f"{p['fee'].code} · {p['fee'].name}"), ('原收费单位', p['fee'].unit_definition),
            ('目录项目', p['item']), ('目录单位', p['item'].unit), ('每原收费单位对应目录数量', p['data']['policy_units_per_fee']),
            ('适配依据', p['data']['compatibility_basis']), ('保存后', '待财务独立核对；源表缺项继续待核对，不改变实际收费')])


@login_required
@never_cache
@require_GET
def detail(request, kind, pk):
    row = _subject(request.user, kind, pk)
    if kind == 'catalogue':
        return redirect('insurance_catalogue', pk=row.pk)
    return render(request, 'insurance/detail.html', dict(row=row, kind=kind,
        blocker=selectors.mapping_blocker(row) if kind == 'mapping' else '', events=row.events.select_related('actor').order_by('-pk')))


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def review(request, kind, pk):
    scope(request.user, ('FINANCE',))
    _subject(request.user, kind, pk)
    return _flow(request, title='独立复核医保资料', form=ReviewForm(_bound(request)),
        prepare=lambda **kw: services.prepare_review(kind=kind, pk=pk, **kw),
        confirm=lambda **kw: services.confirm_review(expected_kind=kind, expected_pk=pk, **kw),
        summary=lambda p: [('资料编号', p['row'].pk), ('结果', '核对通过并启用' if p['data']['decision'] == 'approve' else '未通过'),
            ('依据', p['data']['reason']), ('资金影响', '无；此为课程合成资料核对')])


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def disable(request, kind, pk):
    _subject(request.user, kind, pk)
    return _flow(request, title='停用医保资料并保留历史', form=DisableForm(_bound(request)),
        prepare=lambda **kw: services.prepare_disable(kind=kind, pk=pk, **kw),
        confirm=lambda **kw: services.confirm_disable(expected_kind=kind, expected_pk=pk, **kw),
        summary=lambda p: [('资料编号', p['row'].pk), ('停用依据', p['data']['reason']),
            ('停用后', '阻止新用途，原版本和已发生业务保留；不自动退费或改变原账单')])


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def eligibility(request, pk):
    b = scope(request.user, ('FRONT_DESK',))
    patient = get_object_or_404(visible_patients(request.user), pk=pk, is_active=True)
    if request.method == 'GET':
        row, blocker = selectors.eligibility_at(b['clinic'], patient.pk, timezone.localdate())
        return render(request, 'insurance/eligibility.html', dict(patient=patient, current=row, blocker=blocker,
            history=EligibilityFact.objects.filter(clinic_id=b['clinic'], patient=patient).order_by('-version'), form=EligibilityForm()))
    return _flow(request, title='登记患者模拟待遇核对结果', form=EligibilityForm(_bound(request)),
        prepare=lambda **kw: services.prepare_eligibility(patient_id=pk, **kw),
        confirm=lambda **kw: services.confirm_preparation(expected_kind='eligibility', expected_patient_id=pk, **kw),
        summary=lambda p: [('患者业务编号', patient.patient_no), ('参保地', dict(services.REGIONS)[p['data']['insured_region']]),
            ('结果', dict(services.ELIGIBILITY_STATES)[p['data']['state']]), ('版本', p['data']['version']),
            ('有效日期', f"{p['data']['starts_on']} 至 {p['data']['ends_on']}"), ('合成依据', p['data']['reference']),
            ('影响', '追加核对记录，不扩大患者权限，不产生资金或治疗')])
