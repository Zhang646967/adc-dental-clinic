"""Real Django/PG requests, separate contexts, and retained financial invariants."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import io
import json
import logging
from threading import Barrier
from unittest.mock import patch
from django.contrib.auth.signals import user_login_failed
from django.db import close_old_connections, connections
from django.http import HttpResponse, StreamingHttpResponse
from django.test import Client, TransactionTestCase, override_settings
from django.urls import path, reverse
from adc_core.operational_logging import TRACE, SafeStreamHandler, SafeJsonFormatter
from config.urls import urlpatterns as application_urls
from tests.test_care_finance_equipment import CFEFixture
from finance.cash_models import CashEntry
from care.models import AuditEvent


def fail(request):
    raise RuntimeError('R21_SECRET_EXCEPTION ' + request.GET.get('secret',''))


def stream(request):
    return StreamingHttpResponse(iter([b'first', b'second']))


urlpatterns = [path('trace-rehearsal/failure/', fail, name='health'),
               path('trace-rehearsal/stream/', stream, name='health'), *application_urls]
handler500 = 'adc_core.request_trace.server_error'


@contextmanager
def captured_logs():
    output=io.StringIO(); handler=SafeStreamHandler(output);handler.setFormatter(SafeJsonFormatter())
    names=('adc.operations','django.request','django.security.csrf','django.security.DisallowedHost')
    before=[]
    for name in names:
        logger=logging.getLogger(name);before.append((logger,logger.handlers,logger.level,logger.propagate,logger.disabled))
        logger.handlers=[handler];logger.setLevel(logging.INFO);logger.propagate=False;logger.disabled=False
    try:yield output
    finally:
        for logger,handlers,level,propagate,disabled in before:
            logger.handlers=handlers;logger.setLevel(level);logger.propagate=propagate;logger.disabled=disabled


@override_settings(ROOT_URLCONF=__name__)
class RequestTracingTests(CFEFixture,TransactionTestCase):
    def setUp(self):
        self.setup_cfe()

    def test_server_id_replaces_headers_and_changes_each_request(self):
        with captured_logs() as output:
            responses=[Client().get('/accounts/login/?secret=R21_SECRET_QUERY',HTTP_X_REQUEST_ID='f'*32,
                       HTTP_X_ADC_GATEWAY_REQUEST_ID='R21_SECRET_HEADER') for _ in range(2)]
        ids=[r['X-Request-ID'] for r in responses]
        self.assertNotEqual(*ids)
        for value in ids:self.assertRegex(value,r'^[a-f0-9]{32}$');self.assertNotEqual(value,'f'*32)
        events=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([e['request_id'] for e in events if e['event']=='http.completed'],ids)
        self.assertNotIn('R21_SECRET',output.getvalue());self.assertIsNone(TRACE.get())

    def test_generic_failure_has_reference_and_no_exception_or_query(self):
        client=Client(raise_request_exception=False)
        with captured_logs() as output:
            response=client.get('/trace-rehearsal/failure/?secret=R21_SECRET_QUERY')
        self.assertEqual(response.status_code,500);self.assertContains(response,response['X-Request-ID'],status_code=500)
        self.assertNotIn('R21_SECRET',response.content.decode()+output.getvalue())
        self.assertContains(response,'核对已保存记录',status_code=500);self.assertIsNone(TRACE.get())

    def test_failure_page_needs_no_database_context_processors(self):
        from adc_core.request_trace import server_error
        from django.test import RequestFactory
        request=RequestFactory().get('/');request.adc_request_id='a'*32
        with self.assertNumQueries(0):response=server_error(request)
        self.assertContains(response,'a'*32,status_code=500)

    def test_csrf_failure_and_invalid_host_are_private_and_traced(self):
        with captured_logs() as output:
            csrf=Client(enforce_csrf_checks=True).post('/accounts/login/',{'username':'R21_SECRET_USER','password':'R21_SECRET_PASSWORD'})
            host=Client(raise_request_exception=False).get('/accounts/login/?secret=R21_SECRET_QUERY',HTTP_HOST='R21_SECRET_HOST.invalid')
        self.assertEqual(csrf.status_code,403);self.assertEqual(host.status_code,400)
        for response in (csrf,host):self.assertRegex(response['X-Request-ID'],r'^[a-f0-9]{32}$')
        self.assertNotIn('R21_SECRET',output.getvalue());self.assertIsNone(TRACE.get())

    def test_authentication_events_do_not_keep_entered_credentials(self):
        with captured_logs() as output:
            bad=Client().post('/accounts/login/',{'username':'R21_SECRET_USER','password':'R21_SECRET_PASSWORD'})
            good=Client().post('/accounts/login/',{'username':self.front.username,'password':'test-only-pass-123'})
        self.assertEqual(bad.status_code,200);self.assertEqual(good.status_code,302)
        events=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertIn('auth.login_failed',[e['event'] for e in events]);self.assertIn('auth.login_success',[e['event'] for e in events])
        self.assertNotIn('R21_SECRET',output.getvalue());self.assertNotIn(self.front.username,output.getvalue())
        self.assertNotIn('test-only-pass',output.getvalue())

    def test_parallel_success_and_failure_contexts_never_cross(self):
        barrier=Barrier(8,timeout=20)
        def request(index):
            close_old_connections()
            try:
                barrier.wait()
                response=Client(raise_request_exception=False).get('/trace-rehearsal/failure/' if index%2 else '/accounts/login/')
                return response.status_code,response['X-Request-ID'],TRACE.get()
            finally:connections.close_all()
        with captured_logs() as output,ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(request,range(8)))
        self.assertEqual(len({row[1] for row in results}),8)
        self.assertEqual([row[0] for row in results].count(500),4)
        self.assertTrue(all(row[2] is None for row in results))
        events=[json.loads(line) for line in output.getvalue().splitlines()]
        for status,request_id,_ in results:
            completion=[e for e in events if e.get('request_id')==request_id and e['event'].startswith('http.')]
            self.assertEqual(len(completion),1);self.assertEqual(completion[0]['status'],status)
        self.assertNotIn('R21_SECRET',output.getvalue())

    def test_stream_not_consumed_and_context_is_reset(self):
        response=Client().get('/trace-rehearsal/stream/')
        self.assertTrue(response.streaming);self.assertIsNone(TRACE.get())
        self.assertEqual(b''.join(response.streaming_content),b'firstsecond')

    def test_seven_roles_keep_current_permissions_without_sensitive_metadata(self):
        actors=((self.front,200),(self.manager,403),(self.doctor,200),(self.fin,200),
                (self.hq,403),(self.pa,403),(self.tech,403))
        visit,invoice=self.billed()
        with captured_logs() as output:
            for actor,status in actors:
                self.client.force_login(actor)
                response=self.client.get(reverse('invoice_detail',args=[invoice.pk]))
                self.assertEqual(response.status_code,status)
                self.assertRegex(response['X-Request-ID'],r'^[a-f0-9]{32}$')
        for value in (self.p1.name,invoice.invoice_no,self.front.username):self.assertNotIn(value,output.getvalue())
        for event in map(json.loads,output.getvalue().splitlines()):
            self.assertNotIn('clinic',event);self.assertNotIn('role',event)

    def test_foreign_clinic_and_revoked_grant_remain_rejected(self):
        from accounts.models import RoleAssignment
        visit,invoice=self.billed();self.client.force_login(self.front2)
        self.client.post(reverse('activate_clinic'),{'clinic':self.b.pk})
        with captured_logs() as output:
            foreign=self.client.get(reverse('invoice_detail',args=[invoice.pk]))
            RoleAssignment.objects.filter(user=self.front2).update(is_active=False)
            revoked=self.client.get(reverse('invoice_detail',args=[invoice.pk]))
        self.assertIn(foreign.status_code,(403,404));self.assertIn(revoked.status_code,(302,403,409))
        self.assertNotIn(invoice.invoice_no,output.getvalue())

    def test_sink_failure_does_not_change_cash_or_independent_review(self):
        visit,invoice=self.billed();before_audit=AuditEvent.objects.count()
        self.client.force_login(self.front)
        from workspaces.context import SESSION_KEY
        from workspaces.models import WorkspaceContext
        self.front._adc_workspace=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY])
        preview=self.cash_preview(invoice)
        logger=logging.getLogger('adc.operations')
        with patch.object(logger,'handle',side_effect=OSError('R21_SECRET_DISK')),patch('adc_core.operational_logging.report_sink_failure'):
            response=self.client.post(reverse('cash_invoice_request',args=[invoice.pk]),
                {'action':'confirm','confirmed':'on','proposal_token':preview['proposal_token']})
        self.assertEqual(response.status_code,302)
        entry=CashEntry.objects.get();posted=self.approve(entry)
        self.assertEqual(posted.state,'POSTED');self.assertEqual(CashEntry.objects.count(),1)
        self.assertGreater(AuditEvent.objects.count(),before_audit)
        self.assertEqual(self.balance(invoice)['net_received'],entry.amount)

    def test_http_success_and_denial_survive_broken_log_handler(self):
        self.client.force_login(self.manager)
        logger=logging.getLogger('adc.operations')
        with patch.object(logger,'handle',side_effect=OSError('R21_SECRET_DISK')),patch('adc_core.operational_logging.report_sink_failure'):
            allowed=self.client.get(reverse('equipment_list'))
            denied=self.client.get(reverse('patients'))
        self.assertEqual(allowed.status_code,200);self.assertEqual(denied.status_code,403)
        self.assertContains(denied,denied['X-Request-ID'],status_code=403)

    def test_required_business_audit_failure_still_rolls_back_cash(self):
        visit,invoice=self.billed();preview=self.cash_preview(invoice)
        from finance.cash_services import confirm_cash_request
        with patch('finance.cash_services.emit',side_effect=RuntimeError('R21_SECRET_AUDIT')):
            with self.assertRaises(RuntimeError):
                confirm_cash_request(actor=self.front,proposal_token=preview['proposal_token'],confirmed=True)
        self.assertFalse(CashEntry.objects.exists())

    def test_framework_response_warning_after_unwind_keeps_server_reference(self):
        self.client.force_login(self.manager)
        with captured_logs() as output:
            response=self.client.get(reverse('patients'))
        self.assertEqual(response.status_code,403);self.assertIsNone(TRACE.get())
        events=[json.loads(line) for line in output.getvalue().splitlines()]
        framework=[e for e in events if e['event']=='framework.request']
        self.assertTrue(framework)
        self.assertTrue(all(e['request_id']==response['X-Request-ID'] for e in framework))
        self.assertTrue(all(e['route']=='patients' for e in framework))
