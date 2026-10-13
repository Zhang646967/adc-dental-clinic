from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from assistants.provider import ProviderConfig,classify,ProviderError
class Command(BaseCommand):
    help="Check AI configuration without printing credentials. Network only with --live."
    def add_arguments(self,parser): parser.add_argument("--live",action="store_true",help="Send one synthetic request; may incur provider charges")
    def handle(self,*args,**options):
        self.stdout.write(f"mode={settings.AI_MODE}; key_configured={bool(settings.AI_API_KEY)}; model_configured={bool(settings.AI_MODEL)}")
        if not options["live"]:
            self.stdout.write("No network request. Use --live only after configuring your approved provider.");return
        if settings.AI_MODE!="remote": raise CommandError("Set AI_MODE=remote before a live check.")
        try:
            result=classify("我想预约","patient",ProviderConfig(settings.AI_BASE_URL,settings.AI_API_KEY,settings.AI_MODEL,
                tuple(settings.AI_ALLOWED_HOSTS),settings.AI_TIMEOUT_SECONDS,settings.AI_TOKEN_LIMIT_FIELD))
        except ProviderError as exc: raise CommandError("AI check failed: "+exc.code) from None
        self.stdout.write("Synthetic remote request succeeded; recognised intent="+result)
