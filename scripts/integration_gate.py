"""Sequential validation with durable optional log. No actual database deletion except Django's test DB."""
import os,sys,json,subprocess,hashlib,platform
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
STEPS=[
 [sys.executable,'scripts/verify_update.py'],
 [sys.executable,'-m','unittest','discover','-s','checks','-v'],
 [sys.executable,'scripts/record_runtime.py'],
 [sys.executable,'manage.py','check'],
 [sys.executable,'manage.py','makemigrations','--check','--dry-run'],
 [sys.executable,'manage.py','migrate','--noinput'],
 [sys.executable,'manage.py','test','tests','--settings=config.settings.test','--noinput','--verbosity=2'],
]
def source_digest():
 h=hashlib.sha256()
 for p in sorted(ROOT.rglob('*')):
  if not p.is_file() or p.suffix not in ('.py','.html','.css','.js','.cjs','.yaml','.txt','.json'):continue
  rel=p.relative_to(ROOT)
  if any(x in rel.parts for x in ('__pycache__','.venv','.runtime','docs','evidence','backups','.rc')):continue
  h.update(rel.as_posix().encode());h.update(b'\0');h.update(p.read_bytes());h.update(b'\0')
 return h.hexdigest()
if __name__=='__main__':
 if (os.environ.get('POSTGRES_DB') != 'adc_verify' or os.environ.get('DB_HOST') != 'verify-db' or os.environ.get('DJANGO_SETTINGS_MODULE') != 'config.settings.test'):
  raise SystemExit('STOP: integration_gate requires the dedicated isolated verification configuration; no migrations executed.')
 os.chdir(ROOT);stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
 folder=Path(os.environ['ADC_EVIDENCE_DIR']) if os.environ.get('ADC_EVIDENCE_DIR') else None
 if folder:folder.mkdir(parents=True,exist_ok=True)
 log=(folder/f'gate-{stamp}.log').open('x',encoding='utf-8') if folder else None
 outcomes=[]
 try:
  for command in STEPS:
   print('Running:',' '.join(command),flush=True)
   if log:log.write('Running: '+' '.join(command)+'\n');log.flush()
   process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
   for line in process.stdout:
    print(line,end='',flush=True)
    if log:log.write(line);log.flush()
   code=process.wait();outcomes.append({'command':command,'returncode':code})
   if code:break
 finally:
  if log:log.close()
 report={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),'source_sha256':source_digest(),
  'results':outcomes,'all_gates_passed':len(outcomes)==len(STEPS) and all(x['returncode']==0 for x in outcomes)}
 print(json.dumps(report,ensure_ascii=False,indent=2))
 if folder:(folder/f'gate-{stamp}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 sys.exit(0 if report['all_gates_passed'] else 1)
