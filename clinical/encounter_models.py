"""C2.1 clinical facts; independent of billing and actual-charge records."""
from django.db import models
from django.db.models import Q,F

HISTORY_STATES=[('UNKNOWN','尚未明确'),('REPORTED','自述有相关情况'),('NO_KNOWN','自述目前无已知情况')]
DENTITIONS=[('UNASSESSED','尚未核对牙列'),('PERMANENT','恒牙列'),('PRIMARY','乳牙列'),('MIXED','混合牙列')]


class ClinicalHistoryVersion(models.Model):
    patient=models.ForeignKey('patients.Patient',on_delete=models.PROTECT)
    revision=models.PositiveIntegerField()
    previous=models.OneToOneField('self',null=True,blank=True,on_delete=models.PROTECT,related_name='next_version')
    source=models.CharField(max_length=16,choices=[('SELF','患者本人提交'),('INTERVIEW','医师记录患者自述')])
    source_visit=models.ForeignKey('scheduling.Visit',null=True,blank=True,on_delete=models.PROTECT)
    scope_clinic=models.ForeignKey('registry.Clinic',null=True,blank=True,on_delete=models.PROTECT)
    reported_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    medical_status=models.CharField(max_length=16,choices=HISTORY_STATES,default='UNKNOWN')
    medical_history=models.CharField(max_length=2000,blank=True)
    medication_status=models.CharField(max_length=16,choices=HISTORY_STATES,default='UNKNOWN')
    medications=models.CharField(max_length=2000,blank=True)
    allergy_status=models.CharField(max_length=16,choices=HISTORY_STATES,default='UNKNOWN')
    reported_allergies=models.CharField(max_length=2000,blank=True)
    recorded_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table='adc_clinical_history_version'
        constraints=[
            models.UniqueConstraint(fields=['patient','scope_clinic','revision'],nulls_distinct=False,name='clinical_history_revision_unique'),
            models.CheckConstraint(condition=Q(revision__gte=1),name='clinical_history_revision_positive'),
            models.CheckConstraint(condition=Q(revision=1,previous__isnull=True)|Q(revision__gt=1,previous__isnull=False),name='clinical_history_previous_required'),
            models.CheckConstraint(condition=~Q(previous=F('id')),name='clinical_history_not_previous_self'),
            models.CheckConstraint(condition=Q(source='SELF',source_visit__isnull=True,scope_clinic__isnull=True)|Q(source='INTERVIEW',source_visit__isnull=False,scope_clinic__isnull=False),name='clinical_history_source_valid'),
            models.CheckConstraint(condition=Q(medical_status__in=['UNKNOWN','REPORTED','NO_KNOWN'])&Q(medication_status__in=['UNKNOWN','REPORTED','NO_KNOWN'])&Q(allergy_status__in=['UNKNOWN','REPORTED','NO_KNOWN']),name='clinical_history_states_valid'),
        ]


class ClinicalEncounter(models.Model):
    visit=models.OneToOneField('scheduling.Visit',on_delete=models.PROTECT,related_name='clinical_encounter')
    opened_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    opened_at=models.DateTimeField(auto_now_add=True)
    revision=models.PositiveIntegerField(default=0)

    class Meta:
        db_table='adc_clinical_encounter'


class ClinicalDraft(models.Model):
    encounter=models.OneToOneField(ClinicalEncounter,on_delete=models.PROTECT,related_name='draft')
    saved_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    base_record=models.ForeignKey('clinical.ClinicalRecordVersion',null=True,blank=True,on_delete=models.PROTECT)
    payload=models.JSONField(default=dict)
    saved_at=models.DateTimeField(auto_now=True)

    class Meta:
        db_table='adc_clinical_draft'


