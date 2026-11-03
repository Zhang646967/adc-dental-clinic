"""Verify and apply only the operator's approved forward release migrations."""
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = 'Check or apply the reviewed atomic forward migration plan as the G4 database owner.'

    def add_arguments(self, parser):
        parser.add_argument('approved', nargs='+')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if settings.SETTINGS_MODULE != 'config.settings.g4_maintenance':
            raise CommandError('Use the explicit G4 maintenance service.')
        executor = MigrationExecutor(connection)
        executor.loader.check_consistent_history(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        approved = set(options['approved'])
        if any(backwards or not migration.atomic or
               migration.app_label + '.' + migration.name not in approved
               for migration, backwards in plan):
            raise CommandError('Only reviewed, atomic forward migrations are permitted.')
        if options['apply']:
            call_command('migrate', interactive=False, stdout=self.stdout)
