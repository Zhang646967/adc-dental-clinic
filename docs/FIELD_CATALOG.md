> 历史 v0.3 基础资料；新增功能、字段与证据请看 CHANGELOG_v0.4.md、AI_INTERFACE.md、TEST_REPORT.md。本文件的“尚未运行”仅指原编制时点。

# 全字段清单 v0.3

**从本包模型源码静态提取，不是数据库DESCRIBE或已执行SQL的输出。**

20个逻辑对象均有模型与迁移候选。外键默认按PROTECT策略使用，数据库对应引用约束另由迁移建立。UserAccount继承框架的用户名、哈希密码、登录、权限等字段；本清单突出本项目定义的字段，不冒充完全展开的框架DDL。

## registry.Clinic → `adc_clinic`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `clinic_code` | `models.CharField(max_length=24, unique=True)` |
| `name` | `models.CharField(max_length=120)` |
| `postal_address` | `models.CharField(max_length=255)` |
| `supervisor_name` | `models.CharField(max_length=80)` |
| `phone` | `models.CharField(max_length=32)` |
| `email` | `models.EmailField()` |
| `area_sqm` | `models.DecimalField(max_digits=10, decimal_places=2)` |
| `is_active` | `models.BooleanField(default=True)` |

约束源码：
```python
models.CheckConstraint(condition=Q(area_sqm__gt=0), name='clinic_area_positive')
```

## registry.Dentist → `adc_dentist`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `employee_no` | `models.CharField(max_length=24, unique=True)` |
| `name` | `models.CharField(max_length=80)` |
| `date_of_birth` | `models.DateField()` |
| `home_address` | `models.CharField(max_length=255)` |
| `phone` | `models.CharField(max_length=32)` |
| `email` | `models.EmailField()` |
| `is_active` | `models.BooleanField(default=True)` |

业务唯一键/外键等见上方字段定义。

## registry.Qualification → `adc_qualification`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `code` | `models.CharField(max_length=24, unique=True)` |
| `name` | `models.CharField(max_length=120)` |
| `is_active` | `models.BooleanField(default=True)` |

业务唯一键/外键等见上方字段定义。

## registry.DentistQualification → `adc_dentist_qualification`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `dentist` | `models.ForeignKey('registry.Dentist', on_delete=models.PROTECT, related_name='qualifications')` |
| `qualification` | `models.ForeignKey('registry.Qualification', on_delete=models.PROTECT)` |
| `notes` | `models.TextField(blank=True, default='')` |
| `is_active` | `models.BooleanField(default=True)` |

约束源码：
```python
models.UniqueConstraint(fields=['dentist', 'qualification'], name='dentist_qualification_unique')
```

## registry.Allergy → `adc_allergy`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `code` | `models.CharField(max_length=24, unique=True)` |
| `name` | `models.CharField(max_length=120)` |
| `is_active` | `models.BooleanField(default=True)` |

业务唯一键/外键等见上方字段定义。

## registry.TreatmentType → `adc_treatment_type`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `code` | `models.CharField(max_length=24, unique=True)` |
| `name` | `models.CharField(max_length=120)` |
| `unit_definition` | `models.CharField(max_length=120)` |
| `standard_unit_price` | `models.DecimalField(max_digits=12, decimal_places=2)` |
| `is_active` | `models.BooleanField(default=True)` |

约束源码：
```python
models.CheckConstraint(condition=Q(standard_unit_price__gte=0), name='treatment_price_nonnegative')
```

## accounts.UserAccount → `adc_user`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `dentist` | `models.OneToOneField('registry.Dentist', on_delete=models.PROTECT, null=True, blank=True)` |

业务唯一键/外键等见上方字段定义。

