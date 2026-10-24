"""Retain all care guards and admit only explicitly recorded staged actual care."""
from django.db import migrations


def protect_actual_history(apps,schema_editor):
    if apps.get_model('clinical','PerformedProcedure').objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError('Actual procedure history exists; reversing its care invariant is refused.')

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION adc_validate_visit(p_id bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE v adc_visit%ROWTYPE; i adc_invoice%ROWTYPE; r adc_visit_record_version%ROWTYPE;
        n bigint; successor_count bigint; total numeric; bad bigint; staged boolean;
BEGIN
  SELECT * INTO v FROM adc_visit WHERE id=p_id;
  IF NOT FOUND THEN RETURN; END IF;
  SELECT count(*) INTO successor_count FROM adc_visit WHERE replaces_visit_id=p_id;
  IF (v.status='RESCHEDULED') IS DISTINCT FROM (successor_count=1) THEN
    RAISE EXCEPTION 'rescheduling requires exactly one successor' USING ERRCODE='23514';
  END IF;
  IF v.replaces_visit_id IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM adc_visit p WHERE p.id=v.replaces_visit_id AND p.id<v.id AND p.patient_id=v.patient_id AND p.status='RESCHEDULED') THEN
      RAISE EXCEPTION 'invalid rescheduling history' USING ERRCODE='23514';
    END IF;
  END IF;
  SELECT * INTO i FROM adc_invoice WHERE visit_id=p_id;
  IF v.status NOT IN ('COMPLETED','CLOSED_NO_TREATMENT') THEN
    IF FOUND THEN RAISE EXCEPTION 'unfinished visit cannot have an invoice' USING ERRCODE='23514'; END IF;
    IF EXISTS (SELECT 1 FROM adc_visit_record_version WHERE visit_id=p_id AND state='PUBLISHED') THEN
      RAISE EXCEPTION 'unfinished visit cannot have published content' USING ERRCODE='23514';
    END IF;
    RETURN;
  END IF;
  IF NOT FOUND THEN RAISE EXCEPTION 'closed visit requires an invoice' USING ERRCODE='23514'; END IF;
  SELECT * INTO r FROM adc_visit_record_version WHERE id=i.current_record_version_id;
  IF NOT FOUND OR r.visit_id<>p_id OR r.state<>'PUBLISHED' THEN
    RAISE EXCEPTION 'invoice requires a published version of the same visit' USING ERRCODE='23514';
  END IF;
  SELECT count(*),coalesce(sum(line_amount),0),count(*) FILTER(WHERE confirmed_by_id IS NULL OR confirmed_at IS NULL)
    INTO n,total,bad FROM adc_treatment_record WHERE record_version_id=r.id;
  IF total<>r.total_amount OR bad<>0 THEN
    RAISE EXCEPTION 'published total or confirmation inconsistent' USING ERRCODE='23514';
  END IF;
  SELECT EXISTS (
    SELECT 1 FROM adc_performed_procedure p
    JOIN adc_clinical_encounter e ON e.id=p.encounter_id
    JOIN adc_clinical_record_version c ON c.id=p.source_record_id AND c.encounter_id=e.id
    JOIN adc_plan_step_version s ON s.id=p.step_version_id
    WHERE e.visit_id=p_id AND p.state='ACTIVE' AND p.charge_mode='NO_CHARGE'
      AND p.progress='PARTIAL' AND p.charge_line_id IS NULL AND s.charge_basis='ON_COMPLETION'
  ) INTO staged;
  IF v.status='COMPLETED' AND (r.outcome<>'TREATED' OR (n=0 AND NOT staged)) THEN
    RAISE EXCEPTION 'treated completion requires actual treatment lines or an explicit staged procedure' USING ERRCODE='23514';
  END IF;
  IF v.status='CLOSED_NO_TREATMENT' AND (r.outcome<>'NO_TREATMENT' OR n<>0 OR total<>0 OR btrim(r.no_treatment_reason)='' OR EXISTS (SELECT 1 FROM adc_performed_procedure p JOIN adc_clinical_encounter e ON e.id=p.encounter_id WHERE e.visit_id=p_id AND p.state='ACTIVE')) THEN
    RAISE EXCEPTION 'no-treatment closure requires zero lines/amount and a reason' USING ERRCODE='23514';
  END IF;
END $$;
CREATE OR REPLACE FUNCTION adc_performed_procedure_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR NOT EXISTS (SELECT 1 FROM adc_clinical_encounter e JOIN adc_visit v ON v.id=e.visit_id WHERE e.id=OLD.encounter_id AND v.status='CHECKED_IN') OR
    (to_jsonb(OLD)-'state'-'revision'-'charge_line_id') IS DISTINCT FROM (to_jsonb(NEW)-'state'-'revision'-'charge_line_id') OR
    OLD.state<>'ACTIVE' OR NEW.state<>'VOIDED' OR NEW.revision<>OLD.revision+1 OR NEW.charge_line_id IS NOT NULL THEN
  RAISE EXCEPTION 'Actual procedure source and charge history are retained';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION adc_check_performed_final() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE visit_id bigint;
