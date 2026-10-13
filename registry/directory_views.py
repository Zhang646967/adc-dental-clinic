from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from adc_core.http_support import EXPECTED_ERRORS, add_error
from registry.directory_rules import FIELDS, KINDS, LABELS, DisplayRow
from registry.directory_forms import RegistrationForm, AssociationForm, DirectoryConfirmForm
from registry.directory_services import (MODEL_MAP, CODE_FIELDS, require_directory_actor,
    prepare_registration, prepare_association, confirm_directory_change)
from registry.models import Clinic, Dentist, Qualification


def _kind(kind):
    if kind not in MODEL_MAP:
        raise Http404
    return kind


def _preview(request, preview):
    return render(request, 'registry/directory_confirm.html', {'preview':preview,
        'form':DirectoryConfirmForm(initial={'proposal_token':preview.proposal_token})})

@login_required
@never_cache
@require_GET
def home(request):
    require_directory_actor(request.user)
    counts = [{'kind':kind,'label':label,'count':MODEL_MAP[kind].objects.count()} for kind,label in KINDS.items()]
    require_directory_actor(request.user)
    return render(request,'registry/directory_home.html',{'counts':counts,'read_only':settings.ADC_READ_ONLY})

@login_required
@never_cache
@require_GET
def listing(request, kind):
    require_directory_actor(request.user); _kind(kind)
    q = request.GET.get('q','').strip()[:120]
    qs = MODEL_MAP[kind].objects.order_by(CODE_FIELDS[kind])
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(**{CODE_FIELDS[kind]+'__icontains':q}))
    page = Paginator(qs,25).get_page(request.GET.get('page'))
    rows = [{'pk':obj.pk,'code':getattr(obj,CODE_FIELDS[kind]),'name':obj.name,'active':obj.is_active} for obj in page]
    require_directory_actor(request.user)
    return render(request,'registry/directory_list.html',{'kind':kind,'label':KINDS[kind],
        'rows':rows,'page':page,'q':q,'read_only':settings.ADC_READ_ONLY})

@login_required
@never_cache
@require_GET
def detail(request, kind, pk):
    require_directory_actor(request.user); _kind(kind)
    obj = get_object_or_404(MODEL_MAP[kind],pk=pk)
    rows = tuple(DisplayRow(LABELS[k],str(getattr(obj,k))) for k in FIELDS[kind])
    associations = list(obj.qualifications.select_related('qualification').order_by('qualification__code')) if kind == 'dentist' else []
    require_directory_actor(request.user)
    return render(request,'registry/directory_detail.html',{'object':obj,'kind':kind,'label':KINDS[kind],
        'rows':rows,'associations':associations,'read_only':settings.ADC_READ_ONLY})

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def create(request, kind):
    require_directory_actor(request.user); _kind(kind)
    form = RegistrationForm(request.POST if request.method == 'POST' else None, kind=kind)
    if request.method == 'POST' and form.is_valid():
        try:
            preview = prepare_registration(actor=request.user, kind=kind,
                details={k:form.cleaned_data[k] for k in FIELDS[kind]}, reason_code=form.cleaned_data['reason_code'])
        except EXPECTED_ERRORS as exc:
            add_error(form,exc)
        else:
            return _preview(request,preview)
    return render(request,'registry/directory_form.html',{'form':form,'kind':kind,'title':'登记'+KINDS[kind],
        'read_only':settings.ADC_READ_ONLY})

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def attach(request, pk):
    require_directory_actor(request.user)
    dentist = get_object_or_404(Dentist,pk=pk,is_active=True)
    form = AssociationForm(request.POST if request.method == 'POST' else None,dentist=dentist)
    if request.method == 'POST' and form.is_valid():
        try:
            preview = prepare_association(actor=request.user,dentist_id=dentist.pk,
                qualification_id=form.cleaned_data['qualification'].pk,action='attach',reason_code=form.cleaned_data['reason_code'])
        except EXPECTED_ERRORS as exc:
            add_error(form,exc)
        else:
            return _preview(request,preview)
    return render(request,'registry/directory_form.html',{'form':form,'kind':'dentist','dentist':dentist,
        'title':'登记或恢复牙医资格关联','read_only':settings.ADC_READ_ONLY})

@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def withdraw_preview(request, pk, qpk):
    require_directory_actor(request.user)
    try:
        preview = prepare_association(actor=request.user,dentist_id=pk,qualification_id=qpk,
                                      action='withdraw',reason_code='CORRECT_LINK')
    except EXPECTED_ERRORS as exc:
        form = DirectoryConfirmForm(); add_error(form,exc)
        return render(request,'registry/directory_recovery.html',{'errors':form.errors,
            'problem':'当前关联不能生成撤回预览，请返回目录重新核对。'},status=409)
    return _preview(request,preview)

@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request):
    require_directory_actor(request.user)
    form = DirectoryConfirmForm(request.POST)
    if form.is_valid():
        try:
            result = confirm_directory_change(actor=request.user,proposal_token=form.cleaned_data['proposal_token'],
                operator_password=form.cleaned_data['operator_password'],confirmed=form.cleaned_data['confirmed'])
        except EXPECTED_ERRORS as exc:
            add_error(form,exc)
        except DatabaseError:
            return render(request,'registry/directory_recovery.html',{'problem':
                '暂时无法核对保存结果。请先查询目录，勿盲目重复登记；此提示不代表此前一定没有保存。'},status=503)
        else:
            messages.success(request,'本次操作此前已保存，没有重复执行；请核对当前记录。' if result.repeated else
                '资料已保存并记录操作依据。没有创建账号、发放权限、安排出诊或更改既有预约与账单。')
            return redirect('directory_detail',kind='dentist' if result.kind == 'association' else result.kind,pk=result.object_id)
    return render(request,'registry/directory_recovery.html',{'errors':form.errors,
        'problem':'本次确认未执行。请返回目录查询当前资料，再重新核对；此前成功的登记不会因此撤销。'},status=409)
