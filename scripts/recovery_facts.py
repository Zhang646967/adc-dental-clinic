"""Versioned, bounded PostgreSQL facts; no Django setup or business writes.

The host sends this exact reader into the identified maintenance image. With
--hold, its exported read-only snapshot stays open until pg_dump has finished.
JSONB's bytea representation includes the actual bytes, never Python repr().
"""
import hashlib
import json
import os
import re
import sys

METHOD = 'PG17_JSONB_SHA256_V1'
MAX_FACTS = 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate(value):
    if (not isinstance(value, dict) or set(value) != {'v', 'method', 'tables'} or
            type(value['v']) is not int or value['v'] != 1 or value['method'] != METHOD or
            not isinstance(value['tables'], dict) or not 1 <= len(value['tables']) <= 256 or
            len(canonical(value)) > MAX_FACTS):
        raise ValueError('Database facts format differs.')
    for name, fact in value['tables'].items():
        if (not re.fullmatch(r'public\.[a-zA-Z_][a-zA-Z0-9_]{0,62}', name) or
                not isinstance(fact, dict) or set(fact) != {'rows', 'sha256', 'schema_sha256'} or
                type(fact['rows']) is not int or not 0 <= fact['rows'] <= 1000000 or
                any(not isinstance(fact[key], str) or not re.fullmatch(r'[0-9a-f]{64}', fact[key])
                    for key in ('sha256', 'schema_sha256'))):
            raise ValueError('Database table facts differ.')
    return value


def compare(expected, actual):
    validate(expected)
    validate(actual)
    if expected != actual:
        # Never disclose table contents, clinical data or financial references.
        raise ValueError('Restored database facts differ; runtime remains stopped.')
    return {'method': METHOD, 'tables': len(expected['tables']),
            'rows': sum(f['rows'] for f in expected['tables'].values()),
            'facts_sha256': fingerprint(expected)}


def collect(connection):
    """Called within ONE read-only repeatable-read transaction."""
    from psycopg import sql
    connection.execute("SET LOCAL timezone='UTC'")
    connection.execute("SET LOCAL datestyle='ISO, YMD'")
    connection.execute("SET LOCAL intervalstyle='postgres'")
    connection.execute("SET LOCAL statement_timeout='120s'")
    connection.execute("SET LOCAL lock_timeout='5s'")
    if connection.info.server_version // 10000 != 17:
        raise ValueError('PostgreSQL 17 is required.')
    relations = connection.execute("""SELECT n.nspname,c.relname,c.relkind FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog','information_schema')
        AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','m','f')
        ORDER BY 1,2""").fetchall()
    if not 1 <= len(relations) <= 256 or any(n != 'public' or k != 'r' for n, _, k in relations):
        raise ValueError('Unsupported database relation scope; no partial comparison.')
    # Protect definitions from concurrent DDL while allowing normal writes.
    connection.execute(sql.SQL('LOCK TABLE {} IN ACCESS SHARE MODE').format(
        sql.SQL(',').join(sql.Identifier(n, t) for n, t, _ in relations)))
    result = {'v': 1, 'method': METHOD, 'tables': {}}
    for namespace, table, _ in relations:
        relation = namespace + '.' + table
        columns = connection.execute("""SELECT a.attname,format_type(a.atttypid,a.atttypmod),
            a.attnotnull,a.attgenerated,pg_get_expr(d.adbin,d.adrelid)
            FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
            WHERE a.attrelid=%s::regclass AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum""",
            (relation,)).fetchall()
        constraints = connection.execute("""SELECT conname,pg_get_constraintdef(oid,true)
            FROM pg_constraint WHERE conrelid=%s::regclass ORDER BY conname""", (relation,)).fetchall()
        indexes = connection.execute("""SELECT indexname,indexdef FROM pg_indexes
            WHERE schemaname=%s AND tablename=%s ORDER BY indexname""", (namespace, table)).fetchall()
        schema = {'columns': columns, 'constraints': constraints, 'indexes': indexes}
        h, count = hashlib.sha256(), 0
        # Sorted fixed-width row hashes preserve duplicate multiplicity, without
        # loading rows/CSV bytea into the host or keeping a full table in Python.
        query = sql.SQL('''SELECT h FROM (
            SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') AS h
            FROM {} t) hashed ORDER BY h COLLATE "C"''').format(sql.Identifier(namespace, table))
        with connection.cursor(name='recovery_rows') as cursor:
            cursor.execute(query)
            for (row_hash,) in cursor:
                count += 1
                if count > 1000000:
                    raise ValueError('Course database facts exceed the row bound.')
                h.update(row_hash.encode('ascii') + b'\n')
        result['tables'][relation] = {'rows': count, 'sha256': h.hexdigest(),
                                    'schema_sha256': fingerprint(schema)}
    return validate(result)


def main():
    import psycopg
    hold = sys.argv[-1:] == ['--hold']
    with psycopg.connect(host=os.environ['DB_HOST'], port=os.environ.get('DB_PORT', '5432'),
                         dbname=os.environ['POSTGRES_DB'], user=os.environ['ADC_DATABASE_OWNER'],
                         password=os.environ['ADC_MIGRATION_PASSWORD'], connect_timeout=10) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        facts = collect(connection)
        snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0] if hold else None
        print(canonical({'snapshot': snapshot, 'facts': facts}).decode(), flush=True)
        if hold and sys.stdin.readline().strip() != 'DUMP_COMPLETE':
            raise ValueError('Snapshot export was interrupted.')


if __name__ == '__main__':
    main()
