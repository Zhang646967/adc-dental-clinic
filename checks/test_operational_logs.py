"""Adversarial serialization checks; HTTP/transaction checks run in PostgreSQL."""
import io
import json
import logging
import os
import unittest
from unittest.mock import patch
from adc_core.operational_logging import SafeJsonFormatter, SafeStreamHandler, SafeCommandErrors, TRACE, RequestTrace


class OperationalSerializationTests(unittest.TestCase):
    def record(self, name='django.request'):
        return logging.LogRecord(name, logging.ERROR, '/PRIVATE_SOURCE', 4,
                                 'SECRET_PASSWORD %s', ('SECRET_SQL',), None)

    def test_arbitrary_message_arguments_and_extras_never_serialized(self):
        record = self.record()
        record.request_id = 'FORGED'; record.credentials = 'SECRET_CREDENTIALS'
        record.exc_text = 'SECRET_TRACEBACK'
        text = SafeJsonFormatter().format(record)
        self.assertNotIn('SECRET', text); self.assertNotIn('PRIVATE_SOURCE', text)
        self.assertNotIn('FORGED', text); self.assertNotIn('request_id', json.loads(text))

    def test_exception_string_and_class_name_are_never_evaluated(self):
        class SECRET_Exception(Exception):
            def __str__(self):raise AssertionError('exception evaluated')
        record = self.record(); record.exc_info = (SECRET_Exception, SECRET_Exception(), None)
        data = json.loads(SafeJsonFormatter().format(record))
        self.assertEqual(data['error_code'], 'unhandled_exception')
        self.assertNotIn('SECRET', json.dumps(data))

    def test_injected_event_is_replaced_by_bounded_code(self):
        record = self.record('adc.operations'); record.adc_event = 'SECRET\n{"injected":true}'
        text = SafeJsonFormatter().format(record)
        self.assertEqual(json.loads(text)['event'], 'runtime.notice')
        self.assertNotIn('\n', text); self.assertNotIn('SECRET', text)

    def test_unsafe_method_and_forged_access_id_are_not_retained(self):
        record = self.record('gunicorn.access')
        record.args = {'m': 'SECRET_METHOD', 's': '502', '{x-request-id}o': 'SECRET_HEADER', 'U': '/SECRET_URL'}
        data = json.loads(SafeJsonFormatter().format(record))
        self.assertEqual(data['method'], 'OTHER'); self.assertEqual(data['status'], 502)
        self.assertNotIn('SECRET', json.dumps(data)); self.assertNotIn('request_id', data)

    def test_gateway_access_keeps_only_server_response_id(self):
        record = self.record('gunicorn.access')
        record.args = {'m': 'GET', 's': 200, '{x-request-id}o': 'a'*32, 'q': 'SECRET_QUERY'}
        data = json.loads(SafeJsonFormatter().format(record))
        self.assertEqual(data['request_id'], 'a'*32); self.assertEqual(data['status'], 200)
        self.assertNotIn('SECRET', json.dumps(data))

    def test_invalid_commit_is_unknown(self):
        with patch.dict(os.environ, {'ADC_SOURCE_COMMIT': 'SECRET\nTOKEN'}):
            self.assertEqual(json.loads(SafeJsonFormatter().format(self.record()))['source_commit'], 'unknown')

    def test_reviewed_commit_is_preserved(self):
        with patch.dict(os.environ, {'ADC_SOURCE_COMMIT': 'a'*40}):
            self.assertEqual(json.loads(SafeJsonFormatter().format(self.record()))['source_commit'], 'a'*40)

    def test_context_metadata_is_server_owned(self):
        token = TRACE.set(RequestTrace('b'*32, 'POST', 'cash_review'))
        try:
            record = self.record(); record.adc_request_id='SECRET'
            data = json.loads(SafeJsonFormatter().format(record))
            self.assertEqual((data['request_id'], data['route']), ('b'*32, 'cash_review'))
        finally:TRACE.reset(token)

    def test_sink_failure_never_prints_record_or_raises(self):
        class Broken(io.StringIO):
            def write(self, text):raise OSError('SECRET_DISK')
        handler = SafeStreamHandler(Broken()); handler.setFormatter(SafeJsonFormatter())
        with patch('adc_core.operational_logging.report_sink_failure') as failed:
            handler.handle(self.record()); failed.assert_called_once()

    def test_runtime_command_error_has_no_original_content(self):
        with patch('adc_core.operational_logging.os.write') as output:
            SafeCommandErrors().write('SECRET_CONNECTION_AND_SQL\n')
            data=json.loads(output.call_args.args[1])
        self.assertEqual(data['event'], 'command.notice'); self.assertNotIn('SECRET', str(data))
