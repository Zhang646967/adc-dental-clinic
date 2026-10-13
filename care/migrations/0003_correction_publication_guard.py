from django.db import migrations
SQL="""
CREATE FUNCTION adc_validate_correction_publication() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r adc_visit_record_version%ROWTYPE; c adc_correction_request%ROWTYPE;
BEGIN
  SELECT * INTO r FROM adc_visit_record_version WHERE id=NEW.current_record_version_id;
  IF r.previous_version_id IS NULL THEN
    IF r.revision_no<>1 OR r.correction_request_id IS NOT NULL THEN
      RAISE EXCEPTION 'first publication must be revision one' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT * INTO c FROM adc_correction_request WHERE id=r.correction_request_id;
    IF NOT FOUND OR c.status<>'APPLIED' OR c.visit_id<>NEW.visit_id OR c.base_record_version_id<>r.previous_version_id
       OR c.reviewer_id IS NULL OR c.reviewer_id=c.requester_id OR r.reviewed_by_id IS NULL OR r.reviewed_by_id<>c.reviewer_id THEN
      RAISE EXCEPTION 'correction requires a matching independent approval' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM adc_visit_record_version p WHERE p.id=r.previous_version_id AND p.visit_id=r.visit_id AND p.revision_no<r.revision_no AND p.state='PUBLISHED') THEN
      RAISE EXCEPTION 'invalid predecessor revision' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_OP='UPDATE' AND NEW.current_record_version_id<>OLD.current_record_version_id THEN
    IF r.previous_version_id IS DISTINCT FROM OLD.current_record_version_id THEN
      RAISE EXCEPTION 'current invoice must advance from its current revision' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER invoice_correction_approval
AFTER INSERT OR UPDATE ON adc_invoice DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION adc_validate_correction_publication();
CREATE FUNCTION adc_protect_closed_correction() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status<>'OPEN' THEN
    RAISE EXCEPTION 'resolved corrections are immutable' USING ERRCODE='23514';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER correction_history_guard BEFORE UPDATE OR DELETE ON adc_correction_request
FOR EACH ROW EXECUTE FUNCTION adc_protect_closed_correction();
"""
REVERSE="""
DROP TRIGGER IF EXISTS correction_history_guard ON adc_correction_request;
DROP TRIGGER IF EXISTS invoice_correction_approval ON adc_invoice;
DROP FUNCTION IF EXISTS adc_protect_closed_correction();
DROP FUNCTION IF EXISTS adc_validate_correction_publication();
"""
class Migration(migrations.Migration):
    dependencies=[('care','0002_database_guards')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
