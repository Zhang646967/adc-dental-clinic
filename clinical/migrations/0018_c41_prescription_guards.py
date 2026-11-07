from django.db import migrations


SQL = """
CREATE FUNCTION adc_prescription_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_visit bigint; target_visit bigint; owner_id bigint; target_clinic bigint;
BEGIN
 SELECT r.visit_id INTO source_visit FROM adc_clinical_encounter r
 JOIN adc_clinical_record_version v ON v.encounter_id=r.id WHERE v.id=NEW.record_id;
 SELECT p.visit_id,p.prescriber_id,v.clinic_id INTO target_visit,owner_id,target_clinic
 FROM adc_prescription p JOIN adc_visit v ON v.id=p.visit_id WHERE p.id=NEW.prescription_id;
 IF source_visit IS DISTINCT FROM target_visit OR NOT EXISTS (
  SELECT 1 FROM adc_prescription_duty d WHERE d.id=NEW.prescriber_duty_id
  AND d.user_id=owner_id AND d.clinic_id=target_clinic AND d.kind='PRESCRIBE'
 ) OR NOT EXISTS (
  SELECT 1 FROM adc_professional_authorization a WHERE a.id=NEW.clinical_scope_id
  AND a.user_id=owner_id AND a.clinic_id=target_clinic
 ) THEN RAISE EXCEPTION 'Prescription source and prescriber scope must match'; END IF;
 IF jsonb_typeof(NEW.items) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.items) NOT BETWEEN 1 AND 5
 THEN RAISE EXCEPTION 'A prescription needs a bounded retained item list'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_prescription_decision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_id bigint; target_clinic bigint;
BEGIN
 SELECT p.prescriber_id,v.clinic_id INTO owner_id,target_clinic FROM adc_prescription_version r
 JOIN adc_prescription p ON p.id=r.prescription_id JOIN adc_visit v ON v.id=p.visit_id
 WHERE r.id=NEW.version_id;
 IF (NEW.actor_id=owner_id) IS DISTINCT FROM (NEW.action='WITHDRAWN') OR NOT EXISTS (
  SELECT 1 FROM adc_prescription_duty d WHERE d.id=NEW.duty_id
  AND d.user_id=NEW.actor_id AND d.clinic_id=target_clinic
  AND d.kind=CASE WHEN NEW.action='WITHDRAWN' THEN 'PRESCRIBE' ELSE 'REVIEW' END
 ) THEN RAISE EXCEPTION 'Prescription decision needs the proper independent actor and scope'; END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER rx_version_scope BEFORE INSERT ON adc_prescription_version
FOR EACH ROW EXECUTE FUNCTION adc_prescription_version_guard();
CREATE TRIGGER rx_decision_scope BEFORE INSERT ON adc_prescription_decision
FOR EACH ROW EXECUTE FUNCTION adc_prescription_decision_guard();
CREATE TRIGGER rx_header_retained BEFORE UPDATE OR DELETE ON adc_prescription
FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();
CREATE TRIGGER rx_version_retained BEFORE UPDATE OR DELETE ON adc_prescription_version
FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();
CREATE TRIGGER rx_decision_retained BEFORE UPDATE OR DELETE ON adc_prescription_decision
FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();
"""

REVERSE_SQL = """
DROP TRIGGER rx_decision_retained ON adc_prescription_decision;
DROP TRIGGER rx_version_retained ON adc_prescription_version;
DROP TRIGGER rx_header_retained ON adc_prescription;
DROP TRIGGER rx_decision_scope ON adc_prescription_decision;
DROP TRIGGER rx_version_scope ON adc_prescription_version;
DROP FUNCTION adc_prescription_decision_guard();
DROP FUNCTION adc_prescription_version_guard();
"""


def protect_prescription_history(apps, schema_editor):
    db = schema_editor.connection.alias
    for name in ('Prescription', 'PrescriptionVersion', 'PrescriptionDecision',
                 'PrescriptionCatalogueItem', 'PrescriptionDuty'):
        if apps.get_model('clinical', name).objects.using(db).exists():
            raise RuntimeError('Prescription history or duties exist; reversing the prescription schema is refused.')
    for app, name in (('accounts', 'RoleAssignment'), ('workspaces', 'WorkspaceContext')):
        if apps.get_model(app, name).objects.using(db).filter(role='PHARMACIST').exists():
            raise RuntimeError('Pharmacy roles or workspaces exist; reversing the prescription schema is refused.')


class Migration(migrations.Migration):
    dependencies = [
        ('clinical', '0017_c41_prescriptions'),
        ('accounts', '0008_c41_prescriptions'),
        ('workspaces', '0005_c41_prescriptions'),
    ]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(migrations.RunPython.noop, protect_prescription_history),
    ]
