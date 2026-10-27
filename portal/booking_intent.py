"""Typed service continuation after login and explicit patient selection."""
from django.core import signing
from django.urls import reverse
from portal.booking_intent_rules import INTENT_KEY,INTENT_SALT,INTENT_SECONDS,selected_service
from portal.service_catalogue import public_profiles
from portal.policies import patient_access,SubjectRequired
from workspaces.context import valid_context


def remember_service(request,service_id):
    ctx=request.workspace
    request.session[INTENT_KEY]=signing.dumps({'uid':request.user.pk,
        'workspace':str(ctx.pk),'service':service_id},salt=INTENT_SALT)
    from portal.profile_intent import remember
    remember(request,service_id)


def pending_profile(request):
    token=request.session.get(INTENT_KEY)
    ctx=getattr(request,'workspace',None)
    if not token or ctx is None or ctx.role!='PATIENT' or not valid_context(request.user,ctx):return None
    try:payload=signing.loads(token,salt=INTENT_SALT,max_age=INTENT_SECONDS)
    except (signing.BadSignature,TypeError,ValueError):return None
    service_id=selected_service(payload,user_id=request.user.pk,workspace_id=ctx.pk)
    return next((p for p in public_profiles() if p.service_id==service_id),None)


def destination_after_activation(request):
    if not request.session.get(INTENT_KEY):return None
    ctx=getattr(request,'workspace',None)
    if ctx is None or not ctx.role:return None
    profile=pending_profile(request)
    if not profile:
        request.session.pop(INTENT_KEY,None);return None
    try:access=patient_access(request.user)
    except SubjectRequired:return reverse('portal_subjects')
    if profile.category=='CHILDREN' and not access.guardian:return reverse('portal_subjects')
    if access.delegated and access.clinic_id!=profile.service.department.clinic_id:
        return reverse('portal_subjects')
    request.session.pop(INTENT_KEY,None)
    from portal.profile_intent import consume_selection
    from urllib.parse import urlencode
    selected=consume_selection(request,profile.service_id)
    query={'service':profile.service_id,'clinic':profile.service.department.clinic_id}
    query.update({k:v for k,v in selected.items() if v})
    return reverse('portal_slots')+'?'+urlencode(query)
