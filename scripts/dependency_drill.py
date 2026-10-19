#!/usr/bin/env python3
"""Exercise four dependencies of an explicitly marked synthetic RC rehearsal.

Requires the five-clinic multiclinic_seed fixture. Never initialize, seed, restore,
reset observations or delete volumes here. Recovery is an explicit drill step.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adc_core.operations_store import PrivateStore
from scripts.host_events import Journal, SERVICES, SOURCE


class Drill:
    def __init__(self, root, output, docker, context):
        self.root = Path(root).resolve()
        self.output = Path(output).resolve()
        self.store = PrivateStore(self.output)
        self.marker = json.loads((self.root / '.rc/private/dependency-drill.json').read_text())
        self.project = (self.root / '.rc/project.txt').read_text().strip()
        if (self.marker['project'] != self.project or not re.fullmatch('adc_rc1_[a-f0-9]{12}', self.project)
                or not re.fullmatch('[a-f0-9]{40}', self.marker['source'])):
            raise ValueError('An identified synthetic rehearsal is required.')
        self.d = [docker, '--context', context]
        endpoint = self.run(self.d + ['context', 'inspect', context, '--format', '{{.Endpoints.docker.Host}}'])
        if not endpoint.startswith(b'unix://'):
            raise ValueError('Use an explicit local Docker endpoint.')
        self.dc = self.d + ['compose', '--env-file', str(self.root / '.rc/compose.env'),
            '--project-directory', str(self.root), '-p', self.project, '-f', str(self.root / 'compose.rc.yaml'),
            '-f', str(self.root / '.rc/private/rehearsal-compose.json'), '--profile', 'worker']
        for service in SERVICES:
            cid = self.service(service)
            fmt = '{{index .Config.Labels "com.docker.compose.project"}}|' + SOURCE
            project, source = self.run(self.d + ['inspect', '--format', fmt, cid]).decode().strip().split('|')
            if project != self.project or service in ('web', 'operations', 'notification-worker') and source != self.marker['source']:
                raise ValueError('Drill container identity differs.')
        # A copied directory/flag alone cannot mark the original Mac as disposable.
        self.py('print("true")')
        self.host_directory = self.output / 'host'
        host_store = PrivateStore(self.host_directory)
        host_store.write('target.json', dict(v=1, project=self.project, source=self.marker['source'], context=context, docker=docker))
        self.host = Journal(self.host_directory)
        self.report = dict(passed=False, started_at_utc=datetime.now(timezone.utc).isoformat(),
            application_source=self.marker['source'], checks=[], cases=[],
            scope='Four real dependencies in a fresh five-clinic synthetic rehearsal; original Mac excluded.')

    def run(self, command, *, data=None, allowed=(0,), timeout=45):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('COMPOSE_', 'DOCKER_'))}
        p = subprocess.run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=timeout)
        if p.returncode not in allowed:
            with (self.output / 'private-errors.log').open('ab') as log:
                os.fchmod(log.fileno(), 0o600)
                log.write(p.stdout + p.stderr)
            raise RuntimeError('Drill operation failed; inspect private diagnostics.')
        return p.stdout

    def service(self, name):
        ids = self.run(self.dc + ['ps', '-a', '-q', name]).decode().split()
        if len(ids) != 1:
            raise ValueError('A unique rehearsal service is required.')
        return ids[0]

    def py(self, code):
        guard = ('import os;assert os.environ.get("ADC_DEPENDENCY_DRILL")=='+repr(self.project)+
                 '\nassert os.environ.get("ADC_RC_INSTANCE")=='+repr(self.project)+'\nimport django;django.setup()\n')
        raw = self.run(self.d + ['exec', '-i', self.service('web'), 'python', '-'], data=(guard + code).encode())
        return json.loads(raw.decode().splitlines()[-1])

    def save(self):
        self.store.write('results.json', self.report)

    def check(self, name, passed, **facts):
        self.report['checks'].append(dict(name=name, passed=bool(passed), **facts))
        self.save()
        if not passed:
            raise AssertionError(name)
        print(json.dumps(dict(check=name, passed=True)), flush=True)

    def application_status(self):
        return json.loads(self.run(self.d + ['exec', self.service('web'), 'python', 'manage.py', 'operations_status'], allowed=(0,1,2,3)))

    def wait(self, predicate, limit=125):
        started = time.monotonic()
        while True:
            self.host.collect()
            state = self.application_status()
            if predicate(state):
                return state, round(time.monotonic() - started, 3)
            if time.monotonic() - started > limit:
                raise RuntimeError('Expected condition did not appear; retain the failed drill.')
            time.sleep(2)

    def protect(self):
        return self.py('''import hashlib,json
from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder
from adc_core.snapshots import reporting_snapshot
class Encoder(DjangoJSONEncoder):
 def default(self,v):
  if isinstance(v,(bytes,bytearray,memoryview)):return {'sha256':hashlib.sha256(bytes(v)).hexdigest()}
  return super().default(v)
facts={}
with reporting_snapshot():
 for m in apps.get_models(include_auto_created=True):
  if m._meta.app_label not in ('patients','care','finance','equipment','accounts','registry','portal') and m._meta.label!='scheduling.Visit':continue
  if m._meta.label=='care.AuditEvent':continue
  fields=[f.attname for f in m._meta.concrete_fields if f.name!='last_login']
  rows=list(m.objects.order_by('pk').values(*fields))
  facts[m._meta.label]={'rows':len(rows),'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,cls=Encoder).encode()).hexdigest()}
print(json.dumps(facts))''')

    def ledger(self):
        return self.py('''import json
from decimal import Decimal
from finance.cash_models import CashEntry
totals={};counts={}
for r in CashEntry.objects.filter(state='POSTED').values('kind','amount'):
 totals[r['kind']]=totals.get(r['kind'],Decimal('0'))+r['amount'];counts[r['kind']]=counts.get(r['kind'],0)+1
print(json.dumps({'posted_counts':counts,'posted_totals':{k:str(v) for k,v in totals.items()}}))''')

    def task(self, number):
        return self.py('''from datetime import timedelta
from django.utils import timezone
from accounts.models import UserAccount
from registry.models import Dentist
from workspaces.models import WorkspaceContext
from scheduling.services import create_slot
from scheduling.intake_services import inspect_intake,prepare_intake,confirm_intake
from coordination.task_services import inspect_task,prepare_task,confirm_task
from coordination.task_rules import ACTION_REASONS
from notifications.models import NotificationOutbox
u=UserAccount.objects.get(username='capacity_manager_0')
u._adc_workspace=WorkspaceContext.objects.filter(user=u,role='MANAGER').first()
start=(timezone.now()+timedelta(days='''+str(int(self.marker.get('fixture_day',20)))+''')).replace(hour=8,minute=0,second=0,microsecond=0)+timedelta(hours='''+str(number*2)+''')
slot=create_slot(actor=u,clinic_id=u._adc_workspace.clinic_id,dentist_id=Dentist.objects.get(employee_no='CAP-D0-1').pk,start=start,end=start+timedelta(hours=1))
_,token=inspect_intake(actor=u,slot_id=slot.pk)
p=prepare_intake(actor=u,slot_id=slot.pk,state_token=token,action='pause',reason='COORDINATION')
confirm_intake(actor=u,slot_id=slot.pk,proposal_token=p['proposal_token'],confirmed=True)
_,token=inspect_task(actor=u,slot_id=slot.pk)
p=prepare_task(actor=u,slot_id=slot.pk,task_id=None,state_token=token,action='open',reason=ACTION_REASONS['open'][0],purpose='REPLACE')
r=confirm_task(actor=u,slot_id=slot.pk,task_id=p['task_id'],proposal_token=p['proposal_token'],confirmed=True)
e=NotificationOutbox.objects.get(task_id=r.task_id)
print(__import__('json').dumps({'event':e.pk,'task':r.task_id,'targets':len(e.recipients),'revision':e.task.revision}))''')

    def event(self, pk):
        return self.py('''import json
from notifications.models import NotificationOutbox,InboxMessage
from coordination.models import CoordinationTask
e=NotificationOutbox.objects.get(pk='''+str(pk)+''')
print(json.dumps({'state':e.state,'attempts':e.attempts,'messages':InboxMessage.objects.filter(event=e).count(),'task_revision':CoordinationTask.objects.get(pk=e.task_id).revision}))''')

    def delivery(self, task):
        self.wait(lambda _: self.event(task['event'])['state']=='DELIVERED', limit=40)
        facts = self.event(task['event'])
        self.check('notice_delivered_once_without_task_replay', facts['messages']==task['targets'] and facts['attempts']==1 and facts['task_revision']==task['revision'])

    def change(self, action, service):
        self.run(self.dc + [action, service])
        self.host.collect()

    def finish_case(self, name, before, ledger, started):
        self.wait(lambda s:s['state']=='HEALTHY')
        for _ in range(3):
            time.sleep(1)
            self.host.collect()
        for incident in self.host.status()['active_incidents']:
            self.host.handle(incident['id'], 'course_operator', 'inspect_dependencies')
            self.host.handle(incident['id'], 'course_operator', 'restart_service')
            self.host.handle(incident['id'], 'course_operator', 'verify_business_facts')
            self.host.handle(incident['id'], 'course_operator', close=True)
        self.check(name+'_business_facts_unchanged', self.protect()==before, protected_tables=len(before))
        self.check(name+'_independent_ledger_unchanged', self.ledger()==ledger)
        self.check(name+'_host_recovered_with_history', self.host.status()['state']=='HEALTHY')
        self.report['cases'].append(dict(name=name, duration_seconds=round(time.monotonic()-started,3), responsibility='course_operator', recovered=True))
        self.save()

    def execute(self):
        started=self.run(self.d+['inspect','--format','{{.State.StartedAt}}',self.service('notification-worker')]).decode().strip()
        worker_started=datetime.fromisoformat(started.replace('Z','+00:00')).timestamp()
        def ready(state):
            if state['state']!='HEALTHY':return False
            return self.py('''from adc_core.operations_store import PrivateStore
import json
s=PrivateStore('/app/operations/monitor').read('monitor.json');w=s['sample']['worker']
print(json.dumps(bool(w and w['last_success'] and w['last_success']['utc']>'''+repr(worker_started)+''')))''')
        self.wait(ready)
        self.check('five_clinics_and_nonempty_finance_fixture', self.py('from registry.models import Clinic\nfrom finance.cash_models import CashEntry\nimport json\nprint(json.dumps(Clinic.objects.count()==5 and CashEntry.objects.filter(state="POSTED").count()==500))'))
        for name in ('worker','gateway','observer','database'):
            before, ledger, started = self.protect(), self.ledger(), time.monotonic()
            service = dict(worker='notification-worker', gateway='gateway', observer='operations', database='db')[name]
            self.change('stop', service)
            self.check(name+'_host_identifies_stopped_service', self.host.status()['conditions'][service]['state']=='CRITICAL')
            if name == 'worker':
                task=self.task(0)
                state,seconds=self.wait(lambda s:s.get('conditions',{}).get('worker',{}).get('state')=='CRITICAL',limit=45)
                self.check('stopped_worker_leaves_committed_notice_pending',self.event(task['event'])==dict(state='PENDING',attempts=0,messages=0,task_revision=task['revision']),detected_seconds=seconds)
            elif name == 'gateway':
                try:
                    urlopen('http://127.0.0.1:'+str(self.marker['port'])+'/health/',timeout=2)
                    reachable=True
                except (OSError,URLError):reachable=False
                self.check('gateway_outage_blocks_browser_entry',not reachable)
                task=self.task(1);self.delivery(task)
                self.check('gateway_outage_does_not_stop_internal_work',self.application_status()['conditions']['web']['state']=='HEALTHY')
            elif name == 'observer':
                task=self.task(2);self.delivery(task)
                old=self.application_status().get('observed_at')
                state,seconds=self.wait(lambda s:s.get('reason')=='OBSERVER_UNAVAILABLE',limit=110)
                self.check('independent_reader_detects_real_observer_expiry',state['code']==3,seconds=seconds)
                self.check('observer_outage_keeps_business_http_ready',urlopen('http://127.0.0.1:'+str(self.marker['port'])+'/health/',timeout=3).status==200)
            else:
                state,seconds=self.wait(lambda s:s.get('conditions',{}).get('database',{}).get('state')=='CRITICAL',limit=85)
                self.check('database_outage_has_unknown_backlog_not_zero',state['aggregates'] is None and state['conditions']['backlog']['state']=='UNKNOWN',seconds=seconds)
                try:
                    urlopen('http://127.0.0.1:'+str(self.marker['port'])+'/health/',timeout=5)
                    safe=False
                except HTTPError as error:
                    safe=error.code==503 and len(error.headers.get('X-Request-ID',''))==32 and json.loads(error.read())=={'status':'not_ready'}
                self.check('database_outage_returns_safe_health_503',safe)
            self.change('start',service)
            if name=='database':
                self.run(self.dc+['exec','-T','db','pg_isready','-U','adc_rc_owner','-d','adc_rc_demo'])
                self.change('start','notification-worker')
            if name=='worker':self.delivery(task)
            self.finish_case(name,before,ledger,started)
        self.check('no_duplicate_inbox_business_effects',self.py('''from django.db import connection
import json
with connection.cursor() as c:
 c.execute('SELECT count(*) FROM (SELECT event_id,grant_id FROM adc_inbox_message GROUP BY event_id,grant_id HAVING count(*)>1) d')
 print(json.dumps(c.fetchone()[0]==0))'''))
        self.report.update(passed=True,completed_at_utc=datetime.now(timezone.utc).isoformat(),ledger=self.ledger())
        self.save()
        print(json.dumps(dict(passed=True,cases=len(self.report['cases']),checks=len(self.report['checks']))))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--output',required=True)
    p.add_argument('--docker',default='docker');p.add_argument('--context',required=True)
    p.add_argument('--confirm-synthetic-faults',action='store_true',required=True)
    args=p.parse_args()
    Drill(args.root,args.output,args.docker,args.context).execute()


if __name__=='__main__':main()
