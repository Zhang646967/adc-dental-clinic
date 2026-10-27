"""P1.5 exact-image patient workload; twenty synthetic self accounts/clinics.

Each normal request is counted once. Writes append actual patient self-history,
with server revisions and operation IDs; no booking, treatment or cash is faked.
"""
import argparse,json,os,queue,secrets,stat,subprocess,threading,time
from datetime import datetime,timezone
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.profile_load import Client,check_target,summary,write_request

class PatientClient(Client):
    def __init__(self,port):super().__init__(port);self.session={}
    def api(self,path,method='GET',fields=None):
        body=dict(fields or {})
        if method=='POST':body.update(csrfmiddlewaretoken=self.session.get('csrf_token',''),workspace_token=self.session.get('workspace_token',''))
        headers={'X-CSRFToken':self.session.get('csrf_token',''),'X-ADC-Workspace':self.session.get('workspace_token','')} if method=='POST' else None
        status,_,raw=self.request(method,'/api/mini/v1/'+path,body if method=='POST' else None,json_response=True,extra_headers=headers)
        data=json.loads(raw)
        if status!=200 or data.get('ok') is not True:raise ValueError('Unexpected API status '+str(status)+' '+str(data.get('code','')))
        result=data['data']
        if result.get('csrf_token'):self.session=result
        return result
    def patient_login(self,actor):
        self.api('session/');self.api('login/','POST',dict(username=actor['username'],password=actor['password']))
        if not self.session.get('authenticated') or self.session.get('delegated'):raise ValueError('Synthetic self context required')
        return self.api('history/')

def load(args):
    manifest=Path(args.manifest)
    if manifest.is_symlink() or stat.S_IMODE(manifest.stat().st_mode)&0o077:raise ValueError('Private manifest required')
    data=json.loads(manifest.read_text());actors=data['actors']
    if len(actors)!=20 or len({a['username'] for a in actors})!=20 or len({a['clinic'] for a in actors})!=20:raise ValueError('Twenty distinct synthetic patients and clinics required')
    if args.seconds not in (20,60,1800) or Path(args.output).exists():raise ValueError('Bounded new evidence required')
    services=check_target(args.docker,data['project'],data['port'],data['source'],data['database_container'])
    clients=[PatientClient(data['port']) for _ in actors];states=[c.patient_login(a) for c,a in zip(clients,actors)]
    queues=[queue.Queue(maxsize=1) for _ in actors];results=[];lock=threading.Lock();peak=active=0
    run=secrets.token_hex(6)
    def worker(index):
        nonlocal active,peak
        client=clients[index];state=states[index];actor=actors[index]
        while True:
            item=queues[index].get()
            if item is None:queues[index].task_done();break
            seq,write,due=item;start=time.monotonic();row=dict(seq=seq,actor=index,clinic=actor['clinic'],write=write)
            with lock:active+=1;peak=max(peak,active)
            try:
                if write:
                    fields=dict(expected_revision=state['current_revision'],operation_id=state['operation_id'],medical_status='UNKNOWN',medical_history='',
                        medication_status='UNKNOWN',medications='',allergy_status='UNKNOWN',reported_allergies='',confirmed='on')
                    answer=client.api('history/submit/','POST',fields)
                    row.update(ok=not answer['replayed'] and answer['current_revision']==state['current_revision']+1,
                        revision=answer['current_revision'],record_id=answer['row']['id'],route='history/submit/')
                    state=answer
                else:
                    paths=('discovery/index/','discovery/services/?clinic='+str(actor['clinic']),
                        'discovery/dentists/?clinic='+str(actor['clinic']),'overview/')
                    path=paths[(seq//20)%4];answer=client.api(path);row.update(ok=True,route=path.split('?')[0])
            except Exception as exc:row.update(ok=False,error=type(exc).__name__)
            finally:
                end=time.monotonic();row.update(seconds=end-due,service_seconds=end-start,queue_seconds=start-due)
                with lock:active-=1;results.append(row)
                queues[index].task_done()
        client.close()
    threads=[threading.Thread(target=worker,args=(i,),daemon=True) for i in range(20)]
    for t in threads:t.start()
    guard=subprocess.Popen(['/usr/bin/caffeinate','-i']) if sys.platform=='darwin' else None
    started=datetime.now(timezone.utc).isoformat();base=time.monotonic();wall=time.time();total=args.seconds*5;dropped=[]
    # Twenty simultaneous arrivals every four seconds; latency includes queueing.
    for seq in range(total):
        due=base+(seq//20)*4;delay=due-time.monotonic()
        if delay>0:time.sleep(delay)
        try:queues[seq%20].put_nowait((seq,write_request(seq),due))
        except queue.Full:dropped.append(seq)
        if seq and seq%300==0:
            progress=dict(completed=len(results),target=total,failures=sum(not r['ok'] for r in results),dropped=len(dropped))
            Path(args.output+'.progress').write_text(json.dumps(progress)+'\n');print(json.dumps(progress),flush=True)
    for q in queues:q.join()
    delay=base+args.seconds-time.monotonic()
    if delay>0:time.sleep(delay)
    elapsed=time.monotonic()-base;wall_elapsed=time.time()-wall
    for q in queues:q.put(None)
    for t in threads:t.join(timeout=15)
    if guard:guard.terminate()
    d=[args.docker,'--context','desktop-linux'];meta=json.loads(subprocess.check_output(d+['inspect',*services.values()]))
    finished=datetime.now(timezone.utc).isoformat();events=['events','--since',started,'--until',finished,'--filter','event=oom','--format','{{json .}}']
    for cid in services.values():events+=['--filter','container='+cid]
    oom_events=subprocess.check_output(d+events,text=True,timeout=30).splitlines()
    result=dict(source=data['source'],project=data['project'],run=run,started_utc=started,finished_utc=finished,seconds=args.seconds,
        elapsed_seconds=round(elapsed,3),wall_elapsed_seconds=round(wall_elapsed,3),users=20,clinics=20,target_rps=5,actual_rps=round(len(results)/elapsed,3),
        arrival_mode='twenty simultaneous requests every four seconds',max_in_flight=peak,dropped=dropped,summary=summary(results),
        reads=summary([r for r in results if not r['write']]),writes=summary([r for r in results if r['write']]),
        oom=bool(oom_events) or any(m['State']['OOMKilled'] for m in meta),oom_events=len(oom_events),
        services_running=all(m['State']['Running'] for m in meta),unique_written_records=len({r.get('record_id') for r in results if r['write'] and r['ok']}),
        resource_limits={m['Name'].lstrip('/'):dict(memory_bytes=m['HostConfig']['Memory'],nano_cpus=m['HostConfig']['NanoCpus']) for m in meta},results=results,
        scope='Exact image on Mac; synthetic self-history writes, not real clinical outcomes or independent cloud capacity')
    result['passed']=not dropped and result['summary']['failures']==0 and result['summary']['p95_seconds']<5 and not result['oom'] and result['services_running'] and result['unique_written_records']==total//5
    out=Path(args.output);out.write_text(json.dumps(result,indent=2)+'\n');out.chmod(0o600)
    print(json.dumps({k:result[k] for k in ['passed','source','seconds','summary','reads','writes','oom','unique_written_records']}))
    return 0 if result['passed'] else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);p.add_argument('--seconds',type=int,choices=(20,60,1800),default=1800);p.add_argument('--docker',default='docker')
    raise SystemExit(load(p.parse_args()))
