"""P1 exact-image, loopback-only twenty-clinic workload. Private credentials only.

80% public/authorized reads, 20% actual clinic-draft saves. It creates neither
appointments nor payments. Run the five-clinic clinical baseline separately.
"""
import argparse,json,os,queue,re,secrets,stat,subprocess,threading,time
from collections import Counter
from datetime import datetime,timezone
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode,urlsplit
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.g4_load import Forms,percentile


class Client:
    def __init__(self,port):self.port=port;self.cookies={};self.connection=None
    def close(self):
        if self.connection:self.connection.close()
        self.connection=None
    def request(self,method,route,fields=None,*,json_response=False):
        if not route.startswith('/') or route.startswith('//') or urlsplit(route).netloc:raise ValueError('Local routes only')
        if self.connection is None:self.connection=HTTPConnection('127.0.0.1',self.port,timeout=12)
        origin='http://127.0.0.1:'+str(self.port)
        headers={'Cookie':'; '.join(k+'='+v for k,v in self.cookies.items())};body=None
        if method=='POST':
            body=urlencode(fields or {},doseq=True)
            headers.update({'Content-Type':'application/x-www-form-urlencoded','Origin':origin,'Referer':origin+route})
        if json_response:headers['Accept']='application/json'
        try:
            self.connection.request(method,route,body,headers);reply=self.connection.getresponse();data=reply.read(2*1024*1024+1)
            if len(data)>2*1024*1024:raise ValueError('Oversized response')
            for key,value in reply.getheaders():
                if key.lower()=='set-cookie':
                    cookie=SimpleCookie(value)
                    for name in ('csrftoken','sessionid'):
                        if name in cookie:self.cookies[name]=cookie[name].value
            return reply.status,reply.getheader('Location'),data
        except Exception:self.close();raise
    def follow(self,method,route,fields=None):
        for _ in range(8):
            status,target,body=self.request(method,route,fields)
            if status not in (301,302,303):return status,body
            if not target or urlsplit(target).netloc or not target.startswith('/'):raise ValueError('External redirect refused')
            method,route,fields='GET',target,None
        raise ValueError('Redirect loop')
    def fields(self,route,required):
        status,_,body=self.request('GET',route)
        forms=[x for x in Forms(body).forms if set(required)<=set(x['inputs'])]
        if status!=200 or len(forms)!=1:raise ValueError('Expected authorized form')
        return forms[0]['inputs']
    def login(self,actor):
        fields=self.fields('/accounts/login/',('csrfmiddlewaretoken','username','password'))
        status,body=self.follow('POST','/accounts/login/',fields|dict(username=actor['username'],password=actor['password']))
        if status!=200:raise ValueError('Synthetic manager login failed')
        return self.fields('/profiles/clinic/edit/',('csrfmiddlewaretoken','workspace_token','draft_token'))


def check_target(docker,project,port,source,database):
    if port in (18000,18191) or not 1024<=port<=65535 or not re.fullmatch('[a-f0-9]{40}',source):
        raise ValueError('Explicit isolated port and exact source required')
    d=[docker,'--context','desktop-linux']
    ids=subprocess.check_output(d+['ps','-q','--filter','label=com.docker.compose.project='+project],text=True).split()
    rows=json.loads(subprocess.check_output(d+['inspect',*ids]));services={r['Config']['Labels']['com.docker.compose.service']:r for r in rows}
    if not {'web','gateway','notification-worker'}<=set(services):raise ValueError('Incomplete private rehearsal')
    for name in ('web','notification-worker'):
        row=services[name];env=dict(x.split('=',1) for x in row['Config']['Env'])
        if (env.get('ADC_CAPACITY_REHEARSAL')!=project or env.get('ADC_RC_INSTANCE')!=project or
            env.get('ADC_SOURCE_COMMIT')!=source or env.get('AI_MODE')!='demo' or env.get('AI_API_KEY') or env.get('OPENAI_API_KEY') or
            any(m['Destination']=='/app' for m in row['Mounts'])):raise ValueError('Pinned image without source overlay required')
    ports=services['gateway']['NetworkSettings']['Ports'].get('8080/tcp') or []
    if not any(p['HostIp']=='127.0.0.1' and int(p['HostPort'])==port for p in ports):raise ValueError('Unexpected gateway origin')
    db=json.loads(subprocess.check_output(d+['inspect',database]))[0]
    if db['Name']!='/adc_p1_verify_db' or any(db['NetworkSettings']['Ports'].values()):raise ValueError('Explicit unexposed P1 verification database required')
    return {n:r['Id'] for n,r in services.items()}|{'db':db['Id']}


