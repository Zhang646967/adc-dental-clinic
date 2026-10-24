"""Attributed recall and internal/manual laboratory readiness facts."""
import uuid
from django.db import models
from django.db.models import Q,F

def lab_case_no():return 'LAB-'+uuid.uuid4().hex[:24].upper()


class RecallEpisode(models.Model):
    instruction=models.OneToOneField('clinical.NextVisitInstruction',on_delete=models.PROTECT,related_name='recall')
    owner=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='clinical_recalls')
    followup_due_at=models.DateTimeField()
    state=models.CharField(max_length=16,choices=[('OPEN','继续联系与安排'),('REVIEW','本人暂不继续，转医师核对'),('COMPLETED','已核对实际复诊目标'),('WITHDRAWN','原指示已明确撤回')],default='OPEN')
    revision=models.PositiveIntegerField(default=0)
    opened_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='+')
    opened_at=models.DateTimeField(auto_now_add=True)
    completed_at=models.DateTimeField(null=True,blank=True)
    completion_record=models.ForeignKey('clinical.ClinicalRecordVersion',null=True,blank=True,on_delete=models.PROTECT)
    completion_performed=models.ForeignKey('clinical.PerformedProcedure',null=True,blank=True,on_delete=models.PROTECT)
    class Meta:
        db_table='adc_clinical_recall'
        constraints=[models.CheckConstraint(condition=Q(state__in=['OPEN','REVIEW','COMPLETED','WITHDRAWN']),name='clinical_recall_state_valid'),
            models.CheckConstraint(condition=(Q(state='COMPLETED',completed_at__isnull=False)&(Q(completion_record__isnull=False,completion_performed__isnull=True)|Q(completion_record__isnull=True,completion_performed__isnull=False)))|
                (~Q(state='COMPLETED')&Q(completed_at__isnull=True,completion_record__isnull=True,completion_performed__isnull=True)),name='clinical_recall_completion_evidence')]


class RecallEvent(models.Model):
    episode=models.ForeignKey(RecallEpisode,on_delete=models.PROTECT,related_name='events')
    actor=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    action=models.CharField(max_length=32)
    note=models.CharField(max_length=500,blank=True)
    snapshot=models.JSONField(default=dict)
    operation_id=models.UUIDField(unique=True)
    recorded_at=models.DateTimeField(auto_now_add=True)
    class Meta:db_table='adc_clinical_recall_event'


class LabCase(models.Model):
    case_no=models.CharField(max_length=40,unique=True,default=lab_case_no,editable=False)
    source_record=models.ForeignKey('clinical.ClinicalRecordVersion',on_delete=models.PROTECT)
    step_version=models.ForeignKey('clinical.PlanStepVersion',on_delete=models.PROTECT,related_name='lab_cases')
    requester=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='+')
    requested_at=models.DateTimeField(auto_now_add=True)
    work_kind=models.CharField(max_length=16,choices=[('RESTORATION','修复加工件'),('PROSTHESIS','义齿加工件'),('APPLIANCE','矫治／辅助装置'),('OTHER','其他已明确加工件')])
    specification=models.CharField(max_length=3000)
    vendor_name=models.CharField(max_length=120)
    logistics_note=models.CharField(max_length=500,blank=True)
    needed_on=models.DateField()
    state=models.CharField(max_length=16,choices=[('REQUESTED','待前台安排送出'),('DISPATCHED','已手工登记送出'),('RECEIVED','已返回，待医师验收'),('ACCEPTED','本周期已通过临床验收'),('REWORK','需返工，尚未就绪'),('WITHDRAWN','已明确撤回加工请求')],default='REQUESTED')
    revision=models.PositiveIntegerField(default=0)
    cycle=models.PositiveIntegerField(default=0)
    coordinator=models.ForeignKey('accounts.UserAccount',null=True,blank=True,on_delete=models.PROTECT,related_name='lab_coordination')
    followup_due_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        db_table='adc_lab_case'
        constraints=[models.CheckConstraint(condition=Q(state__in=['REQUESTED','DISPATCHED','RECEIVED','ACCEPTED','REWORK','WITHDRAWN']),name='lab_case_state_valid'),
            models.CheckConstraint(condition=Q(coordinator__isnull=True,followup_due_at__isnull=True,state__in=['REQUESTED','WITHDRAWN'])|Q(coordinator__isnull=False,followup_due_at__isnull=False),name='lab_coordination_owner_due'),
            models.CheckConstraint(condition=Q(work_kind__in=['RESTORATION','PROSTHESIS','APPLIANCE','OTHER']),name='lab_case_kind_valid')]


class LabReview(models.Model):
    case=models.ForeignKey(LabCase,on_delete=models.PROTECT,related_name='reviews')
    target_step_version=models.ForeignKey('clinical.PlanStepVersion',on_delete=models.PROTECT,related_name='lab_reviews')
    source_record=models.ForeignKey('clinical.ClinicalRecordVersion',on_delete=models.PROTECT)
    reviewer=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    cycle=models.PositiveIntegerField()
    decision=models.CharField(max_length=16,choices=[('ACCEPTED','已核对当前步骤，验收通过'),('REWORK','未通过，明确返工')])
    findings=models.CharField(max_length=3000)
    coordination_note=models.CharField(max_length=500,blank=True)
    operation_id=models.UUIDField(unique=True)
    assessed_at=models.DateTimeField()
    recorded_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_lab_review'
        constraints=[models.CheckConstraint(condition=Q(decision__in=['ACCEPTED','REWORK']),name='lab_review_decision_valid'),
            models.CheckConstraint(condition=Q(assessed_at__lte=F('recorded_at')),name='lab_review_not_future'),
            models.CheckConstraint(condition=Q(cycle__gte=1),name='lab_review_real_dispatch_cycle')]


class LabEvent(models.Model):
    case=models.ForeignKey(LabCase,on_delete=models.PROTECT,related_name='events')
    actor=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    action=models.CharField(max_length=32)
    note=models.CharField(max_length=500,blank=True)
    snapshot=models.JSONField(default=dict)
    review=models.ForeignKey(LabReview,null=True,blank=True,on_delete=models.PROTECT)
    operation_id=models.UUIDField(unique=True)
    recorded_at=models.DateTimeField(auto_now_add=True)
    class Meta:db_table='adc_lab_event'
