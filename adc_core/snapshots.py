"""Coherent read models: one PostgreSQL snapshot for each reporting service.
Do not nest in write transactions: READ COMMITTED cannot be upgraded after reads.
"""
from contextlib import contextmanager
from django.db import connection, transaction

@contextmanager
def reporting_snapshot():
    if connection.in_atomic_block:
        raise RuntimeError("Reporting must start outside an existing transaction")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        yield
