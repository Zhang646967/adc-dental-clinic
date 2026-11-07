from django.db import migrations


RETAINED = (
    'stock_item','stock_lot','stock_movement','stock_recall','nursing_execution','sterile_pack','sterile_hold',
)

SQL = """
CREATE FUNCTION adc_stock_balance(p_lot bigint) RETURNS bigint LANGUAGE sql STABLE AS $$
 SELECT coalesce(sum(CASE
  WHEN kind IN ('RECEIPT','REVERSE_OUT') THEN quantity
  WHEN kind IN ('ISSUE','USE','WASTE','REVERSE_IN') THEN -quantity
  ELSE 0 END),0) FROM adc_stock_movement WHERE lot_id=p_lot
$$;

CREATE FUNCTION adc_guard_stock_item() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.kind='DRUG' AND NOT EXISTS (
  SELECT 1 FROM adc_prescription_catalogue_item p WHERE p.id=NEW.prescription_item_id
  AND p.clinic_id=NEW.clinic_id AND p.quantity_unit=NEW.unit
 ) THEN RAISE EXCEPTION 'Drug inventory needs a matching clinic item and unit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_stock_operator(p_actor bigint,p_clinic bigint,p_kind text)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS (SELECT 1 FROM adc_role_assignment a JOIN adc_user u ON u.id=a.user_id
  WHERE a.user_id=p_actor AND a.clinic_id=p_clinic AND a.is_active AND u.is_active AND a.scope_kind='CLINIC'
  AND (a.role='MANAGER' AND p_kind IN ('MATERIAL','IMPLANT') OR a.role='PHARMACIST' AND p_kind='DRUG'
   AND EXISTS (SELECT 1 FROM adc_prescription_duty d WHERE d.user_id=p_actor AND d.clinic_id=p_clinic
       AND d.kind='DISPENSE' AND d.revoked_at IS NULL AND now()>=d.valid_from AND now()<d.valid_until)))
$$;

CREATE FUNCTION adc_guard_stock_recall() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE clinic bigint; item_kind text;
BEGIN
 SELECT i.clinic_id,i.kind INTO clinic,item_kind FROM adc_stock_lot l JOIN adc_stock_item i ON i.id=l.item_id
 WHERE l.id=NEW.lot_id FOR UPDATE OF l;
 IF NOT adc_stock_operator(NEW.actor_id,clinic,item_kind) OR btrim(NEW.reference)='' OR btrim(NEW.reason)='' THEN
  RAISE EXCEPTION 'Recall needs a scoped actor and retained basis' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_guard_stock_movement() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE clinic bigint; item_kind text; rx_item bigint; expiry date; unit text; balance bigint; source_valid boolean;
BEGIN
 SELECT i.clinic_id,i.kind,i.prescription_item_id,l.expires_on,i.unit INTO clinic,item_kind,rx_item,expiry,unit
 FROM adc_stock_lot l JOIN adc_stock_item i ON i.id=l.item_id WHERE l.id=NEW.lot_id FOR UPDATE OF l;
 IF NEW.kind IN ('RECEIPT','ISSUE','USE') AND
  (expiry < (now() AT TIME ZONE 'Asia/Shanghai')::date OR EXISTS (SELECT 1 FROM adc_stock_recall r WHERE r.lot_id=NEW.lot_id)) THEN
  RAISE EXCEPTION 'Expired or recalled stock cannot be received or issued' USING ERRCODE='23514';
 END IF;
 IF NEW.kind IN ('ISSUE','USE','WASTE','REVERSE_IN') THEN
  balance=adc_stock_balance(NEW.lot_id);
  IF balance<NEW.quantity THEN RAISE EXCEPTION 'Available lot stock cannot be negative' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.kind IN ('ISSUE','QUARANTINE') THEN
  SELECT EXISTS (
   SELECT 1 FROM adc_dispense_movement d JOIN adc_pharmacy_quote_line q ON q.id=d.line_id
   JOIN adc_pharmacy_quote h ON h.id=q.quote_id JOIN adc_prescription_decision a ON a.id=h.approval_id
   JOIN adc_prescription_version r ON r.id=a.version_id JOIN adc_prescription p ON p.id=r.prescription_id
   JOIN adc_visit v ON v.id=p.visit_id
   WHERE d.id=NEW.dispense_id AND d.requires_batch AND d.actor_id=NEW.actor_id AND d.quantity=NEW.quantity
     AND q.item_id=rx_item AND q.unit_snapshot=unit AND v.clinic_id=clinic
     AND (d.kind='ISSUE' AND NEW.kind='ISSUE' OR d.kind='RETURN' AND NEW.kind='QUARANTINE' AND EXISTS (
       SELECT 1 FROM adc_stock_movement m WHERE m.dispense_id=d.original_issue_id AND m.lot_id=NEW.lot_id AND m.kind='ISSUE'
     ))
  ) INTO source_valid;
 ELSIF NEW.kind='USE' THEN
  SELECT EXISTS (
   SELECT 1 FROM adc_nursing_execution n JOIN adc_visit v ON v.id=n.visit_id
   WHERE n.id=NEW.execution_id AND n.kind='MATERIAL' AND n.actor_id=NEW.actor_id
   AND n.quantity=NEW.quantity AND v.clinic_id=clinic AND item_kind IN ('MATERIAL','IMPLANT')
  ) INTO source_valid;
 ELSE
  source_valid=adc_stock_operator(NEW.actor_id,clinic,item_kind);
  IF NEW.kind='RECEIPT' THEN source_valid=source_valid AND btrim(NEW.reference)<>'';
  ELSIF NEW.kind IN ('REVERSE_IN','REVERSE_OUT') THEN
   source_valid=source_valid AND EXISTS (
    SELECT 1 FROM adc_stock_movement m WHERE m.id=NEW.reverses_id AND m.lot_id=NEW.lot_id AND m.quantity=NEW.quantity
    AND m.kind=CASE WHEN NEW.kind='REVERSE_IN' THEN 'RECEIPT' ELSE 'WASTE' END
   );
  END IF;
 END IF;
 IF source_valid IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'Stock movement must match its scoped physical source' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_nursing_authorized(p_actor bigint,p_clinic bigint,p_duty bigint,p_kind text)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS (SELECT 1 FROM adc_nursing_duty d JOIN adc_role_assignment a ON a.user_id=d.user_id AND a.clinic_id=d.clinic_id
  JOIN adc_user u ON u.id=d.user_id
  WHERE d.id=p_duty AND d.user_id=p_actor AND d.clinic_id=p_clinic AND d.kind=p_kind
  AND d.revoked_at IS NULL AND now()>=d.valid_from AND now()<d.valid_until
  AND a.role='NURSE' AND a.scope_kind='CLINIC' AND a.is_active AND u.is_active)
$$;

CREATE FUNCTION adc_guard_sterile_pack() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE clinic bigint;
BEGIN
 IF TG_TABLE_NAME='adc_sterile_pack' THEN
  IF NOT adc_nursing_authorized(NEW.released_by_id,NEW.clinic_id,NEW.duty_id,'STERILITY')
   OR btrim(NEW.code)='' OR btrim(NEW.process_reference)='' THEN
   RAISE EXCEPTION 'Sterile package needs a scoped release and process evidence' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT clinic_id INTO clinic FROM adc_sterile_pack WHERE id=NEW.pack_id FOR UPDATE;
  IF NOT adc_nursing_authorized(NEW.actor_id,clinic,NEW.duty_id,'STERILITY') OR btrim(NEW.reason)='' THEN
   RAISE EXCEPTION 'Sterile hold needs a scoped actor and reason' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_guard_nursing_execution() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v adc_visit%ROWTYPE; pack adc_sterile_pack%ROWTYPE; lot adc_stock_lot%ROWTYPE; issued integer; handled bigint;
BEGIN
 SELECT * INTO v FROM adc_visit WHERE id=NEW.visit_id FOR UPDATE;
 IF v.status<>'CHECKED_IN' OR v.attended_at IS NULL OR NEW.observed_at<v.attended_at
  OR NOT adc_nursing_authorized(NEW.actor_id,v.clinic_id,NEW.duty_id,'EXECUTE') THEN
  RAISE EXCEPTION 'Nursing execution needs an active in-clinic encounter and scoped duty' USING ERRCODE='23514';
 END IF;
 IF NEW.kind IN ('MATERIAL','STERILE') AND NOT EXISTS (
  SELECT 1 FROM adc_performed_procedure p JOIN adc_clinical_encounter e ON e.id=p.encounter_id
  WHERE p.id=NEW.performed_id AND e.visit_id=v.id AND p.state='ACTIVE'
 ) THEN RAISE EXCEPTION 'Nursing care needs the corresponding active performed procedure' USING ERRCODE='23514'; END IF;
 IF NEW.kind='STERILE' THEN
  SELECT * INTO pack FROM adc_sterile_pack WHERE id=NEW.sterile_pack_id FOR UPDATE;
  IF pack.clinic_id IS DISTINCT FROM v.clinic_id OR NEW.observed_at<pack.released_at OR pack.valid_until<=clock_timestamp()
   OR EXISTS (SELECT 1 FROM adc_sterile_hold h WHERE h.pack_id=pack.id) THEN
   RAISE EXCEPTION 'Sterile package must be usable in the same clinic' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.kind='ADMINISTER' THEN
  SELECT d.quantity INTO issued FROM adc_dispense_movement d JOIN adc_pharmacy_quote_line q ON q.id=d.line_id
  JOIN adc_pharmacy_quote h ON h.id=q.quote_id JOIN adc_prescription_decision a ON a.id=h.approval_id
  JOIN adc_prescription_version r ON r.id=a.version_id JOIN adc_prescription p ON p.id=r.prescription_id
  WHERE d.id=NEW.issue_id AND d.kind='ISSUE' AND d.requires_batch AND p.visit_id=v.id AND d.occurred_at<=NEW.observed_at;
  SELECT l.* INTO lot FROM adc_stock_lot l JOIN adc_stock_movement m ON m.lot_id=l.id
  WHERE m.dispense_id=NEW.issue_id AND m.kind='ISSUE' FOR UPDATE OF l;
  SELECT coalesce(sum(quantity),0) INTO handled FROM (
   SELECT quantity FROM adc_nursing_execution WHERE issue_id=NEW.issue_id
   UNION ALL SELECT quantity FROM adc_dispense_movement WHERE original_issue_id=NEW.issue_id
  ) accounted;
  IF issued IS NULL OR lot.id IS NULL OR lot.expires_on<(now() AT TIME ZONE 'Asia/Shanghai')::date
   OR EXISTS (SELECT 1 FROM adc_stock_recall c WHERE c.lot_id=lot.id) OR handled+NEW.quantity>issued THEN
   RAISE EXCEPTION 'Administration needs a usable issued lot and undisposed quantity' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_guard_administered_return() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_quantity integer; accounted bigint; trace_needed boolean;
BEGIN
 IF NEW.kind='RETURN' THEN
  -- dispense_scope has already serialized this visit and checked the issue identity.
  SELECT quantity,requires_batch INTO prior_quantity,trace_needed FROM adc_dispense_movement WHERE id=NEW.original_issue_id;
  SELECT coalesce(sum(quantity),0) INTO accounted FROM (
   SELECT quantity FROM adc_nursing_execution WHERE issue_id=NEW.original_issue_id
   UNION ALL SELECT quantity FROM adc_dispense_movement WHERE original_issue_id=NEW.original_issue_id
  ) relevant;
  IF accounted+NEW.quantity>prior_quantity OR NEW.requires_batch IS DISTINCT FROM trace_needed THEN
   RAISE EXCEPTION 'Return cannot consume administered quantity or lose lot provenance' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION adc_check_stock_links() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='adc_dispense_movement' THEN
  IF NEW.requires_batch AND NOT EXISTS (SELECT 1 FROM adc_stock_movement WHERE dispense_id=NEW.id) THEN
   RAISE EXCEPTION 'Traced dispensing needs its stock movement' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.kind='MATERIAL' AND NOT EXISTS (SELECT 1 FROM adc_stock_movement WHERE execution_id=NEW.id) THEN
  RAISE EXCEPTION 'Material execution needs its stock movement' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;

CREATE TRIGGER stock_item_scope BEFORE INSERT ON adc_stock_item FOR EACH ROW EXECUTE FUNCTION adc_guard_stock_item();
CREATE TRIGGER stock_recall_scope BEFORE INSERT ON adc_stock_recall FOR EACH ROW EXECUTE FUNCTION adc_guard_stock_recall();
CREATE TRIGGER stock_movement_scope BEFORE INSERT ON adc_stock_movement FOR EACH ROW EXECUTE FUNCTION adc_guard_stock_movement();
CREATE TRIGGER sterile_pack_scope BEFORE INSERT ON adc_sterile_pack FOR EACH ROW EXECUTE FUNCTION adc_guard_sterile_pack();
CREATE TRIGGER sterile_hold_scope BEFORE INSERT ON adc_sterile_hold FOR EACH ROW EXECUTE FUNCTION adc_guard_sterile_pack();
CREATE TRIGGER nursing_execution_scope BEFORE INSERT ON adc_nursing_execution FOR EACH ROW EXECUTE FUNCTION adc_guard_nursing_execution();
CREATE TRIGGER dispense_use_consistency BEFORE INSERT ON adc_dispense_movement
 FOR EACH ROW EXECUTE FUNCTION adc_guard_administered_return();
CREATE CONSTRAINT TRIGGER dispense_stock_required AFTER INSERT ON adc_dispense_movement
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_check_stock_links();
CREATE CONSTRAINT TRIGGER nursing_stock_required AFTER INSERT ON adc_nursing_execution
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_check_stock_links();
""" + ''.join(
    f'CREATE TRIGGER {name}_retained BEFORE UPDATE OR DELETE ON adc_{name} '
    'FOR EACH ROW EXECUTE FUNCTION adc_clinical_history_guard();\n' for name in RETAINED
)

