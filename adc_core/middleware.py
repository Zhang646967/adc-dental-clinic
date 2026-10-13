"""Instance read-only boundary evaluated against Django-resolved view names."""
from django.conf import settings
from django.shortcuts import render
from adc_core.read_only_policy import allowed_in_read_only

class ReadOnlyDemoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        # process_view runs after URL resolution. The CSRF middleware precedes
        # this middleware; business services independently call require_writable.
        match = getattr(request, "resolver_match", None)
        name = getattr(match, "view_name", None)
        if settings.ADC_READ_ONLY and not allowed_in_read_only(request.method, name):
            return render(request, '403.html', {'read_only_denial': True}, status=403)
        return None
