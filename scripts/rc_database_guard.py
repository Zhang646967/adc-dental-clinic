"""Used only before restoring into the newly created RC database."""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.course_demo')
import django
django.setup()
from django.db import connection
if os.environ.get('ADC_RC_SYNTHETIC')!='1' or connection.settings_dict['NAME']!='adc_rc_demo':
    raise SystemExit('Dedicated RC database required.')
with connection.cursor() as c:
    c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    if c.fetchall():raise SystemExit('Refusing restore: destination public schema is not empty.')
print('Empty RC destination confirmed; source instance not contacted.')
