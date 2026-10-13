"""Read-only inspection of the connected database identity, no grants or DDL."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

class Command(BaseCommand):
    help='Reject an overprivileged web database identity; does not change grants.'
    def handle(self,*args,**options):
        if connection.vendor != 'postgresql':raise CommandError('PostgreSQL is required.')
        with connection.cursor() as cur:
            cur.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            privileged=any(cur.fetchone())
            cur.execute("SELECT d.datdba=r.oid FROM pg_database d JOIN pg_roles r ON r.rolname=current_user WHERE d.datname=current_database()")
            owns_database=cur.fetchone()[0]
            cur.execute("SELECT has_schema_privilege(current_user,'public','CREATE')")
            can_create=cur.fetchone()[0]
            cur.execute("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname='public' AND c.relkind IN ('r','p') AND r.rolname=current_user)")
            owns_table=cur.fetchone()[0]
        if privileged or owns_database or can_create or owns_table:
            raise CommandError('Runtime identity has administrative/ownership/CREATE privileges. Provision a restricted identity separately.')
        self.stdout.write('Role privilege inspection passed. Object DML grants and application behavior still require separate tests.')
