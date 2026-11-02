from django.db import migrations


def preserve(apps,schema_editor):
    for name in ('RecordCopyRequest','RecordCopyItem','RecordCopyFile','RecordCopyEvent'):
        if apps.get_model('clinical',name).objects.using(schema_editor.connection.alias).exists():
            raise RuntimeError('Retained copy applications, sources and deliveries exist; destructive reversal refused.')
    if apps.get_model('clinical','ClinicalReviewerAppointment').objects.filter(can_review_copies=True).exists():
        raise RuntimeError('Explicit copy review duties exist; reversal refused.')


SQL=r'''
CREATE FUNCTION adc_copy_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Copy applications and identity history are retained'; END IF;
 IF (NEW.patient_id,NEW.clinic_id,NEW.recipient_id,NEW.created_by_id,NEW.kind,NEW.purpose,NEW.recipient_name,NEW.created_at)
 IS DISTINCT FROM (OLD.patient_id,OLD.clinic_id,OLD.recipient_id,OLD.created_by_id,OLD.kind,OLD.purpose,OLD.recipient_name,OLD.created_at)
 THEN RAISE EXCEPTION 'Original applicant, purpose, patient and recipient cannot be replaced'; END IF;
 IF NEW.state IN ('APPROVED','FAILED','READY','DELIVERED') AND
 (NEW.verified_by_id IS NULL OR NEW.reviewed_by_id IS NULL OR NEW.reviewed_at IS NULL
 OR NEW.reviewed_by_id IN (NEW.verified_by_id,NEW.created_by_id,NEW.recipient_id)
 OR NOT EXISTS(SELECT 1 FROM adc_clinical_reviewer r WHERE r.id=NEW.assigned_reviewer_id AND r.user_id=NEW.reviewed_by_id AND r.clinic_id=NEW.clinic_id))
 THEN RAISE EXCEPTION 'Copy publication requires independent reviewed identity and scope'; END IF;
 IF NEW.state IN ('READY','DELIVERED') AND NOT EXISTS(SELECT 1 FROM adc_record_copy_file WHERE request_id=NEW.id)
 THEN RAISE EXCEPTION 'Ready copies require their immutable file'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER copy_request_retained BEFORE UPDATE OR DELETE ON adc_record_copy_request FOR EACH ROW EXECUTE FUNCTION adc_copy_request_guard();

CREATE FUNCTION adc_copy_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Copy scope is retained'; END IF;
 IF TG_OP='UPDATE' AND ((NEW.request_id,NEW.visit_id,NEW.sections) IS DISTINCT FROM (OLD.request_id,OLD.visit_id,OLD.sections)
 OR OLD.package_id IS NOT NULL OR NOT EXISTS(SELECT 1 FROM adc_record_copy_request WHERE id=NEW.request_id AND state='PENDING'))
 THEN RAISE EXCEPTION 'Only missing fixed sources may be resolved during material verification'; END IF;
 IF NOT EXISTS(SELECT 1 FROM adc_visit v JOIN adc_record_copy_request r ON r.id=NEW.request_id
 WHERE v.id=NEW.visit_id AND v.patient_id=r.patient_id AND v.clinic_id=r.clinic_id)
 OR (NEW.package_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM adc_archive_package p
 JOIN adc_clinical_archive a ON a.id=p.archive_id JOIN adc_clinical_encounter e ON e.id=a.encounter_id
 WHERE p.id=NEW.package_id AND e.visit_id=NEW.visit_id))
 THEN RAISE EXCEPTION 'Copy sources must belong to the requested patient, clinic and visit'; END IF;
 IF jsonb_typeof(NEW.sections)<>'array' OR jsonb_array_length(NEW.sections)=0
 OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.sections) x WHERE x NOT IN ('DOCUMENT','TREATMENT','CONSENT','FEES'))
 THEN RAISE EXCEPTION 'Copy sections must be explicitly selected'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER copy_scope_retained BEFORE INSERT OR UPDATE OR DELETE ON adc_record_copy_item FOR EACH ROW EXECUTE FUNCTION adc_copy_scope_guard();

CREATE FUNCTION adc_copy_file_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Issued copy bytes and manifests are immutable'; END IF;
 IF NOT EXISTS(SELECT 1 FROM adc_record_copy_request WHERE id=NEW.request_id AND state='APPROVED')
 OR NEW.sha256<>encode(sha256(NEW.pdf),'hex') OR substring(NEW.pdf from 1 for 5)<>convert_to('%PDF-','UTF8')
 OR (NEW.manifest->>'request')::bigint<>NEW.request_id THEN RAISE EXCEPTION 'Copy requires its approved scope and exact file digest'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER copy_file_retained BEFORE INSERT OR UPDATE OR DELETE ON adc_record_copy_file FOR EACH ROW EXECUTE FUNCTION adc_copy_file_guard();
CREATE TRIGGER copy_event_retained BEFORE UPDATE OR DELETE ON adc_record_copy_event FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();
'''
REVERSE='''DROP TRIGGER copy_event_retained ON adc_record_copy_event;
DROP TRIGGER copy_file_retained ON adc_record_copy_file; DROP FUNCTION adc_copy_file_guard();
DROP TRIGGER copy_scope_retained ON adc_record_copy_item; DROP FUNCTION adc_copy_scope_guard();
DROP TRIGGER copy_request_retained ON adc_record_copy_request; DROP FUNCTION adc_copy_request_guard();'''


class Migration(migrations.Migration):
    dependencies=[('clinical','0015_clinicalreviewerappointment_can_review_copies_and_more'),('accounts','0007_roleassignment_can_verify_record_copies_and_more')]
    operations=[migrations.RunSQL(SQL,REVERSE),migrations.RunPython(migrations.RunPython.noop,preserve)]
