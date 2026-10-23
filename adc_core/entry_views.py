"""Public entry, containing curated instructions and links only."""
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_safe
from adc_core.entry_catalog import ENTRY_ROUTES, render_entry


@require_safe
def system_entry(request):
    # No RequestContext: a public walkthrough must not query workspace or patient
    # context processors, create a scope, or change guide/session progress.
    return HttpResponse(render_entry({name: reverse(name) for name in ENTRY_ROUTES}),
        headers={"Cache-Control": "no-store"})
