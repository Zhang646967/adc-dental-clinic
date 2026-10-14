"""Explicit production worker; readonly deployments start no notice writer."""
import os
import subprocess
import sys

if os.environ.get('DJANGO_SETTINGS_MODULE') != 'config.settings.production':
    raise SystemExit('G4 worker requires runtime production settings.')
if os.environ.get('ADC_READ_ONLY', '1') != '0':
    print('Read-only G4 instance: no notification writer started.')
    raise SystemExit(0)
subprocess.run([sys.executable, 'manage.py', 'check_runtime_role'], check=True)
subprocess.run([sys.executable, 'manage.py', 'migrate', '--check'], check=True)
os.execv(sys.executable, [sys.executable, 'manage.py', 'dispatch_notifications',
                       '--watch', '--interval', '5', '--batch-size', '25'])
