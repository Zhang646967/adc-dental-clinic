"""Local inbox-only worker. Log aggregate status, never raw DB errors or targets."""
import json
import signal
import threading
import time
import os
from contextlib import ExitStack
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections
from notifications.dispatcher import dispatch_batch
from notifications.rules import bounded_batch
from adc_core.operations import Heartbeat, identity
from adc_core.operational_logging import emit_event

class Command(BaseCommand):
    help='派发已经提交的任务站内通知；不发送外部消息，不处理预约。'
    def add_arguments(self, parser):
        parser.add_argument('--batch-size',type=int,default=25)
        parser.add_argument('--watch',action='store_true')
        parser.add_argument('--interval',type=int,default=5)
    def handle(self,*args,**options):
        if settings.ADC_READ_ONLY:
            raise CommandError('只读模式拒绝后台通知写入。')
        try: bounded_batch(options['batch_size'])
        except ValueError as exc: raise CommandError(str(exc)) from None
        if not 2 <= options['interval'] <= 300:
            raise CommandError('轮询间隔限定为2到300秒。')
        if options['watch'] and threading.current_thread() is not threading.main_thread():
            raise CommandError('持续通知处理必须在独立进程的主线程中运行。')
        stopping = False
        previous_handlers = {}
        heartbeat = None
        if os.environ.get('ADC_OPERATIONS_INSTANCE'):
            try:
                heartbeat = Heartbeat(os.environ.get('ADC_WORKER_DIRECTORY', '/app/operations/worker'), identity())
            except (OSError, ValueError):
                # Optional diagnostics must not alter notification transactions.
                emit_event('operations.heartbeat_failed')
        def observed(phase, *, delivered=False):
            if heartbeat:
                try:
                    heartbeat.write(phase, delivered=delivered)
                except (OSError, ValueError):
                    emit_event('operations.heartbeat_failed')
        def request_stop(signum, frame):
            nonlocal stopping
            # A signal handler must not acquire a lock, log or touch the DB.
            stopping = True
        try:
            if options['watch']:
                for signum in (signal.SIGTERM, signal.SIGINT):
                    previous_handlers[signum] = signal.getsignal(signum)
                    signal.signal(signum, request_stop)
            # A configured instance has one heartbeat writer. Existing unconfigured
            # workers retain their original SKIP LOCKED dispatch behavior.
            with ExitStack() as lease:
                if heartbeat:
                    try:
                        lease.enter_context(heartbeat.store.lock('worker.lock'))
                    except BlockingIOError:
                        raise
                    except (OSError, ValueError):
                        heartbeat = None
                        emit_event('operations.heartbeat_failed')
                observed('starting')
                while not stopping:
                    observed('polling')
                    close_old_connections()
                    try:
                        results=dispatch_batch(options['batch_size'], should_stop=lambda: stopping)
                    except (DatabaseError,PermissionDenied,RuntimeError):
                        observed('failed')
                        raise CommandError('通知处理停止：数据库或运行策略不可用；没有宣称派发成功。') from None
                    observed('success', delivered=any(r['state']=='DELIVERED' and r['delivered'] for r in results))
                    counts={s:sum(r['state']==s for r in results) for s in ('PENDING','DELIVERED','NO_RECIPIENTS','FAILED')}
                    self.stdout.write(json.dumps({'processed':len(results),'outcomes':counts}))
                    if not options['watch']:
                        if counts['FAILED'] or counts['PENDING']:
                            raise CommandError('本轮存在失败或重试项，请核对派发状态。')
                        return
                    deadline = time.monotonic() + options['interval']
                    while not stopping:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        time.sleep(min(remaining, 0.2))
                observed('stopped')
                self.stdout.write('通知处理已停止；已提交状态保留，未提交事务由数据库回滚。')
        except BlockingIOError:
            raise CommandError('该实例已有通知心跳写入者；未启动第二个写入者。') from None
        except KeyboardInterrupt:
            self.stdout.write('通知处理已停止；已提交状态保留，未提交事务由数据库回滚。')
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
            close_old_connections()
