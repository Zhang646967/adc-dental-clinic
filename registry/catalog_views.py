from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods
from accounts.finance_access import require_finance_read
from workspaces.context import require_active
from registry.models import TreatmentType
from registry import catalog
from registry.catalog_forms import CatalogueCreateForm, CataloguePriceForm
from adc_core.http_support import EXPECTED_ERRORS, add_error

@login_required
@require_GET
def listing(request):
    catalog.require_read(request.user)
    q=request.GET.get('q','').strip()[:120]
    qs=TreatmentType.objects.order_by('code')
    if q:qs=qs.filter(name__icontains=q)
    page=Paginator(qs,25).get_page(request.GET.get('page'))
    return render(request,'registry/catalog_list.html',{'page':page,'q':q,'can_edit':request.workspace.role=='FINANCE'})

@login_required
@require_http_methods(['GET','POST'])
def create(request):
    require_active(request.user,('FINANCE',));require_finance_read(request.user)
    form=CatalogueCreateForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:catalog.create_item(actor=request.user,code=d['code'],name=d['name'],unit=d['unit'],price=d['price'],reason=d['reason'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'已建立标准目录项目。请核对；尚未为任何患者记录治疗或收费。')
            return redirect('catalogue_list')
    return render(request,'registry/catalog_form.html',{'form':form,'title':'新增标准治疗项目'})

@login_required
@require_http_methods(['GET','POST'])
def price(request,pk):
    require_active(request.user,('FINANCE',));require_finance_read(request.user)
    item=get_object_or_404(TreatmentType,pk=pk,is_active=True)
    form=CataloguePriceForm(request.POST or None,initial={'state_token':catalog.price_token(request.user,item),'price':item.standard_unit_price})
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:catalog.change_price(actor=request.user,item_id=item.pk,token=d['state_token'],price=d['price'],reason=d['reason'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'当前目录单价已更新；已有治疗明细及历史账单保持原金额。')
            return redirect('catalogue_list')
    return render(request,'registry/catalog_form.html',{'form':form,'title':'核对并修改当前单价','item':item})
