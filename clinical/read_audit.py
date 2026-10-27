"""Route-based sensitive read evidence, including authorization-denied responses.

Store only typed route/object/purpose/outcome metadata. Query strings, form
values, names, contact details and clinical text never enter this table or logs.
This append is observational evidence, not a business-state mutation.
"""
from clinical.models import SensitiveReadEvent
from django.urls import resolve, Resolver404

ROUTES = {
    'fund_claims': ('FUND_CLAIM_LIST','BILLING'), 'fund_claim_detail': ('INSURANCE_SETTLEMENT','BILLING'),
    'fund_allocation_new': ('FUND_TRANSFER','BILLING'), 'fund_allocation_detail': ('FUND_ALLOCATION','BILLING'),
    'fund_allocation_review': ('FUND_ALLOCATION','BILLING'), 'fund_issues': ('FUND_ISSUE_LIST','BILLING'),
    'fund_issue_new': ('INSURANCE_SETTLEMENT','BILLING'), 'fund_issue_detail': ('FUND_ISSUE','BILLING'),
    'fund_issue_followup': ('FUND_ISSUE','BILLING'),
    'insurance_cancellation_new': ('INSURANCE_SETTLEMENT','BILLING'),
    'insurance_cancellation_query': ('INSURANCE_SETTLEMENT','BILLING'),
    'insurance_cancellation_review': ('INSURANCE_SETTLEMENT','BILLING'),
    'fund_transfers': ('FUND_TRANSFER_LIST','BILLING'), 'fund_transfer_new': ('STATEMENT_LINE','BILLING'),
    'fund_transfer_detail': ('FUND_TRANSFER','BILLING'), 'fund_transfer_review': ('FUND_TRANSFER','BILLING'),
    'insurance_settlements': ('INSURANCE_REQUEST_LIST', 'BILLING'),
    'insurance_settlement_new': ('INVOICE', 'BILLING'),
    'insurance_settlement_detail': ('INSURANCE_SETTLEMENT', 'BILLING'),
    'insurance_settlement_query': ('INSURANCE_SETTLEMENT', 'BILLING'),
    'insurance_settlement_review': ('INSURANCE_SETTLEMENT', 'BILLING'),
    'insurance_eligibility': ('INSURANCE_ELIGIBILITY', 'BILLING'),
    'clinical_recalls':('RECALL_LIST','COORDINATION'),'clinical_recall_claim':('NEXT_VISIT','COORDINATION'),
    'clinical_recall_detail':('RECALL','COORDINATION'),'clinical_recall_action':('RECALL','COORDINATION'),
    'clinical_labs':('LAB_LIST','COORDINATION'),'clinical_lab_detail':('LAB','COORDINATION'),'clinical_lab_action':('LAB','COORDINATION'),
    'clinical_doctor_labs':('CARE','CARE'),'clinical_doctor_lab_action':('LAB','CARE','case_id'),
    'clinical_doctor_lab_queue':('LAB_LIST','CARE'),
    'clinical_plans':('PLAN_LIST','CARE'),'clinical_plan_detail':('PLAN','CARE'),
    'clinical_plan_preview':('PLAN','CARE'),'clinical_plan_decision':('PLAN','CARE'),
    'clinical_actual':('ACTUAL','CARE'),'clinical_actual_void':('ACTUAL','CARE'),
    'clinical_next_visit':('NEXT_VISIT','CARE'),'clinical_next_withdraw':('NEXT_VISIT','CARE'),
    'clinical_next_list':('NEXT_VISIT_LIST','COORDINATION'),'clinical_next_link':('NEXT_VISIT','COORDINATION'),
    'portal_plans':('PLAN_LIST','SELF_PLAN'),'portal_plan':('PLAN','SELF_PLAN'),
    'portal_plan_decision':('PLAN','SELF_PLAN'),
    'mini_plans':('PLAN_LIST','SELF_PLAN'),'mini_plan':('PLAN','SELF_PLAN'),
    'mini_plan_decision_preview':('PLAN','SELF_PLAN'),
    'mini_plan_decision_confirm':('PLAN','SELF_PLAN'),
    'clinical_worklist':('VISIT_LIST','CARE'),'clinical_encounter':('CARE','CARE'),
    'clinical_interview_history':('CARE','HISTORY'),'clinical_record_preview':('CARE','CARE'),
    'clinical_record_confirm':('CARE','CARE'),
    'portal_history':('HISTORY','SELF_HISTORY'),'mini_history':('HISTORY','SELF_HISTORY'),
    'mini_history_submit':('HISTORY','SELF_HISTORY'),
    'patients': ('PATIENT_LIST', 'CARE'), 'patient_detail': ('PATIENT', 'CARE'),
    'patient_lookup': ('IDENTITY_LOOKUP', 'IDENTITY'), 'patient_contact_edit': ('PATIENT', 'COORDINATION'),
    'patient_contact_confirm': ('PATIENT', 'COORDINATION'),
    'visits': ('VISIT_LIST', 'COORDINATION'), 'visit_detail': ('VISIT', 'COORDINATION'),
    'visit_reschedule': ('VISIT', 'COORDINATION'), 'care_workspace': ('CARE', 'CARE'),
    'care_complete': ('CARE', 'CARE'), 'invoice_detail': ('INVOICE', 'BILLING'),
    'portal_invoice': ('INVOICE', 'BILLING'), 'mini_invoice': ('INVOICE', 'BILLING'), 'portal_visit': ('VISIT', 'COORDINATION'),
    'portal_appointments': ('VISIT_LIST', 'COORDINATION'), 'portal_reschedule': ('VISIT', 'COORDINATION'),
    'correction_create': ('CARE', 'BILLING'), 'correction_detail': ('CORRECTION', 'BILLING'),
    'clinical_referrals': ('REFERRAL_LIST', 'TRANSFER'), 'clinical_referral_detail': ('REFERRAL', 'IDENTITY'),
    'clinical_referral_record': ('REFERRAL', 'TRANSFER'), 'clinical_referral_new': ('CARE', 'TRANSFER'),
    'mini_overview': ('VISIT_LIST','COORDINATION'), 'mini_visits': ('VISIT_LIST','COORDINATION'),
    'mini_visit': ('VISIT','COORDINATION'), 'mini_waitlist': ('WAITLIST','COORDINATION'),
    'mini_offer': ('OFFER','COORDINATION'), 'mini_subjects': ('PATIENT_LIST','IDENTITY'),
    'clinical_referral_action': ('REFERRAL','IDENTITY'),
    'mini_referrals': ('REFERRAL_LIST','TRANSFER'),
    'mini_referral_stop_preview': ('REFERRAL','TRANSFER'),
    'doctor_home': ('VISIT_LIST','CARE'), 'frontdesk_home': ('VISIT_LIST','COORDINATION'),
    'portal_home': ('VISIT_LIST','COORDINATION'), 'cash_receivables': ('INVOICE_LIST','BILLING'),
    'patient_relationships': ('PATIENT_LIST','IDENTITY'),
    'patient_relationship_detail': ('RELATIONSHIP','IDENTITY'),
    'patient_relationship_action': ('RELATIONSHIP','IDENTITY'),
}


class SensitiveReadMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = getattr(request, 'resolver_match', None)
        if match is None:
            # Workspace denial can return before Django invokes the resolved view.
            # Resolve only the server route; never retain path/query/body text.
            try:match=resolve(request.path_info)
            except Resolver404:return response
        name = getattr(match, 'url_name', None)
        route = ROUTES.get(name)
        # A successful write redirect contains no sensitive read response.
        # Denied attempts and read redirects remain attributable evidence.
        redirected_write=request.method not in ('GET','HEAD') and 300<=response.status_code<400
        if route and request.user.is_authenticated and not redirected_write:
            ctx = getattr(request.user, '_adc_workspace', None)
            SensitiveReadEvent.objects.create(actor=request.user, role=ctx.role if ctx else '',
                object_kind=route[0], object_id=match.kwargs.get(route[2] if len(route)>2 else 'pk'), purpose=route[1],
                outcome='ALLOW' if getattr(response,'adc_sensitive_read_authorized',False) or 200 <= response.status_code < 300 else 'DENY',
                trace_id=getattr(request, 'adc_request_id', ''))
        return response
