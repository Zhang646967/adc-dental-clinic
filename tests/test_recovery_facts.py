"""Real PostgreSQL snapshot, byte-content and schema comparison regressions."""
from copy import deepcopy
import hashlib

from django.db import connection
from django.test import TransactionTestCase
import psycopg

from scripts.recovery_facts import collect, compare


class DatabaseRecoveryFactsTests(TransactionTestCase):
    def setUp(self):
        connection.ensure_connection()
        self.driver = connection.connection
        self.driver.execute('CREATE TABLE public.recovery_probe (id integer PRIMARY KEY, payload bytea NOT NULL)')
        self.addCleanup(self.driver.execute, 'DROP TABLE IF EXISTS public.recovery_probe')
        self.driver.execute('INSERT INTO public.recovery_probe VALUES (1,%s)', (b'original,csv\r\n\x00\xff',))

    def facts(self):
        with self.driver.transaction():
            self.driver.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            return collect(self.driver)

    def test_all_tables_including_associations_and_binary_content_are_compared(self):
        before = self.facts()
        for name in ('public.adc_user', 'public.adc_user_groups', 'public.django_migrations',
                     'public.adc_statement_batch', 'public.adc_cash_evidence',
                     'public.adc_reconciliation_match', 'public.recovery_probe'):
            self.assertIn(name, before['tables'])
        self.assertEqual(compare(before, self.facts())['tables'], len(before['tables']))
        self.driver.execute('UPDATE public.recovery_probe SET payload=%s WHERE id=1', (b'changed,csv\r\n\x00\xff',))
        with self.assertRaises(ValueError): compare(before, self.facts())

    def test_same_length_binary_substitution_is_not_a_repr_or_row_count_match(self):
        before = self.facts()['tables']['public.recovery_probe']
        self.driver.execute('UPDATE public.recovery_probe SET payload=%s', (b'altered!,csv\r\n\x00\xff',))
        after = self.facts()['tables']['public.recovery_probe']
        self.assertEqual(before['rows'], after['rows'])
        self.assertNotEqual(before['sha256'], after['sha256'])

    def test_schema_changes_and_removed_table_are_detected(self):
        before = self.facts()
        self.driver.execute('ALTER TABLE public.recovery_probe ADD COLUMN reviewed boolean DEFAULT false')
        with self.assertRaises(ValueError): compare(before, self.facts())
        self.driver.execute('DROP TABLE public.recovery_probe')
        with self.assertRaises(ValueError): compare(before, self.facts())

    def test_exported_snapshot_excludes_concurrent_commit_but_current_read_sees_it(self):
        settings = connection.settings_dict
        params = dict(host=settings['HOST'], port=settings['PORT'], dbname=settings['NAME'],
                      user=settings['USER'], password=settings['PASSWORD'])
        with psycopg.connect(**params) as reader, psycopg.connect(**params) as writer:
            with self.driver.transaction():
                self.driver.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                before = collect(self.driver)
                snapshot_id = self.driver.execute('SELECT pg_export_snapshot()').fetchone()[0]
                writer.execute('INSERT INTO public.recovery_probe VALUES (2,%s)', (b'concurrent committed CSV',))
                writer.commit()
                reader.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                from psycopg import sql
                reader.execute(sql.SQL('SET TRANSACTION SNAPSHOT {}').format(sql.Literal(snapshot_id)))
                self.assertEqual(before, collect(reader))
            with self.assertRaises(ValueError): compare(before, self.facts())

    def test_nonpublic_business_tables_prevent_partial_acceptance(self):
        self.driver.execute('CREATE SCHEMA recovery_scope')
        try:
            self.driver.execute('CREATE TABLE recovery_scope.uncovered (id integer)')
            with self.assertRaises(ValueError): self.facts()
        finally:
            self.driver.execute('DROP SCHEMA recovery_scope CASCADE')

    def test_duplicate_rows_change_content_digest(self):
        self.driver.execute('ALTER TABLE public.recovery_probe DROP CONSTRAINT recovery_probe_pkey')
        before = self.facts()['tables']['public.recovery_probe']
        self.driver.execute('INSERT INTO public.recovery_probe SELECT * FROM public.recovery_probe')
        after = self.facts()['tables']['public.recovery_probe']
        self.assertEqual(after['rows'], before['rows'] * 2)
        self.assertNotEqual(before['sha256'], after['sha256'])
