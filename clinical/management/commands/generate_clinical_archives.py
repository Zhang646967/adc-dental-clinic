import json
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from clinical.archive_generation import generate_batch

class Command(BaseCommand):
    help='生成已由独立医务审核通过的固定病历文件；不改变治疗、预约或资金。'
    def add_arguments(self,parser):parser.add_argument('--limit',type=int,default=2)
    def handle(self,*args,**options):
        if settings.ADC_READ_ONLY:raise CommandError('只读实例不能生成归档文件。')
        if not 1<=options['limit']<=10:raise CommandError('单次处理1至10项。')
        result=generate_batch(options['limit'])
        self.stdout.write(json.dumps(dict(processed=len(result),published=sum(r['published'] for r in result),
            failed=sum(r['state']=='FAILED' for r in result),stale=sum(r['state']=='STALE' for r in result))))
