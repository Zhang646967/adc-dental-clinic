"""Explicit read-only guard before the existing notification command."""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if os.environ.get('ADC_RC_SYNTHETIC')!='1':
    raise SystemExit('Not an RC course instance.')
if os.environ.get('ADC_READ_ONLY','1')!='0':
    print('Read-only instance: no notification writer started.')
    raise SystemExit(0)
os.execv(sys.executable,[sys.executable,'manage.py','dispatch_notifications','--watch','--interval','5','--batch-size','25'])