def write_request(sequence):return (sequence//20+sequence%20)%5==4


def summary(rows):
    values=[r['seconds'] for r in rows]
    return dict(requests=len(rows),failures=sum(not r['ok'] for r in rows),
        p95_seconds=round(percentile(values,95),4) if values else None,
        max_seconds=round(max(values),4) if values else None)


def load(args):
    path=Path(args.manifest)
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode)&0o077:raise ValueError('Private manifest required')
    data=json.loads(path.read_text());actors=data['actors']
    if len(actors)!=20 or len({a['username'] for a in actors})!=20 or len({a['clinic'] for a in actors})!=20:
        raise ValueError('Twenty distinct current-clinic managers required')
    if args.seconds not in (20,60,1800):raise ValueError('Bounded rehearsal or full 30-minute run required')
    if Path(args.output).exists():raise ValueError('Never overwrite load evidence')
    services=check_target(args.docker,data['project'],data['port'],data['source'],data['database_container'])
    clients=[];forms=[]
    for actor in actors:
        client=Client(data['port']);forms.append(client.login(actor));clients.append(client)
    run=secrets.token_hex(6);queues=[queue.Queue(maxsize=1) for _ in actors];results=[];lock=threading.Lock()
    active=peak=0;normal_reads=('/profiles/','/operations/management/','/profiles/clinic/edit/','/clinics/')
    def worker(index):
        nonlocal active,peak
        actor=actors[index];client=clients[index]
        while True:
            item=queues[index].get()
            if item is None:queues[index].task_done();break
            seq,write=item;started=time.monotonic();row={'seq':seq,'actor':index,'clinic':actor['clinic'],'write':write}
            with lock:active+=1;peak=max(peak,active)
            try:
                if write:
                    body={**actor['fields'],**forms[index],'action':'SAVE_DRAFT'}
                    body['biography']=actor['fields']['biography']+'\nP1_CAPACITY_'+run+'_'+str(seq)
                    status,_,raw=client.request('POST','/profiles/clinic/edit/',body,json_response=True)
                    answer=json.loads(raw)
                    row['ok']=status==200 and answer.get('ok') is True and answer.get('replay') is False
                    if row['ok']:forms[index]['draft_token']=answer['draft_token'];row['revision']=answer['revision']
                    row['route']='clinic_draft_save'
                else:
                    route=normal_reads[(seq//20)%4]
                    if route=='/operations/management/':route+='?period='+data['period']+'&clinic='+str(actor['clinic'])
                    elif route=='/clinics/':route+=str(actor['clinic'])+'/'
                    status,_,raw=client.request('GET',route)
                    row['ok']=status==200;row['route']=route.split('?')[0]
                row['status']=status
            except Exception as exc:row.update(ok=False,error=type(exc).__name__)
            finally:
                row['seconds']=time.monotonic()-started
                with lock:active-=1;results.append(row)
                queues[index].task_done()
        client.close()
    threads=[threading.Thread(target=worker,args=(i,),daemon=True) for i in range(20)]
    for thread in threads:thread.start()
    guard=None
    if sys.platform=='darwin':guard=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())])
    start_utc=datetime.now(timezone.utc).isoformat();wall=time.time();base=time.monotonic();last_offer=base;max_gap=0;dropped=[]
    total=args.seconds*5
    for seq in range(total):
        due=base+seq/5
        delay=due-time.monotonic()
        if delay>0:time.sleep(delay)
        now=time.monotonic();max_gap=max(max_gap,now-last_offer);last_offer=now
        index=seq%20;write=write_request(seq)
        try:queues[index].put_nowait((seq,write))
        except queue.Full:dropped.append(seq)
        if seq and seq%300==0:
            progress={'completed':len(results),'target':total,'elapsed_seconds':round(now-base,1),'failures':sum(not r['ok'] for r in results),'dropped':len(dropped)}
            Path(args.output+'.progress').write_text(json.dumps(progress)+'\n');print(json.dumps(progress),flush=True)
    for q in queues:q.join()
    delay=base+args.seconds-time.monotonic()
    if delay>0:time.sleep(delay)
    elapsed=time.monotonic()-base;wall_elapsed=time.time()-wall
    for q in queues:q.put(None)
    for t in threads:t.join(timeout=15)
    if guard:guard.terminate()
    d=[args.docker,'--context','desktop-linux'];meta=json.loads(subprocess.check_output(d+['inspect',*services.values()]))
    finish_utc=datetime.now(timezone.utc).isoformat()
    event_args=['events','--since',start_utc,'--until',finish_utc,'--filter','event=oom','--format','{{json .}}']
    for container in services.values():event_args+=['--filter','container='+container]
    oom_events=subprocess.check_output(d+event_args,text=True,timeout=30).strip().splitlines()
    oom=bool(oom_events) or any(m['State']['OOMKilled'] for m in meta)
    result=dict(source=data['source'],project=data['project'],run=run,started_utc=start_utc,seconds=args.seconds,
        elapsed_seconds=round(elapsed,3),wall_elapsed_seconds=round(wall_elapsed,3),max_offer_gap_seconds=round(max_gap,3),
        target_rps=5,actual_rps=round(len(results)/elapsed,3),users=20,clinics=20,offered=total,dropped=dropped,
        max_in_flight=peak,summary=summary(results),reads=summary([r for r in results if not r['write']]),
        writes=summary([r for r in results if r['write']]),oom=oom,oom_events=len(oom_events),
        services_running=all(m['State']['Running'] for m in meta),
        resource_limits={m['Name'].lstrip('/'):dict(memory_bytes=m['HostConfig']['Memory'],nano_cpus=m['HostConfig']['NanoCpus']) for m in meta},
        samples=sorted(results,key=lambda r:r['seq']))
    result['http_passed']=bool(not dropped and not oom and result['services_running'] and result['summary']['failures']==0 and
        result['summary']['p95_seconds']<5 and abs(wall_elapsed-elapsed)<=2 and max_gap<=5 and
        result['reads']['requests']==total*4//5 and result['writes']['requests']==total//5)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');Path(args.output).chmod(0o600)
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','run')}),flush=True)
    return 0 if result['http_passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True)
    p.add_argument('--seconds',type=int,default=1800);p.add_argument('--docker',default='/Applications/Docker.app/Contents/Resources/bin/docker')
    raise SystemExit(load(p.parse_args()))
