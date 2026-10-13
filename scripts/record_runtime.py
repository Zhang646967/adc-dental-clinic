"""Capture actually installed packages without environment values or credentials."""
import importlib.metadata,json,os,platform,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
info={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
      'platform':platform.platform(),'packages':{}}
for name in ('Django','psycopg','psycopg-binary','tzdata','gunicorn'):
    try:info['packages'][name]=importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:info['packages'][name]=None
print(json.dumps(info,indent=2))
if os.environ.get('ADC_EVIDENCE_DIR'):
    directory=Path(os.environ['ADC_EVIDENCE_DIR']);directory.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (directory/f'runtime-{stamp}.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    # Freeze published distribution names and versions only, never editable URLs.
    rows=sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions() if d.metadata.get('Name'))
    (directory/f'installed-{stamp}.txt').write_text('\n'.join(rows)+'\n',encoding='utf-8')
