"""Bounded LOCAL synthetic multi-clinic workload; never aim at a live Mac demo.

Twenty distinct normal HTTP sessions; 80% reads / 20% valid patient or note
writes. No retries. This does not benchmark all business mutations or a cloud
host. Credentials, individual samples and created IDs belong in private output.
The independent database oracle is required before calling a run accepted.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
from http.client import HTTPConnection
from http.cookies import SimpleCookie
import json,os,queue,re,secrets,stat,subprocess,sys,threading,time
from pathlib import Path
from urllib.parse import urlencode,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.g4_load import Forms,percentile
from scripts.g4_course_load import patient_submission

class Client:
    def __init__(self,port):self.port,self.cookies,self.connection=port,{},None
    def close(self):
        if self.connection:self.connection.close()
        self.connection=None
    def request(self,method,route,form=None):
        if method not in ('GET','POST') or not route.startswith('/') or route.startswith('//') or urlsplit(route).netloc:
            raise ValueError('Only local application routes are accepted')
        if self.connection is None:self.connection=HTTPConnection('127.0.0.1',self.port,timeout=8)
        origin='http://127.0.0.1:'+str(self.port)
        headers={'Cookie':'; '.join(k+'='+v for k,v in self.cookies.items())};body=None
        if method=='POST':
            body=urlencode(form or {});headers.update({'Content-Type':'application/x-www-form-urlencoded','Origin':origin,'Referer':origin+route})
        try:
            self.connection.request(method,route,body,headers);r=self.connection.getresponse();data=r.read(1024*1024+1)
            if len(data)>1024*1024:raise ValueError('Oversized response')
            for k,v in r.getheaders():
                if k.lower()=='set-cookie':
                    cookie=SimpleCookie(v)
                    for key in ('csrftoken','sessionid'):
                        if key in cookie:self.cookies[key]=cookie[key].value
            return r.status,r.getheader('Location'),data
        except Exception:self.close();raise
    def follow(self,method,route,form=None):
        for i in range(7):
            status,location,body=self.request(method,route,form)
            if status not in (301,302,303):return route,status,body
            target=urlsplit(location or '')
            if target.scheme or target.netloc or not target.path.startswith('/') or target.fragment:raise ValueError('Unexpected setup redirect')
            method,route,form='GET',location,None
        raise ValueError('Setup redirect loop')
    def form(self,route,required,action=None):
        status,_,body=self.request('GET',route)
        found=[f['inputs'] for f in Forms(body).forms if set(required)<=set(f['inputs']) and (action is None or f['inputs'].get('action')==action)]
        if status!=200 or len(found)!=1:raise ValueError('Expected one signed server form')
        return found[0]
    def login(self,actor):
        f=self.form('/accounts/login/',('username','password','csrfmiddlewaretoken'))
        route,status,body=self.follow('POST','/accounts/login/',f|{'username':actor['username'],'password':actor['password']})
        if actor.get('clinic'):
            fs=[f for f in Forms(body).forms if f['action']=='/workspace/clinic/activate/' and f['inputs'].get('clinic')==str(actor['clinic'])]
            if len(fs)!=1:raise ValueError('Expected signed current-clinic choice')
            route,status,body=self.follow('POST','/workspace/clinic/activate/',fs[0]['inputs'])
        if status!=200 or actor['username'].encode() not in body or 'sessionid' not in self.cookies:raise ValueError('Authenticated workspace not established')

READS={
 'FRONT_DESK':('/patients/','/visits/','/finance/receivables/','/frontdesk/'),
 'DENTIST':('/doctor/','/visits/','/patients/'),
 'MANAGER':('/equipment/maintenance/','/equipment/expenses/','/finance/daily-closes/','/manager/'),
 'FINANCE':('/finance/cash/','/finance/receivables/','/equipment/expenses/','/finance/daily-closes/'),
 'HQ':('/headquarters/','/finance/cash/','/finance/daily-closes/','/equipment/')}

def checked_target(root,project,port,docker):
    if not re.fullmatch('adc_rc1_[0-9a-f]{12}',project) or (root/'.rc/project.txt').read_text().strip()!=project:raise ValueError('Pin an existing explicit rehearsal project')
    if port in (18000,18020) or not 18040<=port<=18999:raise ValueError('Separate loopback rehearsal port required')
    d=[docker,'--context','desktop-linux']
    if not subprocess.check_output(d+['context','inspect','desktop-linux','--format','{{.Endpoints.docker.Host}}'],text=True).strip().startswith('unix://'):raise ValueError('Local Docker only')
    ids=subprocess.check_output(d+['ps','-q','--filter','label=com.docker.compose.project='+project],text=True).split()
    rows=json.loads(subprocess.check_output(d+['inspect',*ids]));services={r['Config']['Labels']['com.docker.compose.service']:r for r in rows}
    if not {'web','db','gateway','notification-worker'}<=set(services):raise ValueError('Complete marked rehearsal required')
    for name in ('web','notification-worker'):
        env=dict(v.split('=',1) for v in services[name]['Config']['Env'])
        if env.get('ADC_CAPACITY_REHEARSAL')!=project or env.get('ADC_RC_INSTANCE')!=project or env.get('AI_MODE')!='demo' or env.get('AI_API_KEY') or env.get('OPENAI_API_KEY'):raise ValueError('Explicit synthetic capacity marker and disabled external AI required')
    ports=services['gateway']['NetworkSettings']['Ports'].get('8080/tcp') or []
    if not any(p['HostIp']=='127.0.0.1' and int(p['HostPort'])==port for p in ports):raise ValueError('Port must belong to pinned loopback gateway')
    return {name:row['Id'] for name,row in services.items()}

def continuous_window(active_seconds,wall_seconds,max_offer_gap):
    # On macOS monotonic time can exclude system sleep. A successful request
    # count alone must never certify a continuous observation window.
    return abs(wall_seconds-active_seconds)<=2 and 0<=max_offer_gap<=5

def load(args):
    root=Path(args.root).resolve();private=root/'.rc/private';checked_target(root,args.project,args.port,args.docker)
    path=private/'capacity-actors.json'
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode)&0o077:raise ValueError('Actor manifest must be private')
    doc=json.loads(path.read_text());actors=[a for a in doc['actors'] if a['measured']]
    if doc['project']!=args.project or len(actors)!=20 or len({a['username'] for a in actors})!=20 or Counter(a['role'] for a in actors)!=Counter(FRONT_DESK=5,DENTIST=5,MANAGER=5,FINANCE=3,HQ=2):raise ValueError('Expected twenty distinct scoped synthetic accounts')
    if not re.fullmatch('[a-z0-9-]{1,48}',args.name) or not 10<=args.seconds<=1800 or args.rps not in (5,10):raise ValueError('Bounded explicit run required')
    output=private/(args.name+'.json')
    if output.exists():raise ValueError('Never overwrite retained evidence')
    run=secrets.token_hex(6);clients=[];fields={};versions={};queues=[queue.Queue(maxsize=2) for _ in actors];results=[];lock=threading.Lock();active=0;peak=0
    for i,a in enumerate(actors):
        c=Client(args.port);c.login(a);clients.append(c)
        if a['role']=='FRONT_DESK':fields[i]=c.form('/patients/new/',('workspace_token','csrfmiddlewaretoken','name'))
        if a['role']=='DENTIST':
            fields[i]=c.form('/care/'+str(a['visit'])+'/',('workspace_token','expected_version'),action='note');versions[i]=int(fields[i]['expected_version'])
    def worker(i):
        nonlocal active,peak
        c=clients[i];a=actors[i]
        while True:
            item=queues[i].get()
            if item is None:break
            seq,write,due=item;start=time.monotonic();route='';status=0;ok=False;created=None;error=None
            with lock:active+=1;peak=max(peak,active)
            try:
                if write:
                    if a['role']=='FRONT_DESK':
                        route='/patients/new/';form=patient_submission(fields[i],a['clinic'],'MC-'+run+'-'+str(seq))
                    else:
                        route='/care/'+str(a['visit'])+'/';form={k:fields[i][k] for k in ('csrfmiddlewaretoken','workspace_token')}|dict(action='note',expected_version=str(versions[i]),clinical_note='MC-'+run+'-'+str(seq),confirmed='on')
                    status,location,body=c.request('POST',route,form)
                    if a['role']=='FRONT_DESK':
                        ok=status==302 and bool(re.fullmatch(r'/patients/[0-9]+/',location or ''))
                        if ok:created=int(location.split('/')[2])
                    else:
                        ok=status==302 and location==route
                        if ok:versions[i]+=1
                else:
                    routes=READS[a['role']];route=routes[(seq//20)%len(routes)]
                    status,_,body=c.request('GET',route);ok=status==200 and a['username'].encode() in body
            except Exception as exc:error=type(exc).__name__
            finish=time.monotonic()
            with lock:
                active-=1;results.append(dict(seq=seq,actor=i,role=a['role'],clinic=a.get('clinic'),write=write,route=re.sub(r'/[0-9]+/','/:id/',route),status=status,ok=ok,seconds=finish-due,service_seconds=finish-start,queue_seconds=start-due,created_id=created,error=error))
        c.close()
    threads=[threading.Thread(target=worker,args=(i,)) for i in range(20)]
    for t in threads:t.start()
    writers=[i for pair in zip([i for i,a in enumerate(actors) if a['role']=='FRONT_DESK'],[i for i,a in enumerate(actors) if a['role']=='DENTIST']) for i in pair]
    wall_started=time.time();started=datetime.fromtimestamp(wall_started,timezone.utc).isoformat();base=time.monotonic();total=args.seconds*args.rps;dropped=[];last_offer=None;max_offer_gap=0
    for seq in range(total):
        due=base+(seq//20)*20/args.rps if args.arrival_mode=='waves' else base+seq/args.rps
        time.sleep(max(0,due-time.monotonic()))
        offered_at=time.time()
        if last_offer is not None:max_offer_gap=max(max_offer_gap,offered_at-last_offer)
        last_offer=offered_at
        if args.arrival_mode=='waves':
            i=seq%20;write=i in {writers[((seq//20)*4+k)%10] for k in range(4)}
        else:
            write=seq%5==4;i=writers[(seq//5)%10] if write else ((seq//5)*4+seq%5)%20
        try:queues[i].put_nowait((seq,write,due))
        except queue.Full:dropped.append(seq)
    time.sleep(max(0,base+args.seconds-time.monotonic()))
    for q in queues:q.put(None)
    for t in threads:t.join()
    elapsed=time.monotonic()-base;wall_elapsed=time.time()-wall_started
    def summary(rows):
        times=[r['seconds'] for r in rows]
        return dict(requests=len(rows),failures=sum(not r['ok'] for r in rows),p95_seconds=round(percentile(times,95),4) if times else None,max_seconds=round(max(times),4) if times else None)
    result=dict(run_id=run,project=args.project,scope='Local synthetic loopback HTTP; per-service resource caps are not an independent cloud host',started_utc=started,arrival_mode=args.arrival_mode,seconds=args.seconds,target_rps=args.rps,elapsed_seconds=round(elapsed,3),wall_elapsed_seconds=round(wall_elapsed,3),max_offer_gap_seconds=round(max_offer_gap,3),continuity_passed=continuous_window(elapsed,wall_elapsed,max_offer_gap),actual_rps=round(len(results)/elapsed,3),distinct_users=20,clinics=5,offered=total,dropped=dropped,max_in_flight=peak,summary=summary(results),reads=summary([r for r in results if not r['write']]),writes=summary([r for r in results if r['write']]),by_role={role:summary([r for r in results if r['role']==role]) for role in READS},by_clinic={str(cid):summary([r for r in results if r['clinic']==cid]) for cid in sorted({a['clinic'] for a in actors if a.get('clinic')})},initial_doctor_versions={str(i):int(fields[i]['expected_version']) for i in versions},final_doctor_versions=versions,samples=sorted(results,key=lambda r:r['seq']))
    result['http_passed']=not dropped and len(results)==total and result['summary']['failures']==0 and result['summary']['p95_seconds']<=5
    with output.open('x') as f:os.fchmod(f.fileno(),0o600);f.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','initial_doctor_versions','final_doctor_versions','run_id')}))
    return 0 if result['http_passed'] and result['continuity_passed'] else 1

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--project',required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--name',required=True);p.add_argument('--seconds',type=int,required=True);p.add_argument('--rps',type=int,default=5);p.add_argument('--arrival-mode',choices=('paced','waves'),default='paced');p.add_argument('--docker',default='/Applications/Docker.app/Contents/Resources/bin/docker');return load(p.parse_args())
if __name__=='__main__':raise SystemExit(main())