class ClinicalRecordVersion(models.Model):
    encounter=models.ForeignKey(ClinicalEncounter,on_delete=models.PROTECT,related_name='record_versions')
    revision=models.PositiveIntegerField()
    previous=models.OneToOneField('self',null=True,blank=True,on_delete=models.PROTECT,related_name='next_version')
    history=models.ForeignKey(ClinicalHistoryVersion,null=True,blank=True,on_delete=models.PROTECT)
    recorded_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    observed_at=models.DateTimeField()
    recorded_at=models.DateTimeField(auto_now_add=True)
    chief_complaint=models.CharField(max_length=2000)
    examination=models.CharField(max_length=4000)
    history_review=models.CharField(max_length=16,choices=[('REVIEWED','已核对指定自述'),('UNAVAILABLE','未取得自述，未知保留')])
    history_assessment=models.CharField(max_length=2000)
    history_cursor=models.CharField(max_length=64)
    history_discrepancy=models.CharField(max_length=2000,blank=True)
    dentition=models.CharField(max_length=16,choices=DENTITIONS)
    amendment_reason=models.CharField(max_length=500,blank=True)

    class Meta:
        db_table='adc_clinical_record_version'
        constraints=[
            models.UniqueConstraint(fields=['encounter','revision'],name='clinical_record_revision_unique'),
            models.CheckConstraint(condition=Q(revision__gte=1),name='clinical_record_revision_positive'),
            models.CheckConstraint(condition=Q(revision=1,previous__isnull=True)|Q(revision__gt=1,previous__isnull=False),name='clinical_record_previous_required'),
            models.CheckConstraint(condition=~Q(previous=F('id')),name='clinical_record_not_previous_self'),
            models.CheckConstraint(condition=Q(previous__isnull=True)|~Q(amendment_reason=''),name='clinical_record_amendment_reason'),
            models.CheckConstraint(condition=Q(observed_at__lte=F('recorded_at')),name='clinical_observation_not_future'),
            models.CheckConstraint(condition=Q(history_review='REVIEWED',history__isnull=False)|Q(history_review='UNAVAILABLE',history__isnull=True),name='clinical_history_review_consistent'),
            models.CheckConstraint(condition=Q(dentition__in=['UNASSESSED','PERMANENT','PRIMARY','MIXED']),name='clinical_dentition_valid'),
        ]


class ToothFinding(models.Model):
    record=models.ForeignKey(ClinicalRecordVersion,on_delete=models.PROTECT,related_name='findings')
    line_no=models.PositiveSmallIntegerField()
    tooth=models.PositiveSmallIntegerField()
    surface=models.CharField(max_length=6,blank=True)
    kind=models.CharField(max_length=16,choices=[('OBSERVATION','检查发现'),('MISSING','缺失'),('EXISTING_WORK','既往处置'),('OTHER','其他观察')])
    detail=models.CharField(max_length=1000)

    class Meta:
        db_table='adc_tooth_finding'
        ordering=['line_no']
        constraints=[
            models.UniqueConstraint(fields=['record','line_no'],name='clinical_finding_line_unique'),
            models.CheckConstraint(condition=Q(line_no__gte=1),name='clinical_finding_line_positive'),
            models.UniqueConstraint(fields=['record','tooth','surface','kind'],name='clinical_finding_location_unique'),
            models.CheckConstraint(condition=Q(tooth__in=[q*10+n for q in range(1,5) for n in range(1,9)]+[q*10+n for q in range(5,9) for n in range(1,6)]),name='clinical_finding_tooth_valid'),
            models.CheckConstraint(condition=Q(kind__in=['OBSERVATION','MISSING','EXISTING_WORK','OTHER']),name='clinical_finding_kind_valid'),
            models.CheckConstraint(condition=~Q(kind='MISSING')|Q(surface=''),name='clinical_missing_whole_tooth'),
        ]


class ClinicalRecordEvent(models.Model):
    actor=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    operation_id=models.UUIDField(unique=True)
    action=models.CharField(max_length=24)
    encounter=models.ForeignKey(ClinicalEncounter,null=True,blank=True,on_delete=models.PROTECT,related_name='events')
    history=models.ForeignKey(ClinicalHistoryVersion,null=True,blank=True,on_delete=models.PROTECT)
    record=models.ForeignKey(ClinicalRecordVersion,null=True,blank=True,on_delete=models.PROTECT)
    note=models.CharField(max_length=500,blank=True)
    snapshot=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table='adc_clinical_record_event'
