"""Local diagnostic command; configuration presence, never credential values."""
import json,platform
import django
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
class Command(BaseCommand):
    help="Show safe local version and pending-migration diagnostics (no remote AI call)."
    def handle(self,*args,**options):
        executor=MigrationExecutor(connection)
        pending=executor.migration_plan(executor.loader.graph.leaf_nodes())
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            database_version=cursor.fetchone()[0]
        data={"application_version":settings.ADC_VERSION,"python":platform.python_version(),
              "django":django.get_version(),"postgresql":database_version,
              "pending_migrations":len(pending),"ai_mode":getattr(settings,"AI_MODE","demo"),
              "ai_key_present":bool(getattr(settings,"AI_API_KEY","")),
              "debug":settings.DEBUG,"public_deployment_verified":False}
        self.stdout.write(json.dumps(data,ensure_ascii=False,indent=2))
