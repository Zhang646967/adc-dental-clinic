"""Route-based sensitive read evidence, including authorization-denied responses.

Store only typed route/object/purpose/outcome metadata. Query strings, form
values, names, contact details and clinical text never enter this table or logs.
This append is observational evidence, not a business-state mutation.
"""
from clinical.models import SensitiveReadEvent
from django.urls import resolve, Resolver404

ROUTES = {
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
    'portal_invoice': ('INVOICE', 'BILLING'), 'portal_visit': ('VISIT', 'COORDINATION'),
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
                object_kind=route[0], object_id=match.kwargs.get('pk'), purpose=route[1],
                outcome='ALLOW' if getattr(response,'adc_sensitive_read_authorized',False) or 200 <= response.status_code < 300 else 'DENY',
                trace_id=getattr(request, 'adc_request_id', ''))
        return response
