"""Explicit read-only result check, protected by CSRF and the active workspace.

POST is used to carry the signed context without URL/history leakage. The handler
has no business writes and never retries acceptance or creates an appointment.
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from workspaces.models import WorkspaceContext
from workspaces.context import SESSION_KEY, attach, valid_context, check_token
from portal.policies import patient_access
from accounts.policies import bindings
from guidance.result_selectors import load_wait_fact
from guidance.result_rules import assess_wait, CONTRACT_VERSION

class StaleResultContext(Exception):
    pass


def _fresh_actor(request):
    ctx = WorkspaceContext.objects.filter(pk=request.session.get(SESSION_KEY), user_id=request.user.pk).first()
    if ctx is None or not valid_context(request.user, ctx):
        raise StaleResultContext()
    if ctx.role not in ("PATIENT", "FRONT_DESK") or (ctx.role == "FRONT_DESK" and ctx.clinic_id is None):
        raise PermissionDenied("当前身份不能核对此类个人预约结果。")
    if not check_token(ctx, request.POST.get("workspace_token", "")):
        raise StaleResultContext()
    attach(request, ctx)
    return ctx


def _still_owns(request, fact):
    ctx = _fresh_actor(request)
    if ctx.role == "PATIENT":
        if patient_access(request.user).patient_id != fact.patient_id:
            raise Http404("未找到可核对的记录。")
    elif ctx.clinic_id != fact.clinic_id or not bindings(request.user).filter(
            role="FRONT_DESK", scope_kind="CLINIC", clinic_id=fact.clinic_id).exists():
        raise Http404("未找到可核对的记录。")


@never_cache
@login_required
@require_POST
def wait_result(request, pk):
    base = "portal/base.html" if getattr(getattr(request, "workspace", None), "role", "") == "PATIENT" else "base.html"
    payload = {"base_template": base, "contract": CONTRACT_VERSION, "entry_id": pk}
    try:
        _fresh_actor(request)
        # One statement returns request, offer and linked Visit at one DB snapshot.
        fact = load_wait_fact(request.user, pk)
        if fact is None:
            raise Http404("未找到可核对的记录。")
        observed_at = timezone.now()
        result = assess_wait(fact, observed_at)
        _still_owns(request, fact)  # revoke/rebind/switch while querying: suppress old result
    except StaleResultContext:
        payload.update(problem="工作身份、诊所或页面已变化，不能沿用旧页面核对。请返回工作台重新选择记录。", error_code="CONTEXT_CHANGED")
        return render(request, "guidance/result.html", payload, status=409)
    except DatabaseError:
        # No request context processors: the database may be unavailable here.
        return HttpResponse(render_to_string("guidance/result_unavailable.html",
            {"home_url": reverse("dashboard")}), status=503)
    target_url = reverse("waitlist")
    if result.target == "offer":
        target_url = reverse("wait_offer", args=[result.target_id])
    elif result.target == "visit":
        route = "portal_visit" if request.workspace.role == "PATIENT" else "visit_detail"
        target_url = reverse(route, args=[result.target_id])
    payload.update(result=result, observed_at=observed_at, target_url=target_url)
    return render(request, "guidance/result.html", payload, status=409 if result.code == "INCONSISTENT" else 200)