## accounts.RoleAssignment → `adc_role_assignment`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `user` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='role_assignments')` |
| `role` | `models.CharField(max_length=16, choices=(('FRONT_DESK', '前台'), ('DENTIST', '牙医'), ('MANAGER', '诊所主管'), ('HQ', '总部管理'), ('FINANCE', '财务'), ('SYSADMIN', '系统管理员')))` |
| `scope_kind` | `models.CharField(max_length=16, choices=(('CLINIC', '诊所'), ('SELF_DENTIST', '本人接诊'), ('CHAIN', '全链'), ('TECHNICAL', '技术管理')))` |
| `clinic` | `models.ForeignKey('registry.Clinic', on_delete=models.PROTECT, null=True, blank=True)` |
| `is_active` | `models.BooleanField(default=True)` |

约束源码：
```python
models.CheckConstraint(condition=Q(role__in=['FRONT_DESK', 'MANAGER'], scope_kind='CLINIC', clinic__isnull=False) | Q(role='DENTIST', scope_kind='SELF_DENTIST', clinic__isnull=True) | Q(role__in=['HQ', 'FINANCE'], scope_kind='CHAIN', clinic__isnull=True) | Q(role='SYSADMIN', scope_kind='TECHNICAL', clinic__isnull=True), name='role_scope_valid')
models.UniqueConstraint(fields=['user', 'role', 'scope_kind', 'clinic'], condition=Q(clinic__isnull=False), name='role_clinic_unique')
models.UniqueConstraint(fields=['user', 'role', 'scope_kind'], condition=Q(clinic__isnull=True), name='role_noclinic_unique')
```

## patients.Patient → `adc_patient`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `patient_no` | `models.CharField(max_length=40, unique=True, default=patient_no, editable=False)` |
| `name` | `models.CharField(max_length=80)` |
| `date_of_birth` | `models.DateField()` |
| `billing_address` | `models.CharField(max_length=255)` |
| `phone` | `models.CharField(max_length=32)` |
| `email` | `models.EmailField(blank=True, default='')` |
| `emergency_name` | `models.CharField(max_length=80)` |
| `emergency_phone` | `models.CharField(max_length=32)` |
| `allergy_status` | `models.CharField(max_length=12, default='UNKNOWN', choices=[('UNKNOWN', '未询问/未知'), ('NO_KNOWN', '已确认无已知过敏'), ('KNOWN', '已知过敏')])` |
| `allergy_info_version` | `models.PositiveIntegerField(default=1)` |
| `created_in_clinic` | `models.ForeignKey('registry.Clinic', on_delete=models.PROTECT, related_name='registered_patients')` |
| `is_active` | `models.BooleanField(default=True)` |

约束源码：
```python
models.CheckConstraint(condition=Q(allergy_status__in=['UNKNOWN', 'NO_KNOWN', 'KNOWN']), name='patient_allergy_status_valid')
models.CheckConstraint(condition=Q(allergy_info_version__gte=1), name='allergy_version_positive')
```

额外普通索引：
```python
models.Index(fields=['phone'], name='patient_phone_idx')
```

## patients.PatientAllergy → `adc_patient_allergy`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `patient` | `models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='allergy_links')` |
| `allergy` | `models.ForeignKey('registry.Allergy', on_delete=models.PROTECT)` |
| `notes` | `models.TextField(blank=True, default='')` |
| `is_active` | `models.BooleanField(default=True)` |

约束源码：
```python
models.UniqueConstraint(fields=['patient', 'allergy'], name='patient_allergy_unique')
```

## scheduling.AvailabilitySlot → `adc_availability_slot`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `dentist` | `models.ForeignKey('registry.Dentist', on_delete=models.PROTECT)` |
| `clinic` | `models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)` |
| `starts_at` | `models.DateTimeField()` |
| `ends_at` | `models.DateTimeField()` |
| `is_active` | `models.BooleanField(default=True)` |

约束源码：
```python
models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')), name='slot_time_order')
ExclusionConstraint(name='slot_dentist_no_overlap', expressions=[(TsTzRange('starts_at', 'ends_at', RangeBoundary()), RangeOperators.OVERLAPS), ('dentist', RangeOperators.EQUAL)], condition=Q(is_active=True))
```

