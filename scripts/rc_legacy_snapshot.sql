\set ON_ERROR_STOP on
SET timezone TO 'UTC';
SET datestyle TO 'ISO, YMD';
-- Same columns before/after; new RC columns intentionally excluded.
SELECT 'account|'||id||'|'||md5(row(username,password,is_active,dentist_id)::text) FROM adc_user ORDER BY id;
SELECT 'patient|'||id||'|'||md5(row(patient_no,name,date_of_birth,billing_address,phone,email)::text) FROM adc_patient ORDER BY id;
SELECT 'visit|'||id||'|'||md5(row(patient_id,clinic_id,dentist_id,availability_slot_id,scheduled_start,scheduled_end,status,lock_version)::text) FROM adc_visit ORDER BY id;
SELECT 'invoice|'||id||'|'||md5(row(invoice_no,visit_id,current_record_version_id,first_issued_at)::text) FROM adc_invoice ORDER BY id;
SELECT 'record|'||id||'|'||md5(row(visit_id,revision_no,state,total_amount,billing_header_snapshot)::text) FROM adc_visit_record_version ORDER BY id;
SELECT 'wait|'||id||'|'||md5(row_to_json(w)::text) FROM adc_wait_request w ORDER BY id;
SELECT 'offer|'||id||'|'||md5(row_to_json(o)::text) FROM adc_wait_offer o ORDER BY id;
SELECT 'event|'||id||'|'||md5(row_to_json(a)::text) FROM adc_audit_event a ORDER BY id;
