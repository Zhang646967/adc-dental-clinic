from django.db import migrations


SQL = """
CREATE FUNCTION adc_pharmacy_visit(p_approval bigint, p_actor bigint, p_duty bigint)
RETURNS adc_visit LANGUAGE plpgsql AS $$
DECLARE result adc_visit%ROWTYPE;
BEGIN
 SELECT v.* INTO result FROM adc_visit v
 JOIN adc_prescription p ON p.visit_id=v.id
 JOIN adc_prescription_version r ON r.prescription_id=p.id
 JOIN adc_prescription_decision d ON d.version_id=r.id
 JOIN adc_prescription_duty duty ON duty.id=p_duty AND duty.kind='DISPENSE'
  AND duty.user_id=p_actor AND duty.clinic_id=v.clinic_id
 WHERE d.id=p_approval AND d.action='APPROVED' AND p.prescriber_id<>p_actor
   AND NOT EXISTS (SELECT 1 FROM adc_prescription_version newer WHERE newer.prescription_id=p.id AND newer.number>r.number)
 FOR UPDATE OF v;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Pharmacy event requires an independent scoped actor and current approved version' USING ERRCODE='23514';
 END IF;
 RETURN result;
END $$;

CREATE FUNCTION adc_guard_pharmacy_header() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v adc_visit%ROWTYPE; operator_id bigint;
BEGIN
 IF TG_TABLE_NAME='adc_pharmacy_quote' THEN operator_id=NEW.prepared_by_id;
 ELSE operator_id=NEW.actor_id;
 END IF;
 v=adc_pharmacy_visit(NEW.approval_id,operator_id,NEW.duty_id);
 IF v.status<>'CHECKED_IN' OR (
  TG_TABLE_NAME='adc_pharmacy_quote' AND EXISTS (SELECT 1 FROM adc_pharmacy_stop s WHERE s.approval_id=NEW.approval_id)
 ) THEN
  RAISE EXCEPTION 'New quote or stop requires an open dispensing encounter' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_guard_pharmacy_line() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM adc_pharmacy_quote q
  JOIN adc_prescription_decision d ON d.id=q.approval_id
  JOIN adc_prescription_version r ON r.id=d.version_id
  JOIN adc_prescription p ON p.id=r.prescription_id
  JOIN adc_visit v ON v.id=p.visit_id AND v.status='CHECKED_IN'
  JOIN adc_prescription_catalogue_item i ON i.id=NEW.item_id AND i.clinic_id=v.clinic_id
  CROSS JOIN LATERAL jsonb_array_elements(r.items) AS entry
  WHERE q.id=NEW.quote_id AND i.is_active AND i.rehearsal_unit_price=NEW.unit_price
    AND (entry->>'item_id')::bigint=i.id AND entry->>'name'=NEW.name_snapshot
    AND entry->>'quantity_unit'=NEW.unit_snapshot AND (entry->>'quantity')::int=NEW.ordered_quantity
 ) THEN
  RAISE EXCEPTION 'Quote line must match an approved retained item and its clinic price' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_check_pharmacy_quote_lines() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT count(*) FROM adc_pharmacy_quote_line l WHERE l.quote_id=NEW.id)
   <> (SELECT jsonb_array_length(r.items) FROM adc_prescription_version r
       JOIN adc_prescription_decision d ON d.version_id=r.id WHERE d.id=NEW.approval_id)
 THEN
  RAISE EXCEPTION 'Quote must contain all approved items' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION adc_guard_dispense_movement() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v adc_visit%ROWTYPE; approval bigint; ordered integer; original integer; used bigint;
BEGIN
 SELECT q.approval_id,l.ordered_quantity INTO approval,ordered FROM adc_pharmacy_quote_line l
 JOIN adc_pharmacy_quote q ON q.id=l.quote_id WHERE l.id=NEW.line_id;
 v=adc_pharmacy_visit(approval,NEW.actor_id,NEW.duty_id);
 IF NEW.kind='ISSUE' THEN
  SELECT coalesce(sum(quantity),0) INTO used FROM adc_dispense_movement WHERE line_id=NEW.line_id AND kind='ISSUE';
  IF v.status<>'CHECKED_IN' OR used+NEW.quantity>ordered OR
     EXISTS (SELECT 1 FROM adc_pharmacy_stop s WHERE s.approval_id=approval) THEN
   RAISE EXCEPTION 'Issuance exceeds the remaining open prescription' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT quantity INTO original FROM adc_dispense_movement
  WHERE id=NEW.original_issue_id AND line_id=NEW.line_id AND kind='ISSUE';
  SELECT coalesce(sum(quantity),0) INTO used FROM adc_dispense_movement WHERE original_issue_id=NEW.original_issue_id;
  IF v.status NOT IN ('CHECKED_IN','COMPLETED') OR original IS NULL OR used+NEW.quantity>original THEN
   RAISE EXCEPTION 'Return exceeds the matching original issue' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER pharmacy_quote_scope BEFORE INSERT ON adc_pharmacy_quote
FOR EACH ROW EXECUTE FUNCTION adc_guard_pharmacy_header();
CREATE TRIGGER pharmacy_stop_scope BEFORE INSERT ON adc_pharmacy_stop
FOR EACH ROW EXECUTE FUNCTION adc_guard_pharmacy_header();
CREATE TRIGGER pharmacy_line_scope BEFORE INSERT ON adc_pharmacy_quote_line
FOR EACH ROW EXECUTE FUNCTION adc_guard_pharmacy_line();
CREATE CONSTRAINT TRIGGER pharmacy_quote_complete AFTER INSERT ON adc_pharmacy_quote
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_check_pharmacy_quote_lines();
CREATE TRIGGER dispense_scope BEFORE INSERT ON adc_dispense_movement
FOR EACH ROW EXECUTE FUNCTION adc_guard_dispense_movement();

CREATE TRIGGER pharmacy_quote_retained BEFORE UPDATE OR DELETE ON adc_pharmacy_quote
FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();
CREATE TRIGGER pharmacy_line_retained BEFORE UPDATE OR DELETE ON adc_pharmacy_quote_line
FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();
CREATE TRIGGER pharmacy_stop_retained BEFORE UPDATE OR DELETE ON adc_pharmacy_stop
FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();
CREATE TRIGGER dispense_retained BEFORE UPDATE OR DELETE ON adc_dispense_movement
FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();
"""