## scheduling.Visit → `adc_visit`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `visit_no` | `models.CharField(max_length=40, unique=True, default=visit_no, editable=False)` |
| `patient` | `models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='visits')` |
| `dentist` | `models.ForeignKey('registry.Dentist', on_delete=models.PROTECT, related_name='visits')` |
| `clinic` | `models.ForeignKey('registry.Clinic', on_delete=models.PROTECT, related_name='visits')` |
| `availability_slot` | `models.ForeignKey('scheduling.AvailabilitySlot', on_delete=models.PROTECT, related_name='visits')` |
| `scheduled_start` | `models.DateTimeField()` |
| `scheduled_end` | `models.DateTimeField()` |
| `status` | `models.CharField(max_length=24, choices=(('SCHEDULED', '已预约'), ('CHECKED_IN', '已到诊'), ('COMPLETED', '治疗完成'), ('CLOSED_NO_TREATMENT', '无治疗关闭'), ('CANCELLED', '已取消'), ('NO_SHOW', '已爽约'), ('RESCHEDULED', '已改期替代')), default='SCHEDULED')` |
| `attended` | `models.BooleanField(default=False)` |
| `attended_at` | `models.DateTimeField(null=True, blank=True)` |
| `completed_at` | `models.DateTimeField(null=True, blank=True)` |
| `chief_complaint` | `models.TextField(blank=True, default='')` |
| `special_needs` | `models.TextField(blank=True, default='')` |
| `cancellation_party` | `models.CharField(max_length=8, blank=True, default='', choices=[('', '不适用'), ('PATIENT', '患者'), ('CLINIC', '诊所')])` |
| `cancellation_reason` | `models.TextField(blank=True, default='')` |
| `replaces_visit` | `models.OneToOneField('scheduling.Visit', on_delete=models.PROTECT, null=True, blank=True, related_name='replacement')` |
| `lock_version` | `models.PositiveIntegerField(default=0)` |
| `created_at` | `models.DateTimeField(auto_now_add=True)` |

约束源码：
```python
models.CheckConstraint(condition=Q(status__in=['SCHEDULED', 'CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT', 'CANCELLED', 'NO_SHOW', 'RESCHEDULED']), name='visit_status_valid')
models.CheckConstraint(condition=Q(scheduled_end__gt=F('scheduled_start')), name='visit_time_order')
models.CheckConstraint(condition=Q(status__in=('CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT'), attended=True, attended_at__isnull=False) | ~Q(status__in=('CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT')) & Q(attended=False, attended_at__isnull=True), name='visit_attendance_consistent')
models.CheckConstraint(condition=Q(status__in=('COMPLETED', 'CLOSED_NO_TREATMENT')) & Q(completed_at__isnull=False, completed_at__gte=F('attended_at')) | ~Q(status__in=('COMPLETED', 'CLOSED_NO_TREATMENT')) & Q(completed_at__isnull=True), name='visit_completion_consistent')
models.CheckConstraint(condition=Q(status='CANCELLED', cancellation_party__in=['PATIENT', 'CLINIC']) & ~Q(cancellation_reason='') | ~Q(status='CANCELLED') & Q(cancellation_party='', cancellation_reason=''), name='visit_cancellation_consistent')
models.CheckConstraint(condition=~Q(replaces_visit=F('id')), name='visit_not_replace_self')
ExclusionConstraint(name='visit_dentist_no_overlap', expressions=[(TsTzRange('scheduled_start', 'scheduled_end', RangeBoundary()), RangeOperators.OVERLAPS), ('dentist', RangeOperators.EQUAL)], condition=Q(status__in=('SCHEDULED', 'CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT')))
ExclusionConstraint(name='visit_patient_no_overlap', expressions=[(TsTzRange('scheduled_start', 'scheduled_end', RangeBoundary()), RangeOperators.OVERLAPS), ('patient', RangeOperators.EQUAL)], condition=Q(status__in=('SCHEDULED', 'CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT')))
```

