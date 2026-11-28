-- Use a read-only connection to the accepted PostgreSQL schema.
BEGIN READ ONLY;
SELECT src.relname AS source_table, source_col.attname AS source_field,
       dst.relname AS target_table, target_col.attname AS target_field,
       source_col.attnotnull AS required
FROM pg_constraint AS c
JOIN pg_class AS src ON src.oid = c.conrelid
JOIN pg_namespace AS ns ON ns.oid = src.relnamespace
JOIN pg_class AS dst ON dst.oid = c.confrelid
JOIN pg_attribute AS source_col
    ON source_col.attrelid = src.oid AND source_col.attnum = c.conkey[1]
JOIN pg_attribute AS target_col
    ON target_col.attrelid = dst.oid AND target_col.attnum = c.confkey[1]
WHERE c.contype = 'f' AND ns.nspname = 'public'
  AND (src.relname, source_col.attname) IN (
      ('adc_visit', 'patient_id'), ('adc_visit', 'replaces_visit_id'),
      ('adc_portal_booking_receipt', 'visit_id'), ('adc_clinical_encounter', 'visit_id'),
      ('adc_clinical_draft', 'encounter_id'), ('adc_clinical_draft', 'base_record_id'),
      ('adc_clinical_record_version', 'encounter_id'), ('adc_clinical_record_version', 'previous_id')
  )
ORDER BY source_table, source_field;

SELECT t.relname AS table_name, pg_get_indexdef(i.indexrelid) AS unique_index
FROM pg_index AS i
JOIN pg_class AS t ON t.oid = i.indrelid
JOIN pg_namespace AS ns ON ns.oid = t.relnamespace
WHERE i.indisunique AND ns.nspname = 'public' AND t.relname IN (
  'adc_visit', 'adc_portal_booking_receipt', 'adc_clinical_encounter',
  'adc_clinical_draft', 'adc_clinical_record_version'
)
ORDER BY table_name, unique_index;
ROLLBACK;
