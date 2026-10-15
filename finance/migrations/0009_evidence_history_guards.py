"""Immutable evidence/import facts, exact matching and retained decisions."""
from django.db import migrations

SQL = r"""
CREATE FUNCTION adc_financial_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e adc_cash_entry%ROWTYPE; a adc_payment_account%ROWTYPE;
        p adc_cash_evidence%ROWTYPE; b adc_statement_batch%ROWTYPE;
        l adc_statement_line%ROWTYPE; latest_id bigint;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'financial evidence history cannot be deleted' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='adc_payment_account' THEN
   IF NEW.code !~ '^[A-Z0-9][A-Z0-9_-]{1,39}$' THEN RAISE EXCEPTION 'invalid payment account code' USING ERRCODE='23514'; END IF;
   IF TG_OP='INSERT' THEN
     IF NOT NEW.is_active OR NEW.lock_version<>0 OR NEW.last_operation_id<>NEW.operation_id THEN
       RAISE EXCEPTION 'account starts active at version zero' USING ERRCODE='23514'; END IF;
   ELSIF (to_jsonb(NEW)-ARRAY['is_active','lock_version','last_operation_id']) IS DISTINCT FROM
         (to_jsonb(OLD)-ARRAY['is_active','lock_version','last_operation_id']) OR
         NEW.is_active=OLD.is_active OR NEW.lock_version<>OLD.lock_version+1 OR NEW.last_operation_id=OLD.last_operation_id THEN
     RAISE EXCEPTION 'account identity is immutable and state changes are versioned' USING ERRCODE='23514';
   END IF;
 ELSIF TG_TABLE_NAME='adc_cash_evidence' THEN
   SELECT * INTO e FROM adc_cash_entry WHERE id=NEW.cash_entry_id;
   SELECT * INTO a FROM adc_payment_account WHERE id=NEW.account_id;
   IF a.clinic_id IS DISTINCT FROM e.clinic_id OR btrim(NEW.reference)='' OR NEW.reference<>btrim(NEW.reference) OR btrim(NEW.reason)='' THEN
     RAISE EXCEPTION 'evidence needs its own clinic account and reference' USING ERRCODE='23514'; END IF;
   IF TG_OP='INSERT' THEN
     SELECT * INTO p FROM adc_cash_evidence WHERE cash_entry_id=NEW.cash_entry_id ORDER BY version DESC LIMIT 1;
     IF NEW.state<>'PENDING' OR (p.id IS NULL AND (NEW.version<>1 OR NEW.previous_id IS NOT NULL)) OR
        (p.id IS NOT NULL AND (NEW.previous_id IS DISTINCT FROM p.id OR NEW.version<>p.version+1 OR p.state='PENDING')) OR
        (NEW.initial AND (NEW.version<>1 OR e.state<>'PENDING' OR NEW.prepared_by_id<>e.prepared_by_id)) OR
        (NOT NEW.initial AND e.state<>'POSTED') THEN
       RAISE EXCEPTION 'evidence version lineage is invalid' USING ERRCODE='23514'; END IF;
   ELSE
     IF OLD.state<>'PENDING' OR NEW.state NOT IN ('APPROVED','REJECTED') OR
       (to_jsonb(NEW)-ARRAY['state','reviewed_by_id','reviewed_at','review_reason']) IS DISTINCT FROM
       (to_jsonb(OLD)-ARRAY['state','reviewed_by_id','reviewed_at','review_reason']) OR NEW.reviewed_at<NEW.prepared_at OR
       (NEW.initial AND ((NEW.state='APPROVED' AND e.state<>'POSTED') OR (NEW.state='REJECTED' AND e.state<>'REJECTED'))) OR
       (NOT NEW.initial AND e.state<>'POSTED') THEN
       RAISE EXCEPTION 'evidence facts and terminal decisions are immutable' USING ERRCODE='23514'; END IF;
   END IF;
 ELSIF TG_TABLE_NAME='adc_statement_batch' THEN
   IF octet_length(NEW.source_bytes) NOT BETWEEN 1 AND 2097152 OR NEW.parser_version<>'csv-v1' OR
      jsonb_typeof(NEW.normalized_rows)<>'array' OR jsonb_array_length(NEW.normalized_rows) NOT BETWEEN 1 AND 1000 OR
      NEW.digest<>encode(sha256(NEW.source_bytes),'hex') THEN
     RAISE EXCEPTION 'invalid bounded statement evidence' USING ERRCODE='23514'; END IF;
   IF TG_OP='INSERT' THEN
     IF NEW.state<>'DRAFT' THEN RAISE EXCEPTION 'statement starts as a private draft' USING ERRCODE='23514'; END IF;
   ELSIF OLD.state<>'DRAFT' OR NEW.state<>'IMPORTED' OR NEW.new_count+NEW.skipped_count<>jsonb_array_length(NEW.normalized_rows) OR
      NEW.imported_at<NEW.created_at OR
      (to_jsonb(NEW)-ARRAY['state','operation_id','imported_at','new_count','skipped_count']) IS DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['state','operation_id','imported_at','new_count','skipped_count']) THEN
     RAISE EXCEPTION 'statement source and accepted batches are immutable' USING ERRCODE='23514';
   END IF;
 ELSIF TG_TABLE_NAME='adc_statement_line' THEN
   IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'accepted statement rows are immutable' USING ERRCODE='23514'; END IF;
   SELECT * INTO b FROM adc_statement_batch WHERE id=NEW.batch_id;
   IF b.account_id IS DISTINCT FROM NEW.account_id OR b.state<>'DRAFT' OR
      NOT (b.normalized_rows @> jsonb_build_array(jsonb_build_object('transaction_id',NEW.transaction_id,
        'booked_on',to_char(NEW.booked_on,'YYYY-MM-DD'),'direction',NEW.direction,'amount',NEW.amount::text,
        'currency',NEW.currency,'reference',NEW.reference))) THEN
     RAISE EXCEPTION 'statement line does not belong to its retained import' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='adc_reconciliation_match' THEN
   SELECT * INTO e FROM adc_cash_entry WHERE id=NEW.cash_entry_id;
   SELECT * INTO p FROM adc_cash_evidence WHERE id=NEW.evidence_id;
   SELECT * INTO l FROM adc_statement_line WHERE id=NEW.line_id;
   SELECT * INTO a FROM adc_payment_account WHERE id=l.account_id;
   SELECT id INTO latest_id FROM adc_cash_evidence WHERE cash_entry_id=NEW.cash_entry_id AND state='APPROVED' ORDER BY version DESC LIMIT 1;
   IF TG_OP='INSERT' THEN
     IF NEW.state<>'PENDING' THEN RAISE EXCEPTION 'matching starts pending independent review' USING ERRCODE='23514'; END IF;
   ELSE
     IF (to_jsonb(NEW)-ARRAY['state','reviewed_by_id','reviewed_at','review_reason','invalidated_by_id','invalidated_at']) IS DISTINCT FROM
        (to_jsonb(OLD)-ARRAY['state','reviewed_by_id','reviewed_at','review_reason','invalidated_by_id','invalidated_at']) THEN
       RAISE EXCEPTION 'matching source identity is immutable' USING ERRCODE='23514'; END IF;
     IF NEW.state='STALE' THEN
       IF OLD.state NOT IN ('PENDING','CONFIRMED') OR latest_id IS NULL OR latest_id=NEW.evidence_id OR
          (NEW.reviewed_by_id,NEW.reviewed_at,NEW.review_reason) IS DISTINCT FROM (OLD.reviewed_by_id,OLD.reviewed_at,OLD.review_reason) OR
          NEW.invalidated_at<NEW.prepared_at THEN
         RAISE EXCEPTION 'only new approved evidence invalidates an active match' USING ERRCODE='23514'; END IF;
     ELSIF OLD.state<>'PENDING' OR NEW.state NOT IN ('CONFIRMED','REJECTED') OR NEW.reviewed_at<NEW.prepared_at THEN
       RAISE EXCEPTION 'matching decisions are retained' USING ERRCODE='23514';
     END IF;
   END IF;
   IF NEW.state IN ('PENDING','CONFIRMED') AND
      (e.state<>'POSTED' OR p.state<>'APPROVED' OR p.cash_entry_id<>e.id OR p.id IS DISTINCT FROM latest_id OR
       p.account_id<>l.account_id OR e.clinic_id<>a.clinic_id OR e.amount<>l.amount OR l.currency<>'CNY' OR p.reference<>l.reference OR
       l.direction<>CASE WHEN e.kind IN ('RECEIPT','EXPENSE_REVERSAL') THEN 'IN' ELSE 'OUT' END OR
       NOT EXISTS(SELECT 1 FROM adc_statement_batch WHERE id=l.batch_id AND state='IMPORTED')) THEN
     RAISE EXCEPTION 'matching requires exact current approved evidence and posted cash' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER payment_account_history BEFORE INSERT OR UPDATE OR DELETE ON adc_payment_account FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard();
CREATE TRIGGER cash_evidence_history BEFORE INSERT OR UPDATE OR DELETE ON adc_cash_evidence FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard();
CREATE TRIGGER statement_batch_history BEFORE INSERT OR UPDATE OR DELETE ON adc_statement_batch FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard();
CREATE TRIGGER statement_line_history BEFORE INSERT OR UPDATE OR DELETE ON adc_statement_line FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard();
CREATE TRIGGER reconciliation_history BEFORE INSERT OR UPDATE OR DELETE ON adc_reconciliation_match FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard();

CREATE FUNCTION adc_evidence_commit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE latest_id bigint;
BEGIN
 IF TG_TABLE_NAME='adc_cash_evidence' AND NEW.state='APPROVED' THEN
   SELECT id INTO latest_id FROM adc_cash_evidence WHERE cash_entry_id=NEW.cash_entry_id AND state='APPROVED' ORDER BY version DESC LIMIT 1;
   IF EXISTS(SELECT 1 FROM adc_reconciliation_match WHERE cash_entry_id=NEW.cash_entry_id AND state IN ('PENDING','CONFIRMED') AND evidence_id<>latest_id) THEN
     RAISE EXCEPTION 'new evidence must invalidate old active matches atomically' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='adc_statement_batch' AND NEW.state='IMPORTED' THEN
   IF NEW.new_count<>(SELECT count(*) FROM adc_statement_line WHERE batch_id=NEW.id) THEN
     RAISE EXCEPTION 'import counts must match accepted rows' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER evidence_matches_current AFTER INSERT OR UPDATE ON adc_cash_evidence DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_evidence_commit_guard();
CREATE CONSTRAINT TRIGGER statement_import_complete AFTER INSERT OR UPDATE ON adc_statement_batch DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_evidence_commit_guard();
"""

REVERSE = r"""
DROP TRIGGER statement_import_complete ON adc_statement_batch;
DROP TRIGGER evidence_matches_current ON adc_cash_evidence;
DROP FUNCTION adc_evidence_commit_guard();
DROP TRIGGER reconciliation_history ON adc_reconciliation_match;
DROP TRIGGER statement_line_history ON adc_statement_line;
DROP TRIGGER statement_batch_history ON adc_statement_batch;
DROP TRIGGER cash_evidence_history ON adc_cash_evidence;
DROP TRIGGER payment_account_history ON adc_payment_account;
DROP FUNCTION adc_financial_evidence_guard();
"""

def refuse_history_reverse(apps,schema_editor):
    for name in ('PaymentAccount','CashEvidenceVersion','StatementBatch','StatementLine','ReconciliationMatch'):
        if apps.get_model('finance',name).objects.exists():
            raise RuntimeError('Financial evidence exists; retain history and restore a separate trusted copy.')

class Migration(migrations.Migration):
    dependencies=[('finance','0008_payment_evidence_reconciliation')]
    operations=[migrations.RunSQL(SQL,REVERSE),migrations.RunPython(migrations.RunPython.noop,refuse_history_reverse)]