额外普通索引：
```python
models.Index(fields=['clinic', 'scheduled_start'], name='visit_clinic_time_idx')
models.Index(fields=['dentist', 'completed_at'], name='visit_dentist_completed_idx')
```

## scheduling.VisitRequest → `adc_visit_request`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `visit` | `models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT, related_name='requests')` |
| `description` | `models.CharField(max_length=500)` |
| `treatment_type` | `models.ForeignKey('registry.TreatmentType', on_delete=models.PROTECT, null=True, blank=True)` |

业务唯一键/外键等见上方字段定义。

## care.CorrectionRequest → `adc_correction_request`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `visit` | `models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT)` |
| `kind` | `models.CharField(max_length=24, choices=[('APPOINTMENT_STATUS', '预约结果'), ('RECORD_CONTENT', '治疗内容')])` |
| `base_record_version` | `models.ForeignKey('care.VisitRecordVersion', on_delete=models.PROTECT, null=True, blank=True, related_name='based_corrections')` |
| `expected_visit_lock_version` | `models.PositiveIntegerField()` |
| `requester` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='requested_corrections')` |
| `reviewer` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_corrections')` |
| `dentist_confirmed_by` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='confirmed_corrections')` |
| `status` | `models.CharField(max_length=12, default='OPEN', choices=[('OPEN', '待审核'), ('APPLIED', '已应用'), ('REJECTED', '已拒绝'), ('WITHDRAWN', '已撤回')])` |
| `reason` | `models.TextField()` |
| `proposed_change` | `models.JSONField(default=dict)` |
| `requested_at` | `models.DateTimeField(auto_now_add=True)` |
| `applied_at` | `models.DateTimeField(null=True, blank=True)` |

约束源码：
```python
models.CheckConstraint(condition=Q(kind__in=['APPOINTMENT_STATUS', 'RECORD_CONTENT']), name='correction_kind_valid')
models.CheckConstraint(condition=Q(status__in=['OPEN', 'APPLIED', 'REJECTED', 'WITHDRAWN']), name='correction_status_valid')
models.CheckConstraint(condition=~Q(requester=F('reviewer')), name='correction_no_self_approval')
models.CheckConstraint(condition=Q(kind='APPOINTMENT_STATUS', base_record_version__isnull=True) | Q(kind='RECORD_CONTENT', base_record_version__isnull=False), name='correction_base_required')
models.CheckConstraint(condition=Q(status='APPLIED', reviewer__isnull=False, applied_at__isnull=False) | ~Q(status='APPLIED') & Q(applied_at__isnull=True), name='correction_applied_metadata')
models.UniqueConstraint(fields=['visit'], condition=Q(status='OPEN'), name='one_open_correction_per_visit')
```

## care.VisitRecordVersion → `adc_visit_record_version`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `visit` | `models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT, related_name='record_versions')` |
| `revision_no` | `models.PositiveIntegerField()` |
| `state` | `models.CharField(max_length=12, default='DRAFT', choices=[('DRAFT', '草稿'), ('PUBLISHED', '已发布'), ('ABANDONED', '已弃用')])` |
| `outcome` | `models.CharField(max_length=16, choices=[('TREATED', '有治疗'), ('NO_TREATMENT', '无治疗')])` |
| `previous_version` | `models.ForeignKey('care.VisitRecordVersion', on_delete=models.PROTECT, null=True, blank=True, related_name='next_versions')` |
| `correction_request` | `models.OneToOneField('care.CorrectionRequest', on_delete=models.PROTECT, null=True, blank=True, related_name='new_version')` |
| `prepared_by` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='prepared_versions')` |
| `reviewed_by` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_versions')` |
| `created_at` | `models.DateTimeField(auto_now_add=True)` |
| `published_at` | `models.DateTimeField(null=True, blank=True)` |
| `allergy_review_snapshot` | `models.JSONField(default=dict)` |
| `billing_header_snapshot` | `models.JSONField(default=dict)` |
| `clinical_note` | `models.TextField(blank=True, default='')` |
| `no_treatment_reason` | `models.TextField(blank=True, default='')` |
| `total_amount` | `models.DecimalField(max_digits=16, decimal_places=2, default=0)` |
| `currency` | `models.CharField(max_length=3, default='CNY')` |

