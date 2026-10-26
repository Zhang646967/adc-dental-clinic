"""Run after a verified restore, before starting any application writers."""
import json
from django.core.management.base import BaseCommand
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone
from accounts.external_models import WebLoginTicket,SmsChallenge,LocalIdentityCode


class Command(BaseCommand):
    help='Expire restored pending authentication without changing accounts, passwords or clinical grants.'
    @transaction.atomic
    def handle(self,**options):
        now=timezone.now()
        counts=dict(qr=WebLoginTicket.objects.filter(state__in=['PENDING','APPROVED']).update(state='EXPIRED',expires_at=now),
            sms=SmsChallenge.objects.filter(consumed_at__isnull=True,expires_at__gt=now).update(expires_at=now),
            local=LocalIdentityCode.objects.filter(consumed_at__isnull=True,expires_at__gt=now).update(expires_at=now))
        from django.contrib.sessions.backends.db import SessionStore
        counts['sessions']=0
        for session in Session.objects.select_for_update().filter(expire_date__gt=now).iterator():
            data=session.get_decoded();keys={'adc_auth_session','adc_web_qr','adc_wechat_oauth','adc_sms_captcha'}&data.keys()
            if keys:
                for key in keys:data.pop(key)
                session.session_data=SessionStore().encode(data);session.save(update_fields=['session_data']);counts['sessions']+=1
        self.stdout.write(json.dumps(dict(status='AUTH_CHALLENGES_EXPIRED',**counts)))
