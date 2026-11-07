from importlib import import_module
from django.db import migrations


# Restore only the preceding visit routine. Its existing triggers stay installed.
PREVIOUS_VISIT = import_module('clinical.migrations.0004_staged_actual_care_guard').FORWARD_SQL.split(
    'CREATE OR REPLACE FUNCTION adc_performed_procedure_guard()', 1,
)[0]

SQL = """
CREATE OR REPLACE FUNCTION adc_validate_visit(p_id bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE v adc_visit%ROWTYPE; i adc_invoice%ROWTYPE; r adc_visit_record_version%ROWTYPE;
        n bigint; successor_count bigint; total numeric; bad bigint; staged boolean; medicine_count bigint; medicine_total numeric;
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
  SELECT count(*),coalesce(sum(line_amount),0) INTO medicine_count,medicine_total
    FROM adc_medication_charge WHERE record_version_id=r.id;
  IF total+medicine_total<>r.total_amount OR bad<>0 THEN
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
  IF v.status='COMPLETED' THEN
    IF r.outcome='PHARMACY_ONLY' THEN
      IF medicine_count=0 OR n<>0 OR EXISTS (
        SELECT 1 FROM adc_performed_procedure p JOIN adc_clinical_encounter e ON e.id=p.encounter_id
        WHERE e.visit_id=p_id AND p.state='ACTIVE'
      ) THEN RAISE EXCEPTION 'pharmacy-only completion requires only physical dispensing' USING ERRCODE='23514'; END IF;
    ELSIF r.outcome<>'TREATED' OR (n=0 AND NOT staged) THEN
      RAISE EXCEPTION 'treated completion requires actual treatment lines or an explicit staged procedure' USING ERRCODE='23514';
    END IF;
  END IF;
  IF v.status='CLOSED_NO_TREATMENT' AND (r.outcome<>'NO_TREATMENT' OR n<>0 OR medicine_count<>0 OR total<>0 OR btrim(r.no_treatment_reason)='' OR EXISTS (SELECT 1 FROM adc_performed_procedure p JOIN adc_clinical_encounter e ON e.id=p.encounter_id WHERE e.visit_id=p_id AND p.state='ACTIVE')) THEN
    RAISE EXCEPTION 'no-treatment closure requires zero lines/amount and a reason' USING ERRCODE='23514';
  END IF;
END $$;
CREATE FUNCTION adc_guard_medication_charge() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual bigint; gross bigint; price numeric;
BEGIN
 SELECT l.unit_price INTO price FROM adc_pharmacy_quote_line l
 JOIN adc_pharmacy_quote q ON q.id=l.quote_id JOIN adc_prescription_decision d ON d.id=q.approval_id
 JOIN adc_prescription_version r ON r.id=d.version_id JOIN adc_prescription p ON p.id=r.prescription_id
 JOIN adc_visit_record_version c ON c.visit_id=p.visit_id AND c.id=NEW.record_version_id
 JOIN adc_dispense_movement m ON m.line_id=l.id AND m.id=NEW.through_movement_id
 WHERE l.id=NEW.quote_line_id;
 SELECT coalesce(sum(CASE WHEN kind='ISSUE' THEN quantity ELSE -quantity END),0),
        coalesce(sum(quantity) FILTER (WHERE kind='ISSUE'),0) INTO actual,gross
 FROM adc_dispense_movement WHERE line_id=NEW.quote_line_id AND id<=NEW.through_movement_id;
 IF price IS NULL OR gross=0 OR actual<>NEW.quantity OR price*NEW.quantity<>NEW.line_amount THEN
  RAISE EXCEPTION 'Medication charge requires matching physical facts and retained price' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_check_invoice_medication() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_version bigint; scope text;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF NEW.current_record_version_id=OLD.current_record_version_id THEN RETURN NULL; END IF;
  old_version=OLD.current_record_version_id;
  SELECT c.proposed_change->>'scope' INTO scope FROM adc_correction_request c
  JOIN adc_visit_record_version r ON r.correction_request_id=c.id WHERE r.id=NEW.current_record_version_id;
 END IF;
 IF old_version IS NULL OR scope='medication_returns' THEN
  IF EXISTS (
   WITH expected AS (
    SELECT m.line_id AS quote_line_id,max(m.id) AS through_movement_id
    FROM adc_dispense_movement m JOIN adc_pharmacy_quote_line l ON l.id=m.line_id
    JOIN adc_pharmacy_quote q ON q.id=l.quote_id JOIN adc_prescription_decision d ON d.id=q.approval_id
    JOIN adc_prescription_version r ON r.id=d.version_id JOIN adc_prescription p ON p.id=r.prescription_id
    WHERE p.visit_id=NEW.visit_id GROUP BY m.line_id
   ), actual AS (
    SELECT quote_line_id,through_movement_id FROM adc_medication_charge
    WHERE record_version_id=NEW.current_record_version_id
   )
   SELECT 1 FROM expected FULL JOIN actual USING (quote_line_id,through_movement_id)
   WHERE expected.quote_line_id IS NULL OR actual.quote_line_id IS NULL
  ) THEN
   RAISE EXCEPTION 'Invoice must include each current dispensing source' USING ERRCODE='23514';
  END IF;
 ELSIF EXISTS (
  WITH previous AS (
   SELECT quote_line_id,through_movement_id FROM adc_medication_charge WHERE record_version_id=old_version
  ), current_lines AS (
   SELECT quote_line_id,through_movement_id FROM adc_medication_charge WHERE record_version_id=NEW.current_record_version_id
  )
  SELECT 1 FROM previous FULL JOIN current_lines USING (quote_line_id,through_movement_id)
  WHERE previous.quote_line_id IS NULL OR current_lines.quote_line_id IS NULL
 ) THEN
  RAISE EXCEPTION 'Only an approved return correction can change medication charges' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;

CREATE TRIGGER medication_charge_published_guard BEFORE INSERT OR UPDATE OR DELETE ON adc_medication_charge
FOR EACH ROW EXECUTE FUNCTION adc_protect_published_line();
CREATE TRIGGER medication_charge_source BEFORE INSERT OR UPDATE ON adc_medication_charge
FOR EACH ROW EXECUTE FUNCTION adc_guard_medication_charge();
CREATE CONSTRAINT TRIGGER invoice_medication_publication AFTER INSERT OR UPDATE ON adc_invoice
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_check_invoice_medication();
"""

REVERSE_SQL = """
DROP TRIGGER invoice_medication_publication ON adc_invoice;
DROP TRIGGER medication_charge_source ON adc_medication_charge;
DROP TRIGGER medication_charge_published_guard ON adc_medication_charge;
DROP FUNCTION adc_check_invoice_medication();
DROP FUNCTION adc_guard_medication_charge();
""" + PREVIOUS_VISIT


def protect_charge_history(apps, schema_editor):
    database = schema_editor.connection.alias
    if apps.get_model('care', 'MedicationCharge').objects.using(database).exists():
        raise RuntimeError('Medication billing history exists; reversing its schema is refused.')


class Migration(migrations.Migration):
    dependencies = [
        ('clinical', '0020_c42_pharmacy_guards'),
        ('care', '0004_c42_medication_charges'),
    ]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(migrations.RunPython.noop, protect_charge_history),
    ]