约束源码：
```python
models.UniqueConstraint(fields=['visit', 'revision_no'], name='visit_revision_unique')
models.UniqueConstraint(fields=['id', 'visit'], name='version_id_visit_unique')
models.UniqueConstraint(fields=['visit'], condition=Q(state='DRAFT'), name='one_draft_per_visit')
models.CheckConstraint(condition=Q(revision_no__gte=1), name='revision_positive')
models.CheckConstraint(condition=Q(state__in=['DRAFT', 'PUBLISHED', 'ABANDONED']), name='version_state_valid')
models.CheckConstraint(condition=Q(outcome__in=['TREATED', 'NO_TREATMENT']), name='version_outcome_valid')
models.CheckConstraint(condition=Q(total_amount__gte=0, currency='CNY'), name='version_money_valid')
models.CheckConstraint(condition=Q(state='PUBLISHED', published_at__isnull=False) | ~Q(state='PUBLISHED') & Q(published_at__isnull=True), name='version_publish_metadata')
models.CheckConstraint(condition=~Q(previous_version=F('id')), name='version_not_previous_self')
```

## care.TreatmentRecord → `adc_treatment_record`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `record_version` | `models.ForeignKey('care.VisitRecordVersion', on_delete=models.PROTECT, related_name='treatment_lines')` |
| `line_no` | `models.PositiveIntegerField()` |
| `treatment_type` | `models.ForeignKey('registry.TreatmentType', on_delete=models.PROTECT)` |
| `name_snapshot` | `models.CharField(max_length=120)` |
| `unit_snapshot` | `models.CharField(max_length=120)` |
| `quantity` | `models.DecimalField(max_digits=12, decimal_places=3)` |
| `unit_price` | `models.DecimalField(max_digits=12, decimal_places=2)` |
| `line_amount` | `models.DecimalField(max_digits=16, decimal_places=2)` |
| `confirmed_by` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True)` |
| `confirmed_at` | `models.DateTimeField(null=True, blank=True)` |
| `price_reason` | `models.CharField(max_length=500, blank=True, default='')` |

约束源码：
```python
models.UniqueConstraint(fields=['record_version', 'line_no'], name='record_line_unique')
models.CheckConstraint(condition=Q(line_no__gte=1, quantity__gt=0, unit_price__gte=0, line_amount__gte=0), name='record_values_valid')
models.CheckConstraint(condition=Q(unit_price__gt=0) | ~Q(price_reason=''), name='zero_price_reason_required')
models.CheckConstraint(condition=Q(confirmed_by__isnull=True, confirmed_at__isnull=True) | Q(confirmed_by__isnull=False, confirmed_at__isnull=False), name='line_confirmation_consistent')
```

## care.Invoice → `adc_invoice`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `invoice_no` | `models.CharField(max_length=40, unique=True, default=invoice_no, editable=False)` |
| `visit` | `models.OneToOneField('scheduling.Visit', on_delete=models.PROTECT, related_name='invoice')` |
| `current_record_version` | `models.OneToOneField('care.VisitRecordVersion', on_delete=models.PROTECT, related_name='current_invoice')` |
| `first_issued_at` | `models.DateTimeField(auto_now_add=True)` |

业务唯一键/外键等见上方字段定义。

## care.AuditEvent → `adc_audit_event`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `actor` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True)` |
| `visit` | `models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT, null=True, blank=True, related_name='events')` |
| `correction_request` | `models.ForeignKey('care.CorrectionRequest', on_delete=models.PROTECT, null=True, blank=True)` |
| `event_type` | `models.CharField(max_length=48)` |
| `occurred_at` | `models.DateTimeField()` |
| `recorded_at` | `models.DateTimeField(auto_now_add=True)` |
| `subject_type` | `models.CharField(max_length=32)` |
| `subject_key` | `models.CharField(max_length=80)` |
| `reason` | `models.CharField(max_length=500, blank=True, default='')` |
| `change_summary` | `models.JSONField(default=dict)` |

