"""Private simulator input. No credential is printed or committed to source."""
from pathlib import Path
import json,os
from django.core.management.base import BaseCommand,CommandError
from accounts.external_identity import issue_local_code
from accounts.models import UserAccount


class Command(BaseCommand):
    help='Issue a private five-minute local identity/phone surrogate; synthetic instances only.'
    def add_arguments(self,parser):
        group=parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--subject',help='Stable synthetic login identity code, e.g. course-parent-1')
        group.add_argument('--account',help='Exact ADC account username for a synthetic phone proof')
        parser.add_argument('--phone',help='Eleven-digit synthetic number starting with zero')
        parser.add_argument('--output',required=True,help='Private JSON output path, outside versioned files')
    def handle(self,*args,**options):
        from adc_core.rules import RuleError
        from django.core.exceptions import PermissionDenied
        try:
            if options['subject']:code,expiry=issue_local_code(subject=options['subject'])
            else:
                user=UserAccount.objects.get(username=options['account'],is_active=True)
                code,expiry=issue_local_code(user_id=user.pk,phone=options['phone'])
        except (RuleError,PermissionDenied,UserAccount.DoesNotExist) as exc:raise CommandError(str(exc)) from None
        output=Path(options['output']);output.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as file:
            os.fchmod(file.fileno(),0o600)
            json.dump(dict(source='LOCAL_SIMULATION',purpose='LOGIN' if options['subject'] else 'PHONE',code=code,expires_at=expiry.isoformat()),file,indent=2);file.write('\n')
        self.stdout.write('Local-only one-use credential written to the private output file; valid for five minutes.')
