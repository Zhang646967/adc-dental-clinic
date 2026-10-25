from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render,redirect
from django.views.decorators.http import require_http_methods
from adc_core.http_support import EXPECTED_ERRORS,add_error
from equipment.policies import manager_clinic
from registry.directory_models import ClinicDirectory
from registry.branch_forms import DirectoryForm,DirectoryConfirmForm
from registry.branch_services import prepare_directory,confirm_directory,values
from registry.branch_projection import opening_data


@login_required
@require_http_methods(['GET','POST'])
def maintain(request):
    clinic=manager_clinic(request.user)
    row=ClinicDirectory.objects.filter(clinic_id=clinic).first()
    if request.method=='POST' and request.POST.get('action')=='confirm':
        form=DirectoryConfirmForm(request.POST)
        if form.is_valid():
            try:confirm_directory(actor=request.user,proposal_token=form.cleaned_data['proposal_token'],confirmed=form.cleaned_data['confirmed'])
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            else:
                messages.success(request,'门店公开资料已保存，历史名称与原预约保留。');return redirect('branch_directory_maintain')
        return render(request,'registry/branch_confirm.html',{'form':form,'failed':True},status=409)
    form=DirectoryForm(request.POST or None,instance=row)
    if request.method=='POST' and form.is_valid():
        try:preview=prepare_directory(actor=request.user,fields=values(form.instance))
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return render(request,'registry/branch_confirm.html',{'preview':preview,
            'form':DirectoryConfirmForm(initial={'proposal_token':preview['proposal_token']})})
    return render(request,'registry/branch_directory.html',{'form':form,'directory':row,
        'opening':opening_data(clinic),'versions':row.versions.select_related('actor')[:10] if row else []})