业务唯一键/外键等见上方字段定义。

额外普通索引：
```python
models.Index(fields=['subject_type', 'subject_key', 'recorded_at'], name='audit_subject_time_idx')
```

## finance.Quarter → `adc_quarter`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `year` | `models.PositiveSmallIntegerField()` |
| `quarter_no` | `models.PositiveSmallIntegerField()` |
| `roster_status` | `models.CharField(max_length=12, default='DRAFT', choices=[('DRAFT', '未确认'), ('CONFIRMED', '已确认')])` |
| `roster_confirmed_by` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True)` |
| `roster_confirmed_at` | `models.DateTimeField(null=True, blank=True)` |

约束源码：
```python
models.UniqueConstraint(fields=['year', 'quarter_no'], name='quarter_unique')
models.CheckConstraint(condition=Q(year__gte=1900, year__lte=9998, quarter_no__gte=1, quarter_no__lte=4), name='quarter_range_valid')
models.CheckConstraint(condition=Q(roster_status='CONFIRMED', roster_confirmed_by__isnull=False, roster_confirmed_at__isnull=False) | Q(roster_status='DRAFT', roster_confirmed_by__isnull=True, roster_confirmed_at__isnull=True), name='quarter_confirmation_valid')
```

## finance.DentistQuarterCost → `adc_dentist_quarter_cost`

| 字段 | Django定义（含长度、精度和空值选项） |
|---|---|
| `id` | `models.BigAutoField(primary_key=True)` |
| `quarter` | `models.ForeignKey('finance.Quarter', on_delete=models.PROTECT, related_name='dentist_costs')` |
| `dentist` | `models.ForeignKey('registry.Dentist', on_delete=models.PROTECT)` |
| `cost_status` | `models.CharField(max_length=12, default='MISSING', choices=[('MISSING', '未录入'), ('DRAFT', '草稿'), ('CONFIRMED', '已确认')])` |
| `supply_cost` | `models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)` |
| `operating_expense` | `models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)` |
| `confirmed_by` | `models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True)` |
| `confirmed_at` | `models.DateTimeField(null=True, blank=True)` |
| `notes` | `models.TextField(blank=True, default='')` |

约束源码：
```python
models.UniqueConstraint(fields=['quarter', 'dentist'], name='dentist_quarter_unique')
models.CheckConstraint(condition=Q(cost_status__in=['MISSING', 'DRAFT', 'CONFIRMED']), name='cost_status_valid')
models.CheckConstraint(condition=(Q(supply_cost__isnull=True) | Q(supply_cost__gte=0)) & (Q(operating_expense__isnull=True) | Q(operating_expense__gte=0)), name='cost_nonnegative')
models.CheckConstraint(condition=Q(cost_status='CONFIRMED', supply_cost__isnull=False, operating_expense__isnull=False, confirmed_by__isnull=False, confirmed_at__isnull=False) | ~Q(cost_status='CONFIRMED') & Q(confirmed_by__isnull=True, confirmed_at__isnull=True), name='cost_confirmation_valid')
models.CheckConstraint(condition=~Q(cost_status='MISSING') | Q(supply_cost__isnull=True, operating_expense__isnull=True), name='missing_cost_is_null')
```
