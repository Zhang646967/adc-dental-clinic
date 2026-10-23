from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.http import require_GET,require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from accounts.policies import bindings
from adc_core.http_support import EXPECTED_ERRORS,add_error
from care.forms import AllergyReviewForm,TreatmentForm,CompletionForm,RemoveLineForm,ClinicalNoteForm
from care.models import VisitRecordVersion,Invoice
from care.services import review_allergies,add_treatment,complete_visit,remove_treatment,save_clinical_note
from care.progress import care_progress
from adc_core.snapshots import reporting_snapshot
from finance.cash_selectors import invoice_balance
from scheduling.models import Visit
from scheduling.selectors import visible_visits,can_read_visit_details

def _own_visit(user,pk):
    v=get_object_or_404(Visit.objects.select_related("patient","dentist","clinic"),pk=pk)
    if not bindings(user).filter(role="DENTIST",scope_kind="SELF_DENTIST",user__dentist_id=v.dentist_id).exists():
        raise PermissionDenied("只有本次负责牙医可以进入接诊工作台。")
    return v

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(["GET","POST"])
def workspace(request,pk):
    _own_visit(request.user,pk)
    progress=care_progress(request.user,pk)
    v=progress['visit'];version=progress['record']
    initial={"expected_version":v.lock_version,"patient_version":v.patient.allergy_info_version,
             "status":v.patient.allergy_status,"allergy_ids":list(v.patient.allergy_links.filter(is_active=True).values_list("allergy_id",flat=True))}
    action=request.POST.get("action") if request.method=="POST" else None
    # Separate HTML ids keep labels attached to the right form on this page.
    # Keep POST field names unchanged so the command and version checks remain.
    allergy_form=AllergyReviewForm(request.POST if action=="review" else None,initial=initial,auto_id="id_allergy_%s")
    treatment_form=TreatmentForm(request.POST if action=="add" else None,initial=initial,auto_id="id_treatment_%s")
    removal_form=RemoveLineForm(request.POST if action=="remove" else None,initial=initial,auto_id="id_removal_%s")
    note_form=ClinicalNoteForm(request.POST if action=="note" else None,
        initial=dict(initial,clinical_note=progress['clinical_note']),auto_id="id_note_%s")
    active={"review":allergy_form,"add":treatment_form,"remove":removal_form,"note":note_form}.get(action)
    if request.method=="POST":
        if active is None: raise PermissionDenied("未知接诊操作。")
        if active.is_valid():
            data=dict(active.cleaned_data);data.pop("confirmed",None)
            try:
                if action=="review":
                    data["allergy_ids"]=[a.pk for a in data["allergy_ids"]]
                    review_allergies(actor=request.user,visit_id=v.pk,**data)
                elif action=="add":
                    data["treatment_id"]=data["treatment_id"].pk
                    add_treatment(actor=request.user,visit_id=v.pk,**data)
                elif action=="note":save_clinical_note(actor=request.user,visit_id=v.pk,**data)
                else: remove_treatment(actor=request.user,visit_id=v.pk,**data)
            except EXPECTED_ERRORS as exc: add_error(active,exc)
            else:
                messages.success(request,"已保存并记录操作历史。")
                return redirect("care_workspace",pk=v.pk)
    return render(request,"care/workspace.html",dict(progress,
        allergy_form=allergy_form,treatment_form=treatment_form,removal_form=removal_form,note_form=note_form))

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(["GET","POST"])
def complete(request,pk):
    _own_visit(request.user,pk)
    progress=care_progress(request.user,pk);v=progress['visit']
    form=CompletionForm(request.POST or None,initial={"expected_version":v.lock_version,
        "outcome":"TREATED" if progress['lines'] else "NO_TREATMENT"})
    if request.method=="POST" and form.is_valid():
        data=dict(form.cleaned_data);data.pop("confirmed")
        try: invoice=complete_visit(actor=request.user,visit_id=v.pk,**data)
        except EXPECTED_ERRORS as exc: add_error(form,exc)
        else:
            messages.success(request,"本次接诊已关闭并生成唯一结算单。该金额为开单金额，不是实收款。")
            return redirect("invoice_detail",pk=invoice.pk)
    return render(request,"care/complete.html",dict(progress,form=form))


def invoice_context(invoice,request,*,portal=False):
    with reporting_snapshot():
        current=Invoice.objects.select_related('visit','current_record_version').get(pk=invoice.pk)
        return _invoice_context(current,request,portal=portal)

def _invoice_context(invoice,request,*,portal=False):
    from django.http import Http404
    record=invoice.current_record_version
    requested=request.GET.get('revision')
    if requested is not None:
        try:
            n=int(requested)
            if n<1:raise ValueError
        except (TypeError,ValueError):raise Http404('无效版本。')
        record=get_object_or_404(VisitRecordVersion,visit_id=invoice.visit_id,revision_no=n,state='PUBLISHED')
    # Deliberately do NOT include clinical_note or allergy snapshot in the invoice context.
    return {"base_template":"portal/base.html" if portal else "base.html",
        "invoice_no":invoice.invoice_no,"revision":record.revision_no,"header":record.billing_header_snapshot,
        "issued_at":invoice.first_issued_at,"total":record.total_amount,"outcome":record.outcome,
        "lines":list(record.treatment_lines.values("name_snapshot","unit_snapshot","quantity","unit_price","line_amount")),
        "patient_portal":portal,"visit_id":invoice.visit_id,
        "is_current":record.pk==invoice.current_record_version_id,
        "published_at":record.published_at,
        "revisions":tuple(VisitRecordVersion.objects.filter(visit_id=invoice.visit_id,state='PUBLISHED').order_by('-revision_no').values('revision_no','published_at')),
        "may_correct":not portal and invoice.visit.status=='COMPLETED' and bindings(request.user).filter(role='DENTIST',scope_kind='SELF_DENTIST',user__dentist_id=invoice.visit.dentist_id).exists(),
        "invoice_id":invoice.pk,
        "cash_balance":invoice_balance(invoice),
        "can_request_cash":not portal and bindings(request.user).filter(role='FRONT_DESK',scope_kind='CLINIC',clinic_id=invoice.visit.clinic_id).exists()}

@login_required
@require_GET
def invoice_detail(request,pk):
    invoice=get_object_or_404(Invoice.objects.select_related("visit","current_record_version"),pk=pk)
    if not can_read_visit_details(request.user,invoice.visit) and not bindings(request.user).filter(role="FINANCE",scope_kind="CHAIN").exists():
        raise PermissionDenied("没有这张结算单的访问权限。")
    return render(request,"care/invoice.html",invoice_context(invoice,request))

@login_required(login_url="portal_login")
@require_GET
def portal_invoice(request,pk):
    from portal.policies import patient_access
    access=patient_access(request.user,self_only=True)
    invoice=get_object_or_404(Invoice.objects.select_related("current_record_version"),pk=pk,visit__patient_id=access.patient_id)
    return render(request,"care/invoice.html",invoice_context(invoice,request,portal=True))