BEGIN
 SELECT e.visit_id INTO visit_id FROM adc_clinical_encounter e WHERE e.id=NEW.encounter_id;
 PERFORM adc_validate_visit(visit_id);
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER performed_visit_final_consistency
AFTER INSERT OR UPDATE ON adc_performed_procedure DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION adc_check_performed_final();
"""

REVERSE_SQL = r"""
DROP TRIGGER performed_visit_final_consistency ON adc_performed_procedure;
DROP FUNCTION adc_check_performed_final();
CREATE OR REPLACE FUNCTION adc_validate_visit(p_id bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE v adc_visit%ROWTYPE; i adc_invoice%ROWTYPE; r adc_visit_record_version%ROWTYPE;
        n bigint; successor_count bigint; total numeric; bad bigint;
BEGIN
  SELECT * INTO v FROM adc_visit WHERE id=p_id;
  IF NOT FOUND THEN RETURN; END IF;
  SELECT count(*) INTO successor_count FROM adc_visit WHERE replaces_visit_id=p_id;
  IF (v.status='RESCHEDULED') IS DISTINCT FROM (successor_count=1) THEN
    RAISE EXCEPTION 'rescheduling requires exactly one successor' USING ERRCODE='23514';
  END IF;
  IF v.replaces_visit_id IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM adc_visit p WHERE p.id=v.replaces_visit_id AND p.id<v.id AND p.patient_id=v.patient_id AND p.status='RESCHEDULED') THEN
      RAISE EXCEPTION 'invalid rescheduling history' USING ERRCODE='23514';
    END IF;
  END IF;
  SELECT * INTO i FROM adc_invoice WHERE visit_id=p_id;
  IF v.status NOT IN ('COMPLETED','CLOSED_NO_TREATMENT') THEN
    IF FOUND THEN RAISE EXCEPTION 'unfinished visit cannot have an invoice' USING ERRCODE='23514'; END IF;
    IF EXISTS (SELECT 1 FROM adc_visit_record_version WHERE visit_id=p_id AND state='PUBLISHED') THEN
      RAISE EXCEPTION 'unfinished visit cannot have published content' USING ERRCODE='23514';
    END IF;
    RETURN;
  END IF;
  IF NOT FOUND THEN RAISE EXCEPTION 'closed visit requires an invoice' USING ERRCODE='23514'; END IF;
  SELECT * INTO r FROM adc_visit_record_version WHERE id=i.current_record_version_id;
  IF NOT FOUND OR r.visit_id<>p_id OR r.state<>'PUBLISHED' THEN
    RAISE EXCEPTION 'invoice requires a published version of the same visit' USING ERRCODE='23514';
  END IF;
  SELECT count(*),coalesce(sum(line_amount),0),count(*) FILTER(WHERE confirmed_by_id IS NULL OR confirmed_at IS NULL)
    INTO n,total,bad FROM adc_treatment_record WHERE record_version_id=r.id;
  IF total<>r.total_amount OR bad<>0 THEN
    RAISE EXCEPTION 'published total or confirmation inconsistent' USING ERRCODE='23514';
  END IF;
  IF v.status='COMPLETED' AND (r.outcome<>'TREATED' OR n=0) THEN
    RAISE EXCEPTION 'treated completion requires actual treatment lines' USING ERRCODE='23514';
  END IF;
  IF v.status='CLOSED_NO_TREATMENT' AND (r.outcome<>'NO_TREATMENT' OR n<>0 OR total<>0 OR btrim(r.no_treatment_reason)='') THEN
    RAISE EXCEPTION 'no-treatment closure requires zero lines/amount and a reason' USING ERRCODE='23514';
  END IF;
END $$;
CREATE OR REPLACE FUNCTION adc_performed_procedure_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR
    (to_jsonb(OLD)-'state'-'revision'-'charge_line_id') IS DISTINCT FROM (to_jsonb(NEW)-'state'-'revision'-'charge_line_id') OR
    OLD.state<>'ACTIVE' OR NEW.state<>'VOIDED' OR NEW.revision<>OLD.revision+1 OR NEW.charge_line_id IS NOT NULL THEN
  RAISE EXCEPTION 'Actual procedure source and charge history are retained';
 END IF;
 RETURN NEW;
END $$;
"""

class Migration(migrations.Migration):
    dependencies=[('clinical','0003_treatment_continuity')]
    operations=[migrations.RunSQL(FORWARD_SQL,reverse_sql=REVERSE_SQL),
        migrations.RunPython(migrations.RunPython.noop,protect_actual_history)]
