"""Private operational metadata. Never format arbitrary messages, args or exceptions.

Business audit remains owned by the transactional business commands. This module
has no Django/ORM dependency and is also used by the Gunicorn master process.
"""
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import logging
import os
import re
import threading
import time


@dataclass(frozen=True)
class RequestTrace:
    request_id: str
    method: str
    route: str = 'unresolved'


TRACE = ContextVar('adc_request_trace', default=None)
ID_PATTERN = re.compile(r'[a-f0-9]{32}\Z')
COMMIT_PATTERN = re.compile(r'[a-f0-9]{40}\Z')
METHODS = frozenset(('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE'))
EVENTS = frozenset((
    'http.completed', 'http.denied', 'http.conflict', 'http.failed',
    'auth.login_success', 'auth.login_failed', 'auth.logout',
    'framework.request', 'framework.security', 'framework.database', 'framework.notice',
    'server.access', 'server.notice', 'runtime.notice', 'command.failed', 'command.notice',
    'operations.heartbeat_failed',
))
LOGGER_EVENTS = {'django.request': 'framework.request', 'django.server': 'framework.request',
                 'django.db.backends': 'framework.database', 'gunicorn.access': 'server.access',
                 'gunicorn.error': 'server.notice'}


def method_code(value):
    return value if isinstance(value, str) and value in METHODS else 'OTHER'


def source_commit():
    value = os.environ.get('ADC_SOURCE_COMMIT', '')
    return value if COMMIT_PATTERN.fullmatch(value) else 'unknown'


def request_id():
    trace = TRACE.get()
    return trace.request_id if trace else ''


def set_route(name):
    trace = TRACE.get()
    if trace and isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_:.-]{0,79}', name):
        TRACE.set(replace(trace, route=name))


def exception_code(info):
    # Never stringify an exception, SQL, traceback, frame, local or class name.
    if not isinstance(info, tuple) or len(info) != 3 or not isinstance(info[1], BaseException):
        return None
    error = info[1]
    try:
        from django.db import DatabaseError, IntegrityError
        if isinstance(error, IntegrityError):
            return 'database_integrity'
        if isinstance(error, DatabaseError):
            return 'database_failure'
    except ImportError:
        pass
    if isinstance(error, (ConnectionError, TimeoutError)):
        return 'dependency_unavailable'
    if isinstance(error, OSError):
        return 'io_failure'
    return 'unhandled_exception'


class SafeJsonFormatter(logging.Formatter):
    def format(self, record):
        name = record.name if isinstance(record.name, str) else ''
        event = LOGGER_EVENTS.get(name, 'runtime.notice')
        if name.startswith('django.security'):
            event = 'framework.security'
        elif name.startswith('django.') and event == 'runtime.notice':
            event = 'framework.notice'
        elif name == 'adc.operations':
            candidate = record.__dict__.get('adc_event')
            if isinstance(candidate, str) and candidate in EVENTS:
                event = candidate
        level = ('CRITICAL' if record.levelno >= 50 else 'ERROR' if record.levelno >= 40
                 else 'WARNING' if record.levelno >= 30 else 'INFO')
        result = {'v': 1, 'time': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  'severity': level, 'service': 'gunicorn' if name.startswith('gunicorn.') else 'application',
                  'source_commit': source_commit(), 'event': event}
        trace = TRACE.get()
        if trace is None:
            # Django may report a rejected response after the middleware has unwound.
            # Reuse only the immutable context we attached to its real request object.
            request = record.__dict__.get('request')
            if request is not None:
                try:
                    from django.http import HttpRequest
                    candidate = vars(request).get('_adc_trace') if isinstance(request, HttpRequest) else None
                    if isinstance(candidate, RequestTrace):
                        trace = candidate
                except ImportError:
                    pass
        if trace:
            result.update(request_id=trace.request_id, method=trace.method, route=trace.route)
        if name == 'adc.operations':
            for key, maximum in (('status', 599), ('duration_ms', 86400000)):
                value = record.__dict__.get('adc_' + key)
                if type(value) is int and 0 <= value <= maximum:
                    result[key] = value
        elif name == 'gunicorn.access' and isinstance(record.args, dict):
            atoms = record.args
            value = atoms.get('{x-request-id}o', '')
            if isinstance(value, str) and ID_PATTERN.fullmatch(value):
                result['request_id'] = value
            result['method'] = method_code(atoms.get('m'))
            value = atoms.get('s')
            if type(value) is int and 100 <= value <= 599:
                result['status'] = value
            elif isinstance(value, str) and re.fullmatch(r'[1-5][0-9]{2}', value):
                result['status'] = int(value)
        error = exception_code(record.exc_info)
        if error:
            result['error_code'] = error
        # getMessage(), str(args), exception formatting and record.extra are deliberately unused.
        return json.dumps(result, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


_failure_lock = threading.Lock()
_last_failure = -float('inf')


def report_sink_failure():
    """A bounded, constant fallback; it also tolerates a broken stderr."""
    global _last_failure
    try:
        with _failure_lock:
            now = time.monotonic()
            if now - _last_failure < 60:
                return
            _last_failure = now
        os.write(2, b'{"v":1,"severity":"ERROR","event":"logging.sink_unavailable"}\n')
    except Exception:
        pass


class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            self.stream.write(self.format(record) + self.terminator)
            self.flush()
        except Exception:
            # logging.handleError can print the original secret message and traceback.
            report_sink_failure()


def emit_event(event, *, status=None, duration_ms=None):
    try:
        if event not in EVENTS:
            return
        level = logging.ERROR if event in ('http.failed', 'command.failed', 'operations.heartbeat_failed') else logging.INFO
        logging.getLogger('adc.operations').log(level, 'operational event', extra={
            'adc_event': event, 'adc_status': status, 'adc_duration_ms': duration_ms})
    except Exception:
        report_sink_failure()


def logging_config():
    return {
        'version': 1, 'disable_existing_loggers': True,
        'formatters': {'safe': {'()': 'adc_core.operational_logging.SafeJsonFormatter'}},
        'handlers': {'safe': {'class': 'adc_core.operational_logging.SafeStreamHandler',
                              'formatter': 'safe', 'stream': 'ext://sys.stdout'}},
        'root': {'handlers': ['safe'], 'level': 'INFO'},
        'loggers': {name: {'handlers': ['safe'], 'level': 'INFO', 'propagate': False}
                    for name in ('adc.operations', 'django', 'django.request', 'django.server',
                                 'django.security', 'django.db.backends', 'gunicorn.error', 'gunicorn.access')},
    }


class SafeCommandErrors:
    """Runtime management stderr cannot serialize a CommandError or traceback."""
    encoding = 'utf-8'
    def write(self, value):
        if value and value.strip():
            self.event('command.notice', logging.WARNING)
        return len(value)
    def event(self, event, level=logging.ERROR):
        try:
            record = logging.LogRecord('adc.operations', level, '', 0, '', (), None)
            record.adc_event = event
            os.write(2, (SafeJsonFormatter().format(record) + '\n').encode('ascii'))
        except Exception:
            report_sink_failure()
    def flush(self):
        pass
    def isatty(self):
        return False
