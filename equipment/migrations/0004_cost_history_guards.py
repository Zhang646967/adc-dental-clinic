"""Additive cost history and cash-basis guards; historical migrations stay intact."""
from django.db import migrations

SQL = r"""
CREATE FUNCTION adc_equipment_cost_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e adc_equipment_event%ROWTYPE; latest adc_equipment_cost_amendment%ROWTYPE; fee numeric; net numeric;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'cost history cannot be deleted' USING ERRCODE='23514';
  END IF;
  PERFORM 1 FROM adc_equipment_asset WHERE id=(SELECT asset_id FROM adc_equipment_event WHERE id=NEW.event_id) FOR UPDATE;
  SELECT * INTO e FROM adc_equipment_event WHERE id=NEW.event_id FOR UPDATE;
  IF NOT FOUND OR e.kind NOT IN ('REGISTER','SERVICE') OR btrim(NEW.reason)='' THEN
    RAISE EXCEPTION 'invalid equipment fee event or reason' USING ERRCODE='23514';
  END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.state<>'PENDING' OR NEW.lock_version<>0 OR NEW.review_reason<>'' THEN
      RAISE EXCEPTION 'cost amendment starts pending' USING ERRCODE='23514';
    END IF;
  ELSE
    IF OLD.state<>'PENDING' OR NEW.state NOT IN ('APPROVED','REJECTED') OR NEW.lock_version<>1
       OR (NEW.event_id,NEW.operation_id,NEW.based_amendment_id,NEW.previous_cost,NEW.proposed_cost,NEW.reason,NEW.prepared_by_id,NEW.prepared_at)
          IS DISTINCT FROM (OLD.event_id,OLD.operation_id,OLD.based_amendment_id,OLD.previous_cost,OLD.proposed_cost,OLD.reason,OLD.prepared_by_id,OLD.prepared_at)
       OR btrim(NEW.review_reason)='' OR NEW.reviewed_at<NEW.prepared_at THEN
      RAISE EXCEPTION 'cost facts and terminal decisions are immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.state<>'REJECTED' THEN
    SELECT * INTO latest FROM adc_equipment_cost_amendment WHERE event_id=e.id AND state='APPROVED' ORDER BY id DESC LIMIT 1;
    fee=CASE WHEN latest.id IS NULL THEN e.cost ELSE latest.proposed_cost END;
    IF NEW.based_amendment_id IS DISTINCT FROM latest.id OR NEW.previous_cost IS DISTINCT FROM fee OR NEW.proposed_cost IS NOT DISTINCT FROM fee THEN
      RAISE EXCEPTION 'cost amendment requires current distinct basis' USING ERRCODE='23514';
    END IF;
    SELECT coalesce(sum(CASE WHEN kind='EQUIPMENT_EXPENSE' THEN amount ELSE -amount END),0) INTO net
      FROM adc_cash_entry WHERE equipment_event_id=e.id AND state='POSTED';
    IF net<>0 OR EXISTS (SELECT 1 FROM adc_cash_entry WHERE equipment_event_id=e.id AND state='PENDING') THEN
      RAISE EXCEPTION 'resolve pending cash and reverse posted fees first' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER equipment_cost_history BEFORE INSERT OR UPDATE OR DELETE ON adc_equipment_cost_amendment
  FOR EACH ROW EXECUTE FUNCTION adc_equipment_cost_guard();

CREATE OR REPLACE FUNCTION adc_cash_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE i adc_invoice%ROWTYPE; a adc_equipment_asset%ROWTYPE; e adc_equipment_event%ROWTYPE;
        original adc_cash_entry%ROWTYPE; amendment adc_equipment_cost_amendment%ROWTYPE; current_amendment bigint; fee numeric; clinic bigint; vstate text; vvisit bigint;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'cash history cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.state<>'PENDING' OR NEW.lock_version<>0 OR NEW.review_reason<>'' THEN
      RAISE EXCEPTION 'cash entry starts as an unreviewed request' USING ERRCODE='23514';
    END IF;
  ELSE
    IF OLD.state<>'PENDING' OR NEW.state NOT IN ('POSTED','REJECTED') OR NEW.lock_version<>1
       OR (NEW.operation_id,NEW.clinic_id,NEW.invoice_id,NEW.based_record_version_id,NEW.equipment_event_id,
           NEW.equipment_cost_amendment_id,NEW.reversal_of_id,NEW.kind,NEW.amount,NEW.occurred_on,NEW.reason,NEW.prepared_by_id,NEW.prepared_at)
         IS DISTINCT FROM
          (OLD.operation_id,OLD.clinic_id,OLD.invoice_id,OLD.based_record_version_id,OLD.equipment_event_id,
           OLD.equipment_cost_amendment_id,OLD.reversal_of_id,OLD.kind,OLD.amount,OLD.occurred_on,OLD.reason,OLD.prepared_by_id,OLD.prepared_at)
       OR btrim(NEW.review_reason)='' OR NEW.reviewed_at<NEW.prepared_at THEN
      RAISE EXCEPTION 'cash request facts and terminal decisions are immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.invoice_id IS NOT NULL THEN
    SELECT * INTO i FROM adc_invoice WHERE id=NEW.invoice_id;
    SELECT clinic_id INTO clinic FROM adc_visit WHERE id=i.visit_id;
    SELECT state,visit_id INTO vstate,vvisit FROM adc_visit_record_version WHERE id=NEW.based_record_version_id;
    IF clinic IS DISTINCT FROM NEW.clinic_id OR vstate IS DISTINCT FROM 'PUBLISHED' OR vvisit IS DISTINCT FROM i.visit_id
       OR (NEW.state<>'REJECTED' AND i.current_record_version_id<>NEW.based_record_version_id) THEN
      RAISE EXCEPTION 'cash request requires its own current published bill' USING ERRCODE='23514';
    END IF;
  ELSE
    PERFORM 1 FROM adc_equipment_asset WHERE id=(SELECT asset_id FROM adc_equipment_event WHERE id=NEW.equipment_event_id) FOR UPDATE;
    SELECT * INTO e FROM adc_equipment_event WHERE id=NEW.equipment_event_id FOR UPDATE;
    SELECT * INTO a FROM adc_equipment_asset WHERE id=e.asset_id;
    fee=e.cost;
    IF NEW.equipment_cost_amendment_id IS NOT NULL THEN
      SELECT * INTO amendment FROM adc_equipment_cost_amendment WHERE id=NEW.equipment_cost_amendment_id;
      IF NOT FOUND OR amendment.event_id<>e.id OR amendment.state<>'APPROVED' THEN
        RAISE EXCEPTION 'invalid equipment cost basis' USING ERRCODE='23514';
      END IF;
      fee=amendment.proposed_cost;
    END IF;
    IF a.clinic_id IS DISTINCT FROM NEW.clinic_id OR e.kind NOT IN ('REGISTER','SERVICE')
       OR fee IS NULL OR fee<=0 OR NEW.amount<>fee THEN
      RAISE EXCEPTION 'equipment cash requires matching retained cost basis' USING ERRCODE='23514';
    END IF;
    IF NEW.state<>'REJECTED' AND NEW.reversal_of_id IS NULL THEN
      SELECT id INTO current_amendment FROM adc_equipment_cost_amendment WHERE event_id=e.id AND state='APPROVED' ORDER BY id DESC LIMIT 1;
      IF NEW.equipment_cost_amendment_id IS DISTINCT FROM current_amendment
         OR EXISTS (SELECT 1 FROM adc_equipment_cost_amendment WHERE event_id=e.id AND state='PENDING') THEN
        RAISE EXCEPTION 'equipment cost basis is stale or pending review' USING ERRCODE='23514';
      END IF;
    END IF;
  END IF;
  IF NEW.reversal_of_id IS NOT NULL THEN
    SELECT * INTO original FROM adc_cash_entry WHERE id=NEW.reversal_of_id;
    IF NOT FOUND OR original.state<>'POSTED' OR original.reversal_of_id IS NOT NULL OR original.amount<>NEW.amount
       OR original.clinic_id<>NEW.clinic_id OR original.invoice_id IS DISTINCT FROM NEW.invoice_id
       OR original.equipment_event_id IS DISTINCT FROM NEW.equipment_event_id
       OR original.equipment_cost_amendment_id IS DISTINCT FROM NEW.equipment_cost_amendment_id
       OR NOT ((original.kind='RECEIPT' AND NEW.kind='REFUND') OR (original.kind='REFUND' AND NEW.kind='RECEIPT')
               OR (original.kind='EQUIPMENT_EXPENSE' AND NEW.kind='EXPENSE_REVERSAL')) THEN
      RAISE EXCEPTION 'invalid cash reversal lineage' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.kind='EXPENSE_REVERSAL' THEN
    RAISE EXCEPTION 'expense reversal requires its original entry' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
"""
REVERSE = r"""DROP TRIGGER equipment_cost_history ON adc_equipment_cost_amendment; DROP FUNCTION adc_equipment_cost_guard();

CREATE OR REPLACE FUNCTION adc_cash_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE i adc_invoice%ROWTYPE; a adc_equipment_asset%ROWTYPE; e adc_equipment_event%ROWTYPE;
        original adc_cash_entry%ROWTYPE; clinic bigint; vstate text; vvisit bigint;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'cash history cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.state<>'PENDING' OR NEW.lock_version<>0 OR NEW.review_reason<>'' THEN
      RAISE EXCEPTION 'cash entry starts as an unreviewed request' USING ERRCODE='23514';
    END IF;
  ELSE
    IF OLD.state<>'PENDING' OR NEW.state NOT IN ('POSTED','REJECTED') OR NEW.lock_version<>1
       OR (NEW.operation_id,NEW.clinic_id,NEW.invoice_id,NEW.based_record_version_id,NEW.equipment_event_id,
           NEW.reversal_of_id,NEW.kind,NEW.amount,NEW.occurred_on,NEW.reason,NEW.prepared_by_id,NEW.prepared_at)
         IS DISTINCT FROM
          (OLD.operation_id,OLD.clinic_id,OLD.invoice_id,OLD.based_record_version_id,OLD.equipment_event_id,
           OLD.reversal_of_id,OLD.kind,OLD.amount,OLD.occurred_on,OLD.reason,OLD.prepared_by_id,OLD.prepared_at)
       OR btrim(NEW.review_reason)='' OR NEW.reviewed_at<NEW.prepared_at THEN
      RAISE EXCEPTION 'cash request facts and terminal decisions are immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.invoice_id IS NOT NULL THEN
    SELECT * INTO i FROM adc_invoice WHERE id=NEW.invoice_id;
    SELECT clinic_id INTO clinic FROM adc_visit WHERE id=i.visit_id;
    SELECT state,visit_id INTO vstate,vvisit FROM adc_visit_record_version WHERE id=NEW.based_record_version_id;
    IF clinic IS DISTINCT FROM NEW.clinic_id OR vstate IS DISTINCT FROM 'PUBLISHED' OR vvisit IS DISTINCT FROM i.visit_id
       OR (NEW.state<>'REJECTED' AND i.current_record_version_id<>NEW.based_record_version_id) THEN
      RAISE EXCEPTION 'cash request requires its own current published bill' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT * INTO e FROM adc_equipment_event WHERE id=NEW.equipment_event_id;
    SELECT * INTO a FROM adc_equipment_asset WHERE id=e.asset_id;
    IF a.clinic_id IS DISTINCT FROM NEW.clinic_id OR e.kind NOT IN ('REGISTER','SERVICE')
       OR e.cost IS NULL OR e.cost<=0 OR NEW.amount<>e.cost THEN
      RAISE EXCEPTION 'equipment cash request requires its matching recorded fee' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.reversal_of_id IS NOT NULL THEN
    SELECT * INTO original FROM adc_cash_entry WHERE id=NEW.reversal_of_id;
    IF NOT FOUND OR original.state<>'POSTED' OR original.reversal_of_id IS NOT NULL OR original.amount<>NEW.amount
       OR original.clinic_id<>NEW.clinic_id OR original.invoice_id IS DISTINCT FROM NEW.invoice_id
       OR original.equipment_event_id IS DISTINCT FROM NEW.equipment_event_id
       OR NOT ((original.kind='RECEIPT' AND NEW.kind='REFUND') OR (original.kind='REFUND' AND NEW.kind='RECEIPT')
               OR (original.kind='EQUIPMENT_EXPENSE' AND NEW.kind='EXPENSE_REVERSAL')) THEN
      RAISE EXCEPTION 'invalid cash reversal lineage' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.kind='EXPENSE_REVERSAL' THEN
    RAISE EXCEPTION 'expense reversal requires its original entry' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
"""

def refuse_reverse(apps,schema_editor):
    if apps.get_model('equipment','EquipmentCostAmendment').objects.exists():
        raise RuntimeError('Cost history exists; retain schema and restore a separate empty environment.')

class Migration(migrations.Migration):
    dependencies=[('equipment','0003_equipmentcostamendment'),('finance','0005_cashentry_equipment_cost_amendment_and_more')]
    operations=[migrations.RunSQL(SQL,REVERSE),migrations.RunPython(migrations.RunPython.noop,refuse_reverse)]