REVERSE_SQL = ''.join(f'DROP TRIGGER {name}_retained ON adc_{name};\n' for name in RETAINED) + """
DROP TRIGGER nursing_stock_required ON adc_nursing_execution;
DROP TRIGGER dispense_stock_required ON adc_dispense_movement;
DROP TRIGGER dispense_use_consistency ON adc_dispense_movement;
DROP TRIGGER nursing_execution_scope ON adc_nursing_execution;
DROP TRIGGER sterile_hold_scope ON adc_sterile_hold;
DROP TRIGGER sterile_pack_scope ON adc_sterile_pack;
DROP TRIGGER stock_movement_scope ON adc_stock_movement;
DROP TRIGGER stock_recall_scope ON adc_stock_recall;
DROP TRIGGER stock_item_scope ON adc_stock_item;
DROP FUNCTION adc_check_stock_links();
DROP FUNCTION adc_guard_administered_return();
DROP FUNCTION adc_guard_nursing_execution();
DROP FUNCTION adc_guard_sterile_pack();
DROP FUNCTION adc_nursing_authorized(bigint,bigint,bigint,text);
DROP FUNCTION adc_guard_stock_movement();
DROP FUNCTION adc_guard_stock_recall();
DROP FUNCTION adc_stock_operator(bigint,bigint,text);
DROP FUNCTION adc_guard_stock_item();
DROP FUNCTION adc_stock_balance(bigint);
"""


def protect_trace_history(apps,schema_editor):
    database=schema_editor.connection.alias
    for name in ('StockItem','StockLot','StockMovement','StockRecall','NursingDuty','NursingExecution','SterilePack','SterileHold'):
        if apps.get_model('supplies',name).objects.using(database).exists():
            raise RuntimeError('Stock or nursing trace history exists; reversing its schema is refused.')
    for app,name in [('accounts','RoleAssignment'),('workspaces','WorkspaceContext')]:
        if apps.get_model(app,name).objects.using(database).filter(role='NURSE').exists():
            raise RuntimeError('Nursing authorization exists; reversing its schema is refused.')


class Migration(migrations.Migration):
    dependencies=[
        ('supplies','0001_c5_batch_nursing'),
        ('accounts','0009_c5_batch_nursing'),
        ('workspaces','0006_c5_batch_nursing'),
    ]
    operations=[
        migrations.RunSQL(SQL,reverse_sql=REVERSE_SQL),
        migrations.RunPython(migrations.RunPython.noop,protect_trace_history),
    ]
