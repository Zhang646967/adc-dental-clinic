"""HTTP diagnostic context; it never reads a body, grants or business objects."""
import time
from uuid import uuid4
from adc_core.operational_logging import TRACE, RequestTrace, emit_event, method_code, set_route


class RequestTraceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        trace = RequestTrace(uuid4().hex, method_code(request.method))
        token = TRACE.set(trace)
        request.adc_request_id = trace.request_id
        request._adc_trace = trace
        started = time.monotonic()
        try:
            response = self.get_response(request)
            from django.urls import resolve, Resolver404
            try:
                match = getattr(request, 'resolver_match', None) or resolve(request.path_info)
                set_route(match.view_name)
            except Resolver404:
                pass
            response['X-Request-ID'] = trace.request_id
            request._adc_trace = TRACE.get()
            status = response.status_code
            event = ('http.failed' if status >= 500 else 'http.denied' if status == 403
                     else 'http.conflict' if status == 409 else 'http.completed')
            emit_event(event, status=status, duration_ms=max(0, int((time.monotonic() - started) * 1000)))
            return response
        finally:
            TRACE.reset(token)

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Only the server's resolved route name, never raw paths/kwargs or client input.
        match = getattr(request, 'resolver_match', None)
        set_route(getattr(match, 'view_name', None))


def support_context(request):
    return {'request_id': getattr(request, 'adc_request_id', '')}


def server_error(request):
    from django.http import HttpResponse
    from django.template.loader import get_template
    # No RequestContext: a failed DB must not be queried again by navigation processors.
    return HttpResponse(get_template('500.html').render(support_context(request)), status=500)


def csrf_failure(request, reason=''):
    from django.http import HttpResponse
    from django.template.loader import get_template
    return HttpResponse(get_template('403.html').render(support_context(request)), status=403)


def login_success(sender, request, **kwargs):
    emit_event('auth.login_success')


def login_failed(sender, request, **kwargs):
    emit_event('auth.login_failed')


def logout(sender, request, **kwargs):
    emit_event('auth.logout')
