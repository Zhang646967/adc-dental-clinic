"""Local inbox-only worker. Log aggregate status, never raw DB errors or targets."""
import json
import time
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections
from notifications.dispatcher import dispatch_batch
from notifications.rules import bounded_batch

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
        try:
            while True:
                close_old_connections()
                try:
                    results=dispatch_batch(options['batch_size'])
                except (DatabaseError,PermissionDenied,RuntimeError):
                    raise CommandError('通知处理停止：数据库或运行策略不可用；没有宣称派发成功。') from None
                counts={s:sum(r['state']==s for r in results) for s in ('PENDING','DELIVERED','NO_RECIPIENTS','FAILED')}
                self.stdout.write(json.dumps({'processed':len(results),'outcomes':counts}))
                if not options['watch']:
                    if counts['FAILED'] or counts['PENDING']:
                        raise CommandError('本轮存在失败或重试项，请核对派发状态。')
                    return
                time.sleep(options['interval'])
        except KeyboardInterrupt:
            self.stdout.write('通知处理已停止；已提交状态保留，未提交事务由数据库回滚。')
        finally:
            close_old_connections()