REVERSE_SQL = """
DROP TRIGGER dispense_retained ON adc_dispense_movement;
DROP TRIGGER pharmacy_stop_retained ON adc_pharmacy_stop;
DROP TRIGGER pharmacy_line_retained ON adc_pharmacy_quote_line;
DROP TRIGGER pharmacy_quote_retained ON adc_pharmacy_quote;
DROP TRIGGER dispense_scope ON adc_dispense_movement;
DROP TRIGGER pharmacy_quote_complete ON adc_pharmacy_quote;
DROP TRIGGER pharmacy_line_scope ON adc_pharmacy_quote_line;
DROP TRIGGER pharmacy_stop_scope ON adc_pharmacy_stop;
DROP TRIGGER pharmacy_quote_scope ON adc_pharmacy_quote;
DROP FUNCTION adc_guard_dispense_movement();
DROP FUNCTION adc_check_pharmacy_quote_lines();
DROP FUNCTION adc_guard_pharmacy_line();
DROP FUNCTION adc_guard_pharmacy_header();
DROP FUNCTION adc_pharmacy_visit(bigint,bigint,bigint);
"""


def protect_pharmacy_history(apps, schema_editor):
    database = schema_editor.connection.alias
    for name in ('PharmacyQuote', 'PharmacyStop', 'DispenseMovement'):
        if apps.get_model('clinical', name).objects.using(database).exists():
            raise RuntimeError('Dispensing history exists; reversing its schema is refused.')
    if (apps.get_model('clinical', 'PrescriptionDuty').objects.using(database).filter(kind='DISPENSE').exists()
            or apps.get_model('clinical', 'PrescriptionCatalogueItem').objects.using(database)
            .filter(rehearsal_unit_price__isnull=False).exists()):
        raise RuntimeError('Dispensing duties or prices exist; reversing their schema is refused.')


class Migration(migrations.Migration):
    dependencies = [('clinical', '0019_c42_dispensing')]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(migrations.RunPython.noop, protect_pharmacy_history),
    ]
