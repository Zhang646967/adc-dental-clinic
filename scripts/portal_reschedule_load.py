"""B1.4 isolated patient workload: 80% GET, 20% valid preview/confirm POST.

Twenty distinct patients in five synthetic clinics. A preview and a confirmation
are counted as separate HTTP requests; only confirmations create replacements.
Private rows and an independent database oracle are required for acceptance.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
from html.parser import HTMLParser
import json,os,queue,re,secrets,stat,sys,threading,time
from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qs,urldefrag
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.multiclinic_load import Client,checked_target,continuous_window
from scripts.g4_load import Forms,percentile

class Links(HTMLParser):
    def __init__(self,body):
        super().__init__();self.links=[];self.feed(body.decode())
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            href=dict(attrs).get('href','')
            if 'start=' in href:self.links.append(urldefrag(href)[0])

def one_form(body,required):
    rows=[f['inputs'] for f in Forms(body).forms if set(required)<=set(f['inputs'])]
    if len(rows)!=1:raise ValueError('Expected one current signed form')
    return rows[0]

def load(args):
    root=Path(args.root).resolve();private=root/'.rc/private'
    checked_target(root,args.project,args.port,args.docker)
    path=private/'portal-reschedule-actors.json'
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode)&0o077:raise ValueError('Private actor file required')
    fixture=json.loads(path.read_text());actors=fixture['actors']
    if fixture['project']!=args.project or len(actors)!=20 or len({a['username'] for a in actors})!=20 or any(a['role']!='PATIENT' for a in actors) or sorted(Counter(a['clinic'] for a in actors).values())!=[4]*5:raise ValueError('Expected twenty patients across five clinics')
    if not 40<=args.seconds<=1800 or args.seconds%40 or args.rps!=5 or not re.fullmatch('[a-z0-9-]{1,48}',args.name):raise ValueError('Bounded explicit workload required')
    output=private/(args.name+'.json')
    if output.exists():raise ValueError('Retain earlier evidence')
    run=secrets.token_hex(6);states=[];clients=[];results=[];queues=[queue.Queue(maxsize=2) for _ in actors];lock=threading.Lock();active=0;peak=0
    doctors={c['clinic']:c['doctor_id'] for c in fixture['cases']}
    def source_route(i):return '/portal/visits/'+str(states[i]['visit'])+'/reschedule/'
    def search_route(i):
        a=actors[i];s=states[i];target=1-s['day']
        return source_route(i)+'?'+urlencode({'day':a['starts'][target][:10],'dentist':doctors[a['clinic']]})
    def select_url(i,body):
        wanted=datetime.fromisoformat(actors[i]['starts'][1-states[i]['day']]).timestamp()
        links=[p for p in Links(body).links if datetime.fromisoformat(parse_qs(urlsplit(p).query)['start'][0]).timestamp()==wanted]
        if len(links)!=1:raise ValueError('Assigned free destination is no longer offered')
        return links[0]
    for i,a in enumerate(actors):
        c=Client(args.port);c.login(a|{'clinic':None});clients.append(c)
        states.append(dict(visit=a['visit'],day=a.get('current_day',0),phase='preview',form=None,choice=None))
        status,_,body=c.request('GET',search_route(i));assert status==200
        choice=select_url(i,body);status,_,body=c.request('GET',choice);assert status==200
        states[i]['form']=one_form(body,('expected_version','slot_id','workspace_token'))
    def worker(i):
        nonlocal active,peak
        c=clients[i];a=actors[i];s=states[i]
        while True:
            job=queues[i].get()
            if job is None:break
            seq,write,due=job;start=time.monotonic()
            with lock:active+=1;peak=max(peak,active)
            ok=False;status=None;error=None;created=None;original=None;route='';phase=s['phase']
            try:
                if write:
                    if s['form'] is None:raise ValueError('Select the destination before a legal POST')
                    route=source_route(i)
                    fields=s['form']|({'reason':'B14-'+run+'-'+str(seq),'action':'preview'} if phase=='preview' else {'action':'confirm','confirmed':'on'})
                    status,location,body=c.request('POST',route,fields)
                    if phase=='preview':
                        ok=status==200
                        if ok:s['form']=one_form(body,('proposal_token','confirmed','workspace_token'));s['phase']='confirm'
                    else:
                        ok=status==302 and bool(re.fullmatch('/portal/visits/[0-9]+/',location or ''))
                        if ok:
                            original=s['visit'];created=int(location.split('/')[3]);s.update(visit=created,day=1-s['day'],phase='preview',form=None,choice=None)
                else:
                    needs=s['phase']=='preview' and s['form'] is None
                    if needs:route=s['choice'] or search_route(i)
                    else:route=['/portal/','/portal/appointments/','/portal/visits/'+str(s['visit'])+'/',search_route(i),'/waitlist/','/portal/help/?visit='+str(s['visit'])][(seq//20)%6]
                    status,_,body=c.request('GET',route);ok=status==200 and a['username'].encode() in body
                    if needs and ok:
                        if s['choice']:s['form']=one_form(body,('expected_version','slot_id','workspace_token'))
                        else:s['choice']=select_url(i,body)
            except Exception as exc:error=type(exc).__name__;ok=False
            finish=time.monotonic()
            with lock:
                active-=1;results.append(dict(seq=seq,actor=i,clinic=a['clinic'],write=write,phase=phase if write else None,
                    method='POST' if write else 'GET',route=re.sub('/[0-9]+/','/:id/',route.split('?')[0]),status=status,ok=ok,
                    seconds=finish-due,service_seconds=finish-start,queue_seconds=start-due,original_id=original,created_id=created,error=error))
        c.close()
    threads=[threading.Thread(target=worker,args=(i,)) for i in range(20)]
    for t in threads:t.start()
    wall=time.time();started=datetime.fromtimestamp(wall,timezone.utc).isoformat();base=time.monotonic();last=None;max_gap=0;dropped=[]
    total=args.seconds*5
    for seq in range(total):
        wave=seq//20;due=base+wave*4;time.sleep(max(0,due-time.monotonic()));now=time.time()
        if last is not None:max_gap=max(max_gap,now-last)
        last=now;i=seq%20;write=i in {(wave*4+k)%20 for k in range(4)}
        try:queues[i].put_nowait((seq,write,due))
        except queue.Full:dropped.append(seq)
    time.sleep(max(0,base+args.seconds-time.monotonic()))
    for q in queues:q.put(None)
    for t in threads:t.join()
    elapsed=time.monotonic()-base;wall_elapsed=time.time()-wall
    def summary(rows):
        values=[x['seconds'] for x in rows]
        return dict(requests=len(rows),failures=sum(not x['ok'] for x in rows),p95_seconds=round(percentile(values,95),4) if values else None,max_seconds=round(max(values),4) if values else None)
    result=dict(project=args.project,scope='Five-clinic patient HTTP workload; distinct from earlier staff workload. Preview and confirmation are separate POST requests.',run_id=run,started_utc=started,seconds=args.seconds,target_rps=5,arrival_mode='waves',elapsed_seconds=round(elapsed,3),wall_elapsed_seconds=round(wall_elapsed,3),max_offer_gap_seconds=round(max_gap,3),continuity_passed=continuous_window(elapsed,wall_elapsed,max_gap),actual_rps=round(len(results)/elapsed,3),distinct_users=20,clinics=5,offered=total,dropped=dropped,max_in_flight=peak,summary=summary(results),reads=summary([x for x in results if not x['write']]),writes=summary([x for x in results if x['write']]),previews=summary([x for x in results if x['write'] and x['phase']=='preview']),confirmations=summary([x for x in results if x['write'] and x['phase']=='confirm']),committed_reschedules=sum(x['ok'] and x['created_id'] is not None for x in results),by_clinic={str(k):summary([x for x in results if x['clinic']==k]) for k in sorted(doctors)},final_states=[{k:v for k,v in s.items() if k not in ('form','choice')} for s in states],samples=sorted(results,key=lambda x:x['seq']))
    result['http_passed']=not dropped and len(results)==total and not result['summary']['failures'] and result['summary']['p95_seconds']<5 and result['committed_reschedules']==total//10 and all(s['phase']=='preview' for s in states)
    with output.open('x') as f:os.fchmod(f.fileno(),0o600);f.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('run_id','samples','final_states')}))
    return 0 if result['http_passed'] and result['continuity_passed'] else 1

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--project',required=True);p.add_argument('--port',required=True,type=int);p.add_argument('--name',required=True);p.add_argument('--seconds',required=True,type=int);p.add_argument('--rps',default=5,type=int);p.add_argument('--docker',default='/Applications/Docker.app/Contents/Resources/bin/docker');return load(p.parse_args())
if __name__=='__main__':raise SystemExit(main())
