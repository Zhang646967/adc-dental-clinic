"""Prepare only a new RC configuration; no Docker, DB or existing .env access.
Run using the Python base image from RC_WINDOWS.cmd, avoiding host Python.
"""
from pathlib import Path
import argparse,json,re,secrets,os

def prepare(root,port=18000):
    root=Path(root).resolve()
    if not 1024<=port<=65535:raise ValueError('Invalid loopback port.')
    if (root/'.env').exists():raise ValueError('Use a clean extraction, not the old working directory.')
    target=root/'.rc'
    if target.exists():raise ValueError('.rc already exists; never overwrite existing secrets/state.')
    project='adc_rc1_'+secrets.token_hex(6)
    target.mkdir(mode=0o700);(target/'private').mkdir(mode=0o700)
    env={'RC_PROJECT':project,'RC_APP_SECRET':secrets.token_urlsafe(64),'RC_DB_PASSWORD':secrets.token_urlsafe(32),
         'RC_WEB_PORT':str(port),'RC_READ_ONLY':'0'}
    with (target/'compose.env').open('x',encoding='ascii') as f:f.write(''.join(k+'='+v+'\n' for k,v in env.items()))
    (target/'project.txt').write_text(project+'\n',encoding='ascii')
    (target/'state.json').write_text(json.dumps({'instance':project,'initialized':False,'version':'1.0.0-rc.1'},indent=2),encoding='ascii')
    try:(target/'compose.env').chmod(0o600)
    except OSError:pass
    return project

def validate(root):
    root=Path(root)
    project=(root/'.rc/project.txt').read_text().strip()
    if not re.fullmatch(r'adc_rc1_[0-9a-f]{12}',project):raise ValueError('Invalid project identifier.')
    env={}
    for line in (root/'.rc/compose.env').read_text().splitlines():
        k,v=line.split('=',1);env[k]=v
    required={'RC_PROJECT','RC_APP_SECRET','RC_DB_PASSWORD','RC_WEB_PORT','RC_READ_ONLY'}
    if not required<=set(env) or set(env)-required-{'RC_SMS_PROVIDER','RC_TEACHER_TEST_MODE'}:raise ValueError('Unexpected configuration keys.')
    if env.get('RC_SMS_PROVIDER','disabled') not in ('disabled','demo') or env.get('RC_TEACHER_TEST_MODE','0') not in ('0','1'):raise ValueError('Invalid local authentication configuration.')
    if env.get('RC_SMS_PROVIDER')=='demo' and env.get('RC_TEACHER_TEST_MODE')!='1':raise ValueError('Test SMS requires the explicit synthetic teacher flag.')
    if env['RC_PROJECT']!=project or len(env['RC_APP_SECRET'])<50 or len(env['RC_DB_PASSWORD'])<30:raise ValueError('Incomplete private configuration.')
    if env['RC_READ_ONLY'] not in ('0','1'):raise ValueError('Invalid read-only switch.')
    if not env['RC_WEB_PORT'].isdigit() or not 1024<=int(env['RC_WEB_PORT'])<=65535:raise ValueError('Invalid port.')
    return project

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action',choices=['prepare','validate']);a.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));a.add_argument('--port',type=int,default=18000)
    o=a.parse_args()
    try:
        result=prepare(o.root,o.port) if o.action=='prepare' else validate(o.root)
        print('RC configuration: '+result+'; secrets not displayed. Protect .rc/private and compose.env.')
    except (OSError,ValueError) as exc:
        print('RC configuration stopped: '+str(exc));raise SystemExit(2)
