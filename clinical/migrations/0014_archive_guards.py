from django.db import migrations


def preserve(apps,schema_editor):
    for name in ('ClinicalArchive','ArchiveSubmission','ArchivePackage','ArchiveAmendment','ArchiveEvent'):
        if apps.get_model('clinical',name).objects.using(schema_editor.connection.alias).exists():
            raise RuntimeError('Retained archive work or files exist; destructive reversal refused.')
    if apps.get_model('clinical','ClinicalReviewerAppointment').objects.filter(can_review_archives=True).exists():
        raise RuntimeError('An explicit archive review appointment exists; reversal refused.')


SQL=r'''
CREATE FUNCTION adc_archive_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Archive work identity is retained'; END IF;
 IF NEW.encounter_id<>OLD.encounter_id OR NEW.responsible_id<>OLD.responsible_id OR NEW.due_at<>OLD.due_at
 OR NEW.created_at<>OLD.created_at OR NEW.revision<>OLD.revision+1 THEN
  RAISE EXCEPTION 'Archive identity, original deadline and revision must be retained';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER archive_head_retained BEFORE UPDATE OR DELETE ON adc_clinical_archive
FOR EACH ROW EXECUTE FUNCTION adc_archive_head_guard();

CREATE FUNCTION adc_archive_submission_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE enc bigint; author_dentist bigint;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Archive submissions are retained'; END IF;
 SELECT a.encounter_id,v.dentist_id INTO enc,author_dentist FROM adc_clinical_archive a
 JOIN adc_clinical_encounter e ON e.id=a.encounter_id JOIN adc_visit v ON v.id=e.visit_id WHERE a.id=NEW.archive_id;
 IF NEW.document_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM adc_clinical_document_version d
 JOIN adc_clinical_document h ON h.id=d.document_id WHERE d.id=NEW.document_version_id AND h.encounter_id=enc) THEN
  RAISE EXCEPTION 'Archive document must belong to the same encounter';
 END IF;
 IF NEW.kind='ARCHIVE' AND jsonb_array_length(NEW.snapshot->'issues')<>0 THEN
  RAISE EXCEPTION 'Incomplete materials cannot be published as a complete archive';
 END IF;
 IF NEW.previous_package_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM adc_archive_package WHERE id=NEW.previous_package_id AND archive_id=NEW.archive_id) THEN
  RAISE EXCEPTION 'Archive predecessor belongs to another encounter';
 END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['state','revision','reviewer_id','reviewed_by_id','reviewed_at','review_note','approval_scope','attempts','generation_error'])
   IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','revision','reviewer_id','reviewed_by_id','reviewed_at','review_note','approval_scope','attempts','generation_error'])
   OR NEW.revision<>OLD.revision+1 THEN RAISE EXCEPTION 'Submitted source snapshots and original responsibility are retained'; END IF;
  IF NOT ((OLD.state='PENDING' AND NEW.state IN ('APPROVED','RETURNED','REJECTED','STALE'))
       OR (OLD.state='APPROVED' AND NEW.state IN ('PUBLISHED','FAILED','STALE'))
       OR (OLD.state='FAILED' AND NEW.state IN ('APPROVED','STALE'))) THEN
   RAISE EXCEPTION 'Invalid archive submission transition';
  END IF;
  IF OLD.reviewed_at IS NOT NULL AND (NEW.reviewed_at,NEW.reviewed_by_id,NEW.reviewer_id,NEW.review_note,NEW.approval_scope)
   IS DISTINCT FROM (OLD.reviewed_at,OLD.reviewed_by_id,OLD.reviewer_id,OLD.review_note,OLD.approval_scope) THEN
   RAISE EXCEPTION 'Independent archive review is retained';
  END IF;
 END IF;
 IF NEW.reviewed_at IS NOT NULL AND (NEW.reviewed_by_id=NEW.submitted_by_id OR NEW.reviewer_id<>NEW.assigned_reviewer_id
 OR NEW.review_note='' OR NOT EXISTS(SELECT 1 FROM adc_clinical_reviewer r JOIN adc_user u ON u.id=r.user_id
 JOIN adc_clinical_encounter e ON e.id=enc JOIN adc_visit v ON v.id=e.visit_id
 WHERE r.id=NEW.reviewer_id AND r.user_id=NEW.reviewed_by_id AND r.clinic_id=v.clinic_id AND u.dentist_id<>author_dentist)) THEN
  RAISE EXCEPTION 'Archive review must retain a distinct appointed medical reviewer';
 END IF;
 IF NEW.state IN ('APPROVED','FAILED','PUBLISHED') AND (NEW.reviewed_at IS NULL OR NEW.reviewed_by_id IS NULL) THEN
  RAISE EXCEPTION 'Generation requires an independent medical approval'; END IF;
 IF NEW.state='PUBLISHED' AND NOT EXISTS(SELECT 1 FROM adc_archive_package WHERE submission_id=NEW.id) THEN
  RAISE EXCEPTION 'Archive publication requires its fixed file'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER archive_submission_retained BEFORE INSERT OR UPDATE OR DELETE ON adc_archive_submission
FOR EACH ROW EXECUTE FUNCTION adc_archive_submission_guard();

CREATE FUNCTION adc_archive_package_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Published archive bytes and manifests are immutable'; END IF;
 IF NOT EXISTS(SELECT 1 FROM adc_archive_submission s WHERE s.id=NEW.submission_id AND s.archive_id=NEW.archive_id AND s.state='APPROVED')
 OR NEW.pdf_sha256<>encode(sha256(NEW.pdf),'hex') OR octet_length(NEW.pdf)<100
 OR substring(NEW.pdf from 1 for 5)<>convert_to('%PDF-','UTF8') THEN
  RAISE EXCEPTION 'Archive requires its approved source and exact PDF bytes';
 END IF;
 IF (NEW.previous_id IS NULL AND NEW.number<>1) OR (NEW.previous_id IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM adc_archive_package WHERE id=NEW.previous_id AND archive_id=NEW.archive_id AND number=NEW.number-1)) THEN
  RAISE EXCEPTION 'Archive package must append to its own previous package'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER archive_package_retained BEFORE INSERT OR UPDATE OR DELETE ON adc_archive_package
FOR EACH ROW EXECUTE FUNCTION adc_archive_package_guard();

CREATE FUNCTION adc_archive_amendment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE enc bigint; r adc_clinical_record_version%ROWTYPE; d adc_clinical_document_version%ROWTYPE; p jsonb; findings jsonb;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Archive amendment requests are retained'; END IF;
 SELECT encounter_id INTO enc FROM adc_clinical_archive WHERE id=NEW.archive_id;
 IF NOT EXISTS(SELECT 1 FROM adc_archive_package b JOIN adc_archive_submission s ON s.id=b.submission_id
 WHERE b.id=NEW.base_package_id AND b.archive_id=NEW.archive_id AND s.kind='ARCHIVE') THEN
  RAISE EXCEPTION 'Amendment must reference its own completed archive'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['state','revision','reviewer_id','reviewed_by_id','reviewed_at','review_note','approval_scope','result_document_id','result_record_id'])
   IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','revision','reviewer_id','reviewed_by_id','reviewed_at','review_note','approval_scope','result_document_id','result_record_id'])
   OR NEW.revision<>OLD.revision+1 THEN RAISE EXCEPTION 'Exact proposed amendment and original basis are immutable'; END IF;
  IF NOT ((OLD.state='PENDING' AND NEW.state IN ('APPROVED','RETURNED','REJECTED','CANCELLED')) OR
          (OLD.state='APPROVED' AND NEW.state IN ('APPLIED','CANCELLED'))) THEN RAISE EXCEPTION 'Invalid archive amendment transition'; END IF;
  IF OLD.reviewed_at IS NOT NULL AND (NEW.reviewed_at,NEW.reviewed_by_id,NEW.reviewer_id,NEW.review_note,NEW.approval_scope)
   IS DISTINCT FROM (OLD.reviewed_at,OLD.reviewed_by_id,OLD.reviewer_id,OLD.review_note,OLD.approval_scope) THEN
   RAISE EXCEPTION 'Amendment review is retained'; END IF;
 END IF;
 IF NEW.reviewed_at IS NOT NULL AND (NEW.reviewed_by_id=NEW.requested_by_id OR NEW.reviewer_id<>NEW.assigned_reviewer_id OR NEW.review_note=''
 OR NOT EXISTS(SELECT 1 FROM adc_clinical_reviewer a JOIN adc_user u ON u.id=a.user_id JOIN adc_clinical_encounter e ON e.id=enc
 JOIN adc_visit v ON v.id=e.visit_id WHERE a.id=NEW.reviewer_id AND a.user_id=NEW.reviewed_by_id AND a.clinic_id=v.clinic_id AND u.dentist_id<>v.dentist_id)) THEN
  RAISE EXCEPTION 'Amendment requires a distinct appointed medical reviewer'; END IF;
 IF NEW.state IN ('APPROVED','APPLIED') AND NEW.reviewed_at IS NULL THEN RAISE EXCEPTION 'Amendment must be approved before application'; END IF;
 IF NEW.state='APPLIED' THEN
  p=NEW.candidate->'payload';
  IF NEW.target='DOCUMENT' THEN
   SELECT * INTO d FROM adc_clinical_document_version WHERE id=NEW.result_document_id;
   IF NOT FOUND OR d.confirmed_by_id<>NEW.requested_by_id OR d.content IS DISTINCT FROM p
   OR d.source_snapshot IS DISTINCT FROM NEW.candidate->'source'
   OR NOT EXISTS(SELECT 1 FROM adc_clinical_document WHERE id=d.document_id AND encounter_id=enc) THEN
    RAISE EXCEPTION 'Applied document must equal the approved amendment'; END IF;
  ELSE
   SELECT * INTO r FROM adc_clinical_record_version WHERE id=NEW.result_record_id;
   SELECT COALESCE(jsonb_agg(jsonb_build_object('tooth',f.tooth,'surface',f.surface,'kind',f.kind,'detail',f.detail) ORDER BY f.line_no),'[]'::jsonb)
    INTO findings FROM adc_tooth_finding f WHERE f.record_id=NEW.result_record_id;
   IF r.id IS NULL OR r.encounter_id<>enc OR r.recorded_by_id<>NEW.requested_by_id
   OR r.chief_complaint IS DISTINCT FROM p->>'chief_complaint' OR r.examination IS DISTINCT FROM p->>'examination'
   OR r.history_assessment IS DISTINCT FROM p->>'history_assessment' OR r.history_discrepancy IS DISTINCT FROM p->>'history_discrepancy'
   OR r.history_review IS DISTINCT FROM p->>'history_review' OR r.dentition IS DISTINCT FROM p->>'dentition'
   OR r.history_id IS DISTINCT FROM (p->>'history_id')::bigint OR r.observed_at IS DISTINCT FROM (p->>'observed_at')::timestamptz
   OR r.amendment_reason IS DISTINCT FROM p->>'amendment_reason' OR findings IS DISTINCT FROM p->'findings' THEN
    RAISE EXCEPTION 'Applied examination must equal the approved amendment'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER archive_amendment_retained BEFORE INSERT OR UPDATE OR DELETE ON adc_archive_amendment
FOR EACH ROW EXECUTE FUNCTION adc_archive_amendment_guard();

CREATE TRIGGER archive_event_retained BEFORE UPDATE OR DELETE ON adc_archive_event
FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();

CREATE FUNCTION adc_archived_version_requires_review() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE enc bigint; required boolean;
BEGIN
 IF TG_TABLE_NAME='adc_clinical_document_version' THEN
  SELECT encounter_id INTO enc FROM adc_clinical_document WHERE id=NEW.document_id;
  SELECT EXISTS(SELECT 1 FROM adc_archive_package b JOIN adc_archive_submission s ON s.id=b.submission_id
   JOIN adc_clinical_document_version d ON d.id=s.document_version_id JOIN adc_clinical_archive a ON a.id=b.archive_id
   WHERE a.encounter_id=enc AND s.kind='ARCHIVE' AND d.revision<NEW.revision) INTO required;
  IF required AND NOT EXISTS(SELECT 1 FROM adc_archive_amendment WHERE target='DOCUMENT' AND state='APPLIED' AND result_document_id=NEW.id) THEN
   RAISE EXCEPTION 'Archived document requires a prior independent exact-content amendment'; END IF;
 ELSE
  SELECT EXISTS(SELECT 1 FROM adc_archive_package b JOIN adc_archive_submission s ON s.id=b.submission_id
   JOIN adc_clinical_document_version d ON d.id=s.document_version_id JOIN adc_clinical_record_version r ON r.id=d.source_record_id
   JOIN adc_clinical_archive a ON a.id=b.archive_id WHERE a.encounter_id=NEW.encounter_id AND s.kind='ARCHIVE' AND r.revision<NEW.revision) INTO required;
  IF required AND NOT EXISTS(SELECT 1 FROM adc_archive_amendment WHERE target='RECORD' AND state='APPLIED' AND result_record_id=NEW.id) THEN
   RAISE EXCEPTION 'Archived examination requires a prior independent exact-content amendment'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER archived_document_review AFTER INSERT ON adc_clinical_document_version
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_archived_version_requires_review();
CREATE CONSTRAINT TRIGGER archived_record_review AFTER INSERT ON adc_clinical_record_version
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_archived_version_requires_review();
'''

REVERSE='''
DROP TRIGGER archived_record_review ON adc_clinical_record_version;
DROP TRIGGER archived_document_review ON adc_clinical_document_version;
DROP FUNCTION adc_archived_version_requires_review();
DROP TRIGGER archive_event_retained ON adc_archive_event;
DROP TRIGGER archive_amendment_retained ON adc_archive_amendment;
DROP FUNCTION adc_archive_amendment_guard();
DROP TRIGGER archive_package_retained ON adc_archive_package;
DROP FUNCTION adc_archive_package_guard();
DROP TRIGGER archive_submission_retained ON adc_archive_submission;
DROP FUNCTION adc_archive_submission_guard();
DROP TRIGGER archive_head_retained ON adc_clinical_archive;
DROP FUNCTION adc_archive_head_guard();
'''


class Migration(migrations.Migration):
    dependencies=[('clinical','0013_medical_archives')]
    operations=[migrations.RunSQL(SQL,REVERSE),migrations.RunPython(migrations.RunPython.noop,preserve)]
