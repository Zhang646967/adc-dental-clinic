"""Resume a service choice only after ordinary authorized workspace activation."""
from django.core import signing
from django.urls import reverse
from portal.booking_intent_rules import INTENT_KEY, INTENT_SALT, INTENT_SECONDS, selected_service
from portal.service_catalogue import public_profiles
from workspaces.context import valid_context


def remember_service(request, service_id):
    ctx = request.workspace
    request.session[INTENT_KEY] = signing.dumps({'uid': request.user.pk,
        'workspace': str(ctx.pk), 'service': service_id}, salt=INTENT_SALT)


def destination_after_activation(request):
    token = request.session.get(INTENT_KEY)
    if not token:
        return None
    ctx = getattr(request, 'workspace', None)
    if ctx is None or not ctx.role:
        return None  # Preserve the choice until the person explicitly selects a role.
    request.session.pop(INTENT_KEY, None)
    if ctx.role != 'PATIENT' or not valid_context(request.user, ctx):
        return None
    try:
        payload = signing.loads(token, salt=INTENT_SALT, max_age=INTENT_SECONDS)
    except (signing.BadSignature, TypeError, ValueError):
        return None
    service_id = selected_service(payload, user_id=request.user.pk, workspace_id=ctx.pk)
    if service_id is None:
        return None
    profile = next((p for p in public_profiles() if p.service_id == service_id), None)
    if not profile or profile.category == 'CHILDREN':
        return None
    return reverse('portal_slots') + '?service=' + str(service_id)
