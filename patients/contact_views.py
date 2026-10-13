from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from adc_core.http_support import EXPECTED_ERRORS, add_error
from patients.contact_forms import ContactEditForm, ContactConfirmForm
from patients.contact_rules import CONTACT_FIELDS
from patients.contact_services import contact_editor, prepare_contact_change, confirm_contact_change

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def edit(request, pk):
    editor = contact_editor(actor=request.user, patient_id=pk)
    form = ContactEditForm(request.POST if request.method == 'POST' else None,
                           initial={**editor.values, 'state_token': editor.state_token})
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            preview = prepare_contact_change(actor=request.user, patient_id=pk,
                state_token=data['state_token'], details={k:data[k] for k in CONTACT_FIELDS},
                reason_code=data['reason_code'])
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            return render(request, 'patients/contact_confirm.html', {
                'patient': preview.patient, 'rows': preview.rows, 'reason_label': preview.reason_label,
                'form': ContactConfirmForm(initial={'proposal_token':preview.proposal_token}),
            })
    return render(request, 'patients/contact_edit.html', {'patient':editor.patient, 'form':form,
                                                          'read_only':settings.ADC_READ_ONLY})

@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request, pk):
    form = ContactConfirmForm(request.POST)
    # Scope is checked before displaying even the error-recovery route.
    editor = contact_editor(actor=request.user, patient_id=pk)
    if form.is_valid():
        try:
            result = confirm_contact_change(actor=request.user, patient_id=pk,
                proposal_token=form.cleaned_data['proposal_token'], confirmed=form.cleaned_data['confirmed'])
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        except DatabaseError:
            return render(request, 'patients/contact_recovery.html', {
                'patient':editor.patient, 'problem':'暂时无法确认保存结果。请先核对当前资料，不要反复提交。',
            }, status=503)
        else:
            messages.success(request, '该次更正此前已保存，没有重复写入；请核对当前资料。' if result.repeated else
                             '联络资料已保存。患者身份、过敏记录、账号绑定和历史结算单未被本次操作修改。')
            return redirect('patient_detail', pk=pk)
    return render(request, 'patients/contact_recovery.html', {
        'patient':editor.patient, 'problem':'本次确认未执行，请先核对当前资料。之前已成功保存的操作不会因此撤销。',
        'errors':form.errors,
    }, status=409)
