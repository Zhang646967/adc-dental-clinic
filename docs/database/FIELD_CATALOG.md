# 当前数据库字段目录

结构基线日期：2026-10-20。本目录列出68张ORM业务／框架表；另1张django_migrations为框架迁移日志。

字段类型、可空、SQL约束及索引来自数据库只读结构核对；模型映射来自同版本已运行应用。没有读取任何业务行、密码、配置值或字段默认值。

PK=主键；UK=单列唯一；FK=外键；NULL=可空。复合唯一、条件唯一和排斥约束另列，不用单列UK代替。

## adc_ai_usage_bucket

模型：`assistants.UsageBucket`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| key | character varying(100) | UK | 否 | — |
| used | integer | — | 否 | — |

数据库约束：

- `adc_ai_usage_bucket_key_key`：`UNIQUE (key)`。
- `adc_ai_usage_bucket_pkey`：`PRIMARY KEY (id)`。
- `adc_ai_usage_bucket_used_check`：`CHECK ((used >= 0))`。

索引（含条件唯一索引）：

- `adc_ai_usage_bucket_key_d220a79a_like`：`CREATE INDEX adc_ai_usage_bucket_key_d220a79a_like ON public.adc_ai_usage_bucket USING btree (key varchar_pattern_ops)`。
- `adc_ai_usage_bucket_key_key`：`CREATE UNIQUE INDEX adc_ai_usage_bucket_key_key ON public.adc_ai_usage_bucket USING btree (key)`。
- `adc_ai_usage_bucket_pkey`：`CREATE UNIQUE INDEX adc_ai_usage_bucket_pkey ON public.adc_ai_usage_bucket USING btree (id)`。

跨表及历史触发器：


## adc_allergy

模型：`registry.Allergy`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| code | character varying(24) | UK | 否 | — |
| name | character varying(120) | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_allergy_code_key`：`UNIQUE (code)`。
- `adc_allergy_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `adc_allergy_code_88ac287b_like`：`CREATE INDEX adc_allergy_code_88ac287b_like ON public.adc_allergy USING btree (code varchar_pattern_ops)`。
- `adc_allergy_code_key`：`CREATE UNIQUE INDEX adc_allergy_code_key ON public.adc_allergy USING btree (code)`。
- `adc_allergy_pkey`：`CREATE UNIQUE INDEX adc_allergy_pkey ON public.adc_allergy USING btree (id)`。

跨表及历史触发器：


## adc_appointment_action_event

模型：`operations.AppointmentActionEvent`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| followup_id | bigint | FK | 是 | `adc_cancellation_followup.id` |
| improvement_id | bigint | FK | 是 | `adc_appointment_improvement.id` |
| operation_id | uuid | UK | 否 | — |
| actor_id | bigint | FK | 否 | `adc_user.id` |
| action | character varying(16) | — | 否 | — |
| snapshot | jsonb | — | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_appointment_acti_followup_id_725fe406_fk_adc_cance`：`FOREIGN KEY (followup_id) REFERENCES adc_cancellation_followup(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_appointment_acti_improvement_id_8a168f3c_fk_adc_appoi`：`FOREIGN KEY (improvement_id) REFERENCES adc_appointment_improvement(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_appointment_action_event_actor_id_991de65f_fk_adc_user_id`：`FOREIGN KEY (actor_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_appointment_action_event_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_appointment_action_event_pkey`：`PRIMARY KEY (id)`。
- `appointment_event_one_owner`：`CHECK ((((followup_id IS NOT NULL) AND (improvement_id IS NULL)) OR ((followup_id IS NULL) AND (improvement_id IS NOT NULL))))`。

索引（含条件唯一索引）：

- `adc_appointment_action_event_actor_id_991de65f`：`CREATE INDEX adc_appointment_action_event_actor_id_991de65f ON public.adc_appointment_action_event USING btree (actor_id)`。
- `adc_appointment_action_event_followup_id_725fe406`：`CREATE INDEX adc_appointment_action_event_followup_id_725fe406 ON public.adc_appointment_action_event USING btree (followup_id)`。
- `adc_appointment_action_event_improvement_id_8a168f3c`：`CREATE INDEX adc_appointment_action_event_improvement_id_8a168f3c ON public.adc_appointment_action_event USING btree (improvement_id)`。
- `adc_appointment_action_event_operation_id_key`：`CREATE UNIQUE INDEX adc_appointment_action_event_operation_id_key ON public.adc_appointment_action_event USING btree (operation_id)`。
- `adc_appointment_action_event_pkey`：`CREATE UNIQUE INDEX adc_appointment_action_event_pkey ON public.adc_appointment_action_event USING btree (id)`。

跨表及历史触发器：

- `appointment_history_immutable`：`CREATE TRIGGER appointment_history_immutable BEFORE DELETE OR UPDATE ON public.adc_appointment_action_event FOR EACH ROW EXECUTE FUNCTION adc_appointment_history_immutable()`。

## adc_appointment_improvement

模型：`operations.AppointmentImprovement`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| weekday | smallint | — | 否 | — |
| band | character varying(8) | — | 否 | — |
| baseline_start | date | — | 否 | — |
| baseline_end | date | — | 否 | — |
| kind | character varying(16) | — | 否 | — |
| plan | character varying(500) | — | 否 | — |
| assigned_to_id | bigint | FK | 否 | `adc_user.id` |
| due_on | date | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| execution | character varying(500) | — | 否 | — |
| submitted_by_id | bigint | FK | 是 | `adc_user.id` |
| reviewed_by_id | bigint | FK | 是 | `adc_user.id` |
| review_start | date | — | 是 | — |
| review_end | date | — | 是 | — |
| assessment | character varying(16) | — | 否 | — |
| review_note | character varying(500) | — | 否 | — |
| baseline | jsonb | — | 否 | — |
| comparison | jsonb | — | 否 | — |
| lock_version | integer | — | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_appointment_impr_assigned_to_id_cac0d69e_fk_adc_user_`：`FOREIGN KEY (assigned_to_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_appointment_impr_reviewed_by_id_19d385a6_fk_adc_user_`：`FOREIGN KEY (reviewed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_appointment_impr_submitted_by_id_1766aec5_fk_adc_user_`：`FOREIGN KEY (submitted_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_appointment_improvement_clinic_id_259f81d0_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_appointment_improvement_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_appointment_improvement_pkey`：`PRIMARY KEY (id)`。
- `adc_appointment_improvement_weekday_check`：`CHECK ((weekday >= 0))`。
- `improve_band`：`CHECK (((band)::text = ANY ((ARRAY['08_10'::character varying, '10_12'::character varying, '12_14'::character varying, '14_16'::character varying, '16_18'::character varying, '18_20'::character varying, 'OTHER'::character varying])::text[])))`。
- `improve_period`：`CHECK ((baseline_end >= baseline_start))`。
- `improve_review_independent`：`CHECK (((NOT ((state)::text = 'CLOSED'::text)) OR ((review_end IS NOT NULL) AND (review_start IS NOT NULL) AND (reviewed_by_id IS NOT NULL) AND (submitted_by_id IS NOT NULL) AND (NOT ((reviewed_by_id = submitted_by_id) AND (reviewed_by_id IS NOT NULL) AND (submitted_by_id IS NOT NULL))) AND (NOT ((reviewed_by_id = assigned_to_id) AND (reviewed_by_id IS NOT NULL))))))`。
- `improve_state`：`CHECK (((state)::text = ANY ((ARRAY['OPEN'::character varying, 'WORKING'::character varying, 'READY'::character varying, 'CLOSED'::character varying, 'CANCELLED'::character varying])::text[])))`。
- `improve_weekday`：`CHECK (((weekday >= 1) AND (weekday <= 7)))`。

索引（含条件唯一索引）：

- `adc_appointment_improvement_assigned_to_id_cac0d69e`：`CREATE INDEX adc_appointment_improvement_assigned_to_id_cac0d69e ON public.adc_appointment_improvement USING btree (assigned_to_id)`。
- `adc_appointment_improvement_clinic_id_259f81d0`：`CREATE INDEX adc_appointment_improvement_clinic_id_259f81d0 ON public.adc_appointment_improvement USING btree (clinic_id)`。
- `adc_appointment_improvement_pkey`：`CREATE UNIQUE INDEX adc_appointment_improvement_pkey ON public.adc_appointment_improvement USING btree (id)`。
- `adc_appointment_improvement_reviewed_by_id_19d385a6`：`CREATE INDEX adc_appointment_improvement_reviewed_by_id_19d385a6 ON public.adc_appointment_improvement USING btree (reviewed_by_id)`。
- `adc_appointment_improvement_submitted_by_id_1766aec5`：`CREATE INDEX adc_appointment_improvement_submitted_by_id_1766aec5 ON public.adc_appointment_improvement USING btree (submitted_by_id)`。
- `improve_clinic_state_due`：`CREATE INDEX improve_clinic_state_due ON public.adc_appointment_improvement USING btree (clinic_id, state, due_on)`。

跨表及历史触发器：


## adc_assistant_event

模型：`assistants.AssistantEvent`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| request_id | uuid | UK | 否 | — |
| user_id | bigint | FK | 否 | `adc_user.id` |
| audience | character varying(12) | — | 否 | — |
| intent | character varying(32) | — | 否 | — |
| mode | character varying(24) | — | 否 | — |
| result_code | character varying(40) | — | 否 | — |
| input_chars | integer | — | 否 | — |
| duration_ms | integer | — | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_assistant_event_duration_ms_check`：`CHECK ((duration_ms >= 0))`。
- `adc_assistant_event_input_chars_check`：`CHECK ((input_chars >= 0))`。
- `adc_assistant_event_pkey`：`PRIMARY KEY (id)`。
- `adc_assistant_event_request_id_key`：`UNIQUE (request_id)`。
- `adc_assistant_event_user_id_32ab42ac_fk_adc_user_id`：`FOREIGN KEY (user_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。

索引（含条件唯一索引）：

- `adc_assistant_event_pkey`：`CREATE UNIQUE INDEX adc_assistant_event_pkey ON public.adc_assistant_event USING btree (id)`。
- `adc_assistant_event_request_id_key`：`CREATE UNIQUE INDEX adc_assistant_event_request_id_key ON public.adc_assistant_event USING btree (request_id)`。
- `adc_assistant_event_user_id_32ab42ac`：`CREATE INDEX adc_assistant_event_user_id_32ab42ac ON public.adc_assistant_event USING btree (user_id)`。

跨表及历史触发器：


## adc_audit_event

模型：`care.AuditEvent`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| actor_id | bigint | FK | 是 | `adc_user.id` |
| visit_id | bigint | FK | 是 | `adc_visit.id` |
| correction_request_id | bigint | FK | 是 | `adc_correction_request.id` |
| event_type | character varying(48) | — | 否 | — |
| occurred_at | timestamp with time zone | — | 否 | — |
| recorded_at | timestamp with time zone | — | 否 | — |
| subject_type | character varying(32) | — | 否 | — |
| subject_key | character varying(80) | — | 否 | — |
| reason | character varying(500) | — | 否 | — |
| change_summary | jsonb | — | 否 | — |

数据库约束：

- `adc_audit_event_actor_id_3e8fb4f4_fk_adc_user_id`：`FOREIGN KEY (actor_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_audit_event_correction_request_i_7fafd744_fk_adc_corre`：`FOREIGN KEY (correction_request_id) REFERENCES adc_correction_request(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_audit_event_pkey`：`PRIMARY KEY (id)`。
- `adc_audit_event_visit_id_155d86a2_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。

索引（含条件唯一索引）：

- `adc_audit_event_actor_id_3e8fb4f4`：`CREATE INDEX adc_audit_event_actor_id_3e8fb4f4 ON public.adc_audit_event USING btree (actor_id)`。
- `adc_audit_event_correction_request_id_7fafd744`：`CREATE INDEX adc_audit_event_correction_request_id_7fafd744 ON public.adc_audit_event USING btree (correction_request_id)`。
- `adc_audit_event_pkey`：`CREATE UNIQUE INDEX adc_audit_event_pkey ON public.adc_audit_event USING btree (id)`。
- `adc_audit_event_visit_id_155d86a2`：`CREATE INDEX adc_audit_event_visit_id_155d86a2 ON public.adc_audit_event USING btree (visit_id)`。
- `audit_subject_time_idx`：`CREATE INDEX audit_subject_time_idx ON public.adc_audit_event USING btree (subject_type, subject_key, recorded_at)`。

跨表及历史触发器：

- `audit_history_guard`：`CREATE TRIGGER audit_history_guard BEFORE DELETE OR UPDATE ON public.adc_audit_event FOR EACH ROW EXECUTE FUNCTION adc_protect_audit()`。

## adc_availability_slot

模型：`scheduling.AvailabilitySlot`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| dentist_id | bigint | FK | 否 | `adc_dentist.id` |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| starts_at | timestamp with time zone | — | 否 | — |
| ends_at | timestamp with time zone | — | 否 | — |
| is_active | boolean | — | 否 | — |
| booking_paused | boolean | — | 否 | — |
| intake_revision | integer | — | 否 | — |

数据库约束：

- `adc_availability_slot_clinic_id_f510d79d_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_availability_slot_dentist_id_cd3e15fc_fk_adc_dentist_id`：`FOREIGN KEY (dentist_id) REFERENCES adc_dentist(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_availability_slot_intake_revision_check`：`CHECK ((intake_revision >= 0))`。
- `adc_availability_slot_pkey`：`PRIMARY KEY (id)`。
- `slot_dentist_no_overlap`：`EXCLUDE USING gist (tstzrange(starts_at, ends_at, '[)'::text) WITH &&, dentist_id WITH =) WHERE (is_active)`。
- `slot_time_order`：`CHECK ((ends_at > starts_at))`。

索引（含条件唯一索引）：

- `adc_availability_slot_clinic_id_f510d79d`：`CREATE INDEX adc_availability_slot_clinic_id_f510d79d ON public.adc_availability_slot USING btree (clinic_id)`。
- `adc_availability_slot_dentist_id_cd3e15fc`：`CREATE INDEX adc_availability_slot_dentist_id_cd3e15fc ON public.adc_availability_slot USING btree (dentist_id)`。
- `adc_availability_slot_pkey`：`CREATE UNIQUE INDEX adc_availability_slot_pkey ON public.adc_availability_slot USING btree (id)`。
- `slot_clinic_start_idx`：`CREATE INDEX slot_clinic_start_idx ON public.adc_availability_slot USING btree (clinic_id, starts_at)`。
- `slot_dentist_no_overlap`：`CREATE INDEX slot_dentist_no_overlap ON public.adc_availability_slot USING gist (tstzrange(starts_at, ends_at, '[)'::text), dentist_id) WHERE is_active`。

跨表及历史触发器：

- `slot_history_guard`：`CREATE TRIGGER slot_history_guard BEFORE UPDATE ON public.adc_availability_slot FOR EACH ROW EXECUTE FUNCTION adc_protect_slot()`。

## adc_booking_service

模型：`scheduling.BookingService`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| department_id | bigint | FK | 否 | `adc_department.id` |
| code | character varying(40) | — | 否 | — |
| name | character varying(100) | — | 否 | — |
| duration_minutes | smallint | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_booking_service_department_id_b1cf9fa9_fk_adc_department_id`：`FOREIGN KEY (department_id) REFERENCES adc_department(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_booking_service_duration_minutes_check`：`CHECK ((duration_minutes >= 0))`。
- `adc_booking_service_pkey`：`PRIMARY KEY (id)`。
- `service_department_code`：`UNIQUE (department_id, code)`。
- `service_duration_valid`：`CHECK ((duration_minutes = ANY (ARRAY[15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180, 195, 210, 225, 240])))`。

索引（含条件唯一索引）：

- `adc_booking_service_department_id_b1cf9fa9`：`CREATE INDEX adc_booking_service_department_id_b1cf9fa9 ON public.adc_booking_service USING btree (department_id)`。
- `adc_booking_service_pkey`：`CREATE UNIQUE INDEX adc_booking_service_pkey ON public.adc_booking_service USING btree (id)`。
- `service_department_code`：`CREATE UNIQUE INDEX service_department_code ON public.adc_booking_service USING btree (department_id, code)`。

跨表及历史触发器：


## adc_booking_service_dentists

模型：`scheduling.BookingService_dentists`；ORM生成的连接表。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| bookingservice_id | bigint | FK | 否 | `adc_booking_service.id` |
| dentist_id | bigint | FK | 否 | `adc_dentist.id` |

数据库约束：

- `adc_booking_service__bookingservice_id_cd23e050_fk_adc_booki`：`FOREIGN KEY (bookingservice_id) REFERENCES adc_booking_service(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_booking_service__dentist_id_51362169_fk_adc_denti`：`FOREIGN KEY (dentist_id) REFERENCES adc_dentist(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_booking_service_dent_bookingservice_id_dentis_13f7641e_uniq`：`UNIQUE (bookingservice_id, dentist_id)`。
- `adc_booking_service_dentists_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `adc_booking_service_dent_bookingservice_id_dentis_13f7641e_uniq`：`CREATE UNIQUE INDEX adc_booking_service_dent_bookingservice_id_dentis_13f7641e_uniq ON public.adc_booking_service_dentists USING btree (bookingservice_id, dentist_id)`。
- `adc_booking_service_dentists_bookingservice_id_cd23e050`：`CREATE INDEX adc_booking_service_dentists_bookingservice_id_cd23e050 ON public.adc_booking_service_dentists USING btree (bookingservice_id)`。
- `adc_booking_service_dentists_dentist_id_51362169`：`CREATE INDEX adc_booking_service_dentists_dentist_id_51362169 ON public.adc_booking_service_dentists USING btree (dentist_id)`。
- `adc_booking_service_dentists_pkey`：`CREATE UNIQUE INDEX adc_booking_service_dentists_pkey ON public.adc_booking_service_dentists USING btree (id)`。

跨表及历史触发器：


## adc_cancellation_followup

模型：`operations.CancellationFollowUp`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| visit_id | bigint | UK / FK | 否 | `adc_visit.id` |
| reason_code | character varying(16) | — | 否 | — |
| state | character varying(16) | — | 否 | — |
| assigned_to_id | bigint | FK | 否 | `adc_user.id` |
| due_on | date | — | 是 | — |
| replacement_visit_id | bigint | FK | 是 | `adc_visit.id` |
| note | character varying(500) | — | 否 | — |
| lock_version | integer | — | 否 | — |
| updated_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_cancellation_fol_assigned_to_id_8b7042c1_fk_adc_user_`：`FOREIGN KEY (assigned_to_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cancellation_fol_replacement_visit_id_d62bf875_fk_adc_visit`：`FOREIGN KEY (replacement_visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cancellation_followup_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_cancellation_followup_pkey`：`PRIMARY KEY (id)`。
- `adc_cancellation_followup_visit_id_ae359afa_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cancellation_followup_visit_id_key`：`UNIQUE (visit_id)`。
- `cancel_follow_booking`：`CHECK (((NOT ((state)::text = 'REBOOKED'::text)) OR (replacement_visit_id IS NOT NULL)))`。
- `cancel_follow_pending_due`：`CHECK (((NOT ((state)::text = ANY ((ARRAY['OPEN'::character varying, 'WAITING'::character varying])::text[]))) OR (due_on IS NOT NULL)))`。
- `cancel_follow_reason`：`CHECK (((reason_code)::text = ANY ((ARRAY['UNSUPPLIED'::character varying, 'SCHEDULE'::character varying, 'CONTACT'::character varying, 'COST'::character varying, 'CLINIC'::character varying, 'OTHER'::character varying])::text[])))`。
- `cancel_follow_state`：`CHECK (((state)::text = ANY ((ARRAY['OPEN'::character varying, 'WAITING'::character varying, 'REBOOKED'::character varying, 'DECLINED'::character varying, 'NO_ACTION'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_cancellation_followup_assigned_to_id_8b7042c1`：`CREATE INDEX adc_cancellation_followup_assigned_to_id_8b7042c1 ON public.adc_cancellation_followup USING btree (assigned_to_id)`。
- `adc_cancellation_followup_pkey`：`CREATE UNIQUE INDEX adc_cancellation_followup_pkey ON public.adc_cancellation_followup USING btree (id)`。
- `adc_cancellation_followup_replacement_visit_id_d62bf875`：`CREATE INDEX adc_cancellation_followup_replacement_visit_id_d62bf875 ON public.adc_cancellation_followup USING btree (replacement_visit_id)`。
- `adc_cancellation_followup_visit_id_key`：`CREATE UNIQUE INDEX adc_cancellation_followup_visit_id_key ON public.adc_cancellation_followup USING btree (visit_id)`。

跨表及历史触发器：


## adc_cash_entry

模型：`finance.CashEntry`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| operation_id | uuid | UK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| invoice_id | bigint | FK | 是 | `adc_invoice.id` |
| based_record_version_id | bigint | FK | 是 | `adc_visit_record_version.id` |
| equipment_event_id | bigint | FK | 是 | `adc_equipment_event.id` |
| equipment_cost_amendment_id | bigint | FK | 是 | `adc_equipment_cost_amendment.id` |
| reversal_of_id | bigint | FK | 是 | `adc_cash_entry.id` |
| kind | character varying(24) | — | 否 | — |
| amount | numeric(16,2) | — | 否 | — |
| occurred_on | date | — | 否 | — |
| reason | character varying(500) | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| lock_version | integer | — | 否 | — |
| prepared_by_id | bigint | FK | 否 | `adc_user.id` |
| prepared_at | timestamp with time zone | — | 否 | — |
| reviewed_by_id | bigint | FK | 是 | `adc_user.id` |
| reviewed_at | timestamp with time zone | — | 是 | — |
| review_reason | character varying(500) | — | 否 | — |

数据库约束：

- `adc_cash_entry_based_record_version_22b48b6f_fk_adc_visit`：`FOREIGN KEY (based_record_version_id) REFERENCES adc_visit_record_version(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_entry_clinic_id_6376e513_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_entry_equipment_cost_amend_57ace712_fk_adc_equip`：`FOREIGN KEY (equipment_cost_amendment_id) REFERENCES adc_equipment_cost_amendment(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_entry_equipment_event_id_4633ba3f_fk_adc_equip`：`FOREIGN KEY (equipment_event_id) REFERENCES adc_equipment_event(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_entry_invoice_id_71163834_fk_adc_invoice_id`：`FOREIGN KEY (invoice_id) REFERENCES adc_invoice(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_entry_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_cash_entry_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_cash_entry_pkey`：`PRIMARY KEY (id)`。
- `adc_cash_entry_prepared_by_id_9c735baa_fk_adc_user_id`：`FOREIGN KEY (prepared_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_entry_reversal_of_id_dd479024_fk_adc_cash_entry_id`：`FOREIGN KEY (reversal_of_id) REFERENCES adc_cash_entry(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_entry_reviewed_by_id_f7f3a418_fk_adc_user_id`：`FOREIGN KEY (reviewed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `cash_amount_positive`：`CHECK ((amount > (0)::numeric))`。
- `cash_cost_requires_equipment`：`CHECK (((equipment_cost_amendment_id IS NULL) OR (equipment_event_id IS NOT NULL)))`。
- `cash_exact_source`：`CHECK ((((based_record_version_id IS NOT NULL) AND (equipment_event_id IS NULL) AND (invoice_id IS NOT NULL) AND ((kind)::text = ANY ((ARRAY['RECEIPT'::character varying, 'REFUND'::character varying])::text[]))) OR ((based_record_version_id IS NULL) AND (equipment_event_id IS NOT NULL) AND (invoice_id IS NULL) AND ((kind)::text = ANY ((ARRAY['EQUIPMENT_EXPENSE'::character varying, 'EXPENSE_REVERSAL'::character varying])::text[])))))`。
- `cash_kind_valid`：`CHECK (((kind)::text = ANY ((ARRAY['RECEIPT'::character varying, 'REFUND'::character varying, 'EQUIPMENT_EXPENSE'::character varying, 'EXPENSE_REVERSAL'::character varying])::text[])))`。
- `cash_no_self_review`：`CHECK ((NOT ((prepared_by_id = reviewed_by_id) AND (reviewed_by_id IS NOT NULL))))`。
- `cash_review_metadata`：`CHECK ((((lock_version = 0) AND (reviewed_at IS NULL) AND (reviewed_by_id IS NULL) AND ((state)::text = 'PENDING'::text)) OR ((lock_version = 1) AND (reviewed_at IS NOT NULL) AND (reviewed_by_id IS NOT NULL) AND ((state)::text = ANY ((ARRAY['POSTED'::character varying, 'REJECTED'::character varying])::text[])))))`。
- `cash_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['PENDING'::character varying, 'POSTED'::character varying, 'REJECTED'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_cash_entry_based_record_version_id_22b48b6f`：`CREATE INDEX adc_cash_entry_based_record_version_id_22b48b6f ON public.adc_cash_entry USING btree (based_record_version_id)`。
- `adc_cash_entry_clinic_id_6376e513`：`CREATE INDEX adc_cash_entry_clinic_id_6376e513 ON public.adc_cash_entry USING btree (clinic_id)`。
- `adc_cash_entry_equipment_cost_amendment_id_57ace712`：`CREATE INDEX adc_cash_entry_equipment_cost_amendment_id_57ace712 ON public.adc_cash_entry USING btree (equipment_cost_amendment_id)`。
- `adc_cash_entry_equipment_event_id_4633ba3f`：`CREATE INDEX adc_cash_entry_equipment_event_id_4633ba3f ON public.adc_cash_entry USING btree (equipment_event_id)`。
- `adc_cash_entry_invoice_id_71163834`：`CREATE INDEX adc_cash_entry_invoice_id_71163834 ON public.adc_cash_entry USING btree (invoice_id)`。
- `adc_cash_entry_operation_id_key`：`CREATE UNIQUE INDEX adc_cash_entry_operation_id_key ON public.adc_cash_entry USING btree (operation_id)`。
- `adc_cash_entry_pkey`：`CREATE UNIQUE INDEX adc_cash_entry_pkey ON public.adc_cash_entry USING btree (id)`。
- `adc_cash_entry_prepared_by_id_9c735baa`：`CREATE INDEX adc_cash_entry_prepared_by_id_9c735baa ON public.adc_cash_entry USING btree (prepared_by_id)`。
- `adc_cash_entry_reversal_of_id_dd479024`：`CREATE INDEX adc_cash_entry_reversal_of_id_dd479024 ON public.adc_cash_entry USING btree (reversal_of_id)`。
- `adc_cash_entry_reviewed_by_id_f7f3a418`：`CREATE INDEX adc_cash_entry_reviewed_by_id_f7f3a418 ON public.adc_cash_entry USING btree (reviewed_by_id)`。
- `cash_clinic_day_idx`：`CREATE INDEX cash_clinic_day_idx ON public.adc_cash_entry USING btree (clinic_id, occurred_on)`。
- `cash_clinic_state_date_idx`：`CREATE INDEX cash_clinic_state_date_idx ON public.adc_cash_entry USING btree (clinic_id, state, occurred_on)`。
- `cash_one_live_reversal`：`CREATE UNIQUE INDEX cash_one_live_reversal ON public.adc_cash_entry USING btree (reversal_of_id) WHERE ((reversal_of_id IS NOT NULL) AND ((state)::text = ANY ((ARRAY['PENDING'::character varying, 'POSTED'::character varying])::text[])))`。

跨表及历史触发器：

- `aaa_daily_cash_lock`：`CREATE TRIGGER aaa_daily_cash_lock BEFORE INSERT OR UPDATE ON public.adc_cash_entry FOR EACH ROW EXECUTE FUNCTION adc_daily_cash_lock()`。
- `cash_entry_history`：`CREATE TRIGGER cash_entry_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_cash_entry FOR EACH ROW EXECUTE FUNCTION adc_cash_history_guard()`。

## adc_cash_evidence

模型：`finance.CashEvidenceVersion`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| cash_entry_id | bigint | FK | 否 | `adc_cash_entry.id` |
| account_id | bigint | FK | 否 | `adc_payment_account.id` |
| reference | character varying(80) | — | 否 | — |
| version | integer | — | 否 | — |
| previous_id | bigint | UK / FK | 是 | `adc_cash_evidence.id` |
| initial | boolean | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| operation_id | uuid | UK | 否 | — |
| prepared_by_id | bigint | FK | 否 | `adc_user.id` |
| prepared_at | timestamp with time zone | — | 否 | — |
| reason | character varying(500) | — | 否 | — |
| reviewed_by_id | bigint | FK | 是 | `adc_user.id` |
| reviewed_at | timestamp with time zone | — | 是 | — |
| review_reason | character varying(500) | — | 否 | — |

数据库约束：

- `adc_cash_evidence_account_id_4e3f5a14_fk_adc_payment_account_id`：`FOREIGN KEY (account_id) REFERENCES adc_payment_account(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_evidence_cash_entry_id_55e92d71_fk_adc_cash_entry_id`：`FOREIGN KEY (cash_entry_id) REFERENCES adc_cash_entry(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_evidence_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_cash_evidence_pkey`：`PRIMARY KEY (id)`。
- `adc_cash_evidence_prepared_by_id_cbe61383_fk_adc_user_id`：`FOREIGN KEY (prepared_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_evidence_previous_id_250d31ac_fk_adc_cash_evidence_id`：`FOREIGN KEY (previous_id) REFERENCES adc_cash_evidence(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_evidence_previous_id_key`：`UNIQUE (previous_id)`。
- `adc_cash_evidence_reviewed_by_id_3250b8bc_fk_adc_user_id`：`FOREIGN KEY (reviewed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_cash_evidence_version_check`：`CHECK ((version >= 0))`。
- `cash_evidence_positive_version`：`CHECK ((version >= 1))`。
- `cash_evidence_review_metadata`：`CHECK (((((review_reason)::text = ''::text) AND (reviewed_at IS NULL) AND (reviewed_by_id IS NULL) AND ((state)::text = 'PENDING'::text)) OR ((reviewed_at IS NOT NULL) AND (reviewed_by_id IS NOT NULL) AND ((state)::text = ANY ((ARRAY['APPROVED'::character varying, 'REJECTED'::character varying])::text[])) AND (NOT ((review_reason)::text = ''::text)))))`。
- `cash_evidence_separate_review`：`CHECK (((reviewed_by_id IS NULL) OR (NOT ((prepared_by_id = reviewed_by_id) AND (reviewed_by_id IS NOT NULL)))))`。
- `cash_evidence_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['PENDING'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying])::text[])))`。
- `cash_evidence_version_unique`：`UNIQUE (cash_entry_id, version)`。
- `evidence_matches_current`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。

索引（含条件唯一索引）：

- `adc_cash_evidence_account_id_4e3f5a14`：`CREATE INDEX adc_cash_evidence_account_id_4e3f5a14 ON public.adc_cash_evidence USING btree (account_id)`。
- `adc_cash_evidence_cash_entry_id_55e92d71`：`CREATE INDEX adc_cash_evidence_cash_entry_id_55e92d71 ON public.adc_cash_evidence USING btree (cash_entry_id)`。
- `adc_cash_evidence_operation_id_key`：`CREATE UNIQUE INDEX adc_cash_evidence_operation_id_key ON public.adc_cash_evidence USING btree (operation_id)`。
- `adc_cash_evidence_pkey`：`CREATE UNIQUE INDEX adc_cash_evidence_pkey ON public.adc_cash_evidence USING btree (id)`。
- `adc_cash_evidence_prepared_by_id_cbe61383`：`CREATE INDEX adc_cash_evidence_prepared_by_id_cbe61383 ON public.adc_cash_evidence USING btree (prepared_by_id)`。
- `adc_cash_evidence_previous_id_key`：`CREATE UNIQUE INDEX adc_cash_evidence_previous_id_key ON public.adc_cash_evidence USING btree (previous_id)`。
- `adc_cash_evidence_reviewed_by_id_3250b8bc`：`CREATE INDEX adc_cash_evidence_reviewed_by_id_3250b8bc ON public.adc_cash_evidence USING btree (reviewed_by_id)`。
- `cash_evidence_one_pending`：`CREATE UNIQUE INDEX cash_evidence_one_pending ON public.adc_cash_evidence USING btree (cash_entry_id) WHERE ((state)::text = 'PENDING'::text)`。
- `cash_evidence_version_unique`：`CREATE UNIQUE INDEX cash_evidence_version_unique ON public.adc_cash_evidence USING btree (cash_entry_id, version)`。

跨表及历史触发器：

- `cash_evidence_history`：`CREATE TRIGGER cash_evidence_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_cash_evidence FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard()`。
- `evidence_matches_current`：`CREATE CONSTRAINT TRIGGER evidence_matches_current AFTER INSERT OR UPDATE ON public.adc_cash_evidence DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_evidence_commit_guard()`。

## adc_clinic

模型：`registry.Clinic`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_code | character varying(24) | UK | 否 | — |
| name | character varying(120) | — | 否 | — |
| postal_address | character varying(255) | — | 否 | — |
| supervisor_name | character varying(80) | — | 否 | — |
| phone | character varying(32) | — | 否 | — |
| email | character varying(254) | — | 否 | — |
| area_sqm | numeric(10,2) | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_clinic_clinic_code_key`：`UNIQUE (clinic_code)`。
- `adc_clinic_pkey`：`PRIMARY KEY (id)`。
- `clinic_area_positive`：`CHECK ((area_sqm > (0)::numeric))`。

索引（含条件唯一索引）：

- `adc_clinic_clinic_code_0f024ec6_like`：`CREATE INDEX adc_clinic_clinic_code_0f024ec6_like ON public.adc_clinic USING btree (clinic_code varchar_pattern_ops)`。
- `adc_clinic_clinic_code_key`：`CREATE UNIQUE INDEX adc_clinic_clinic_code_key ON public.adc_clinic USING btree (clinic_code)`。
- `adc_clinic_pkey`：`CREATE UNIQUE INDEX adc_clinic_pkey ON public.adc_clinic USING btree (id)`。

跨表及历史触发器：


## adc_coordination_task

模型：`coordination.CoordinationTask`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| slot_id | bigint | FK | 否 | `adc_availability_slot.id` |
| purpose | character varying(12) | — | 否 | — |
| opening_reason | character varying(24) | — | 否 | — |
| creation_operation | uuid | UK | 否 | — |
| state | character varying(12) | — | 否 | — |
| created_by_id | bigint | FK | 否 | `adc_user.id` |
| assignee_id | bigint | FK | 是 | `adc_user.id` |
| due_at | timestamp with time zone | — | 是 | — |
| submitted_by_id | bigint | FK | 是 | `adc_user.id` |
| submitted_at | timestamp with time zone | — | 是 | — |
| submitted_digest | character varying(64) | — | 否 | — |
| closed_by_id | bigint | FK | 是 | `adc_user.id` |
| closed_at | timestamp with time zone | — | 是 | — |
| revision | integer | — | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |
| updated_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_coordination_tas_slot_id_90ab0e4e_fk_adc_avail`：`FOREIGN KEY (slot_id) REFERENCES adc_availability_slot(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_coordination_task_assignee_id_b1e859b2_fk_adc_user_id`：`FOREIGN KEY (assignee_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_coordination_task_closed_by_id_9b574b07_fk_adc_user_id`：`FOREIGN KEY (closed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_coordination_task_created_by_id_78b2c445_fk_adc_user_id`：`FOREIGN KEY (created_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_coordination_task_creation_operation_key`：`UNIQUE (creation_operation)`。
- `adc_coordination_task_pkey`：`PRIMARY KEY (id)`。
- `adc_coordination_task_revision_check`：`CHECK ((revision >= 0))`。
- `adc_coordination_task_submitted_by_id_bc23e4df_fk_adc_user_id`：`FOREIGN KEY (submitted_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `coord_task_close_valid`：`CHECK ((((closed_at IS NOT NULL) AND (closed_by_id IS NOT NULL) AND ((state)::text = ANY ((ARRAY['CLOSED'::character varying, 'CANCELLED'::character varying])::text[]))) OR ((NOT ((state)::text = ANY ((ARRAY['CLOSED'::character varying, 'CANCELLED'::character varying])::text[]))) AND (closed_at IS NULL) AND (closed_by_id IS NULL))))`。
- `coord_task_owner_valid`：`CHECK ((((assignee_id IS NULL) AND ((state)::text = 'OPEN'::text)) OR ((assignee_id IS NOT NULL) AND ((state)::text = ANY ((ARRAY['IN_PROGRESS'::character varying, 'READY'::character varying, 'CLOSED'::character varying])::text[]))) OR ((state)::text = 'CANCELLED'::text)))`。
- `coord_task_purpose_valid`：`CHECK (((purpose)::text = ANY ((ARRAY['DEACTIVATE'::character varying, 'REPLACE'::character varying])::text[])))`。
- `coord_task_reason_valid`：`CHECK (((opening_reason)::text = ANY ((ARRAY['PLAN_CHANGE'::character varying, 'STAFF_UNAVAILABLE'::character varying])::text[])))`。
- `coord_task_separate_review`：`CHECK (((NOT ((state)::text = 'CLOSED'::text)) OR (NOT ((closed_by_id = submitted_by_id) AND (closed_by_id IS NOT NULL) AND (submitted_by_id IS NOT NULL)))))`。
- `coord_task_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['OPEN'::character varying, 'IN_PROGRESS'::character varying, 'READY'::character varying, 'CLOSED'::character varying, 'CANCELLED'::character varying])::text[])))`。
- `coord_task_submit_owner`：`CHECK (((NOT ((state)::text = ANY ((ARRAY['READY'::character varying, 'CLOSED'::character varying])::text[]))) OR (submitted_by_id = assignee_id)))`。
- `coord_task_submit_valid`：`CHECK (((((state)::text = ANY ((ARRAY['READY'::character varying, 'CLOSED'::character varying])::text[])) AND (submitted_at IS NOT NULL) AND (submitted_by_id IS NOT NULL) AND (NOT ((submitted_digest)::text = ''::text))) OR ((NOT ((state)::text = ANY ((ARRAY['READY'::character varying, 'CLOSED'::character varying])::text[]))) AND (submitted_at IS NULL) AND (submitted_by_id IS NULL) AND ((submitted_digest)::text = ''::text))))`。

索引（含条件唯一索引）：

- `adc_coordination_task_assignee_id_b1e859b2`：`CREATE INDEX adc_coordination_task_assignee_id_b1e859b2 ON public.adc_coordination_task USING btree (assignee_id)`。
- `adc_coordination_task_closed_by_id_9b574b07`：`CREATE INDEX adc_coordination_task_closed_by_id_9b574b07 ON public.adc_coordination_task USING btree (closed_by_id)`。
- `adc_coordination_task_created_by_id_78b2c445`：`CREATE INDEX adc_coordination_task_created_by_id_78b2c445 ON public.adc_coordination_task USING btree (created_by_id)`。
- `adc_coordination_task_creation_operation_key`：`CREATE UNIQUE INDEX adc_coordination_task_creation_operation_key ON public.adc_coordination_task USING btree (creation_operation)`。
- `adc_coordination_task_pkey`：`CREATE UNIQUE INDEX adc_coordination_task_pkey ON public.adc_coordination_task USING btree (id)`。
- `adc_coordination_task_slot_id_90ab0e4e`：`CREATE INDEX adc_coordination_task_slot_id_90ab0e4e ON public.adc_coordination_task USING btree (slot_id)`。
- `adc_coordination_task_submitted_by_id_bc23e4df`：`CREATE INDEX adc_coordination_task_submitted_by_id_bc23e4df ON public.adc_coordination_task USING btree (submitted_by_id)`。
- `coord_task_one_active_slot`：`CREATE UNIQUE INDEX coord_task_one_active_slot ON public.adc_coordination_task USING btree (slot_id) WHERE ((state)::text = ANY ((ARRAY['OPEN'::character varying, 'IN_PROGRESS'::character varying, 'READY'::character varying])::text[]))`。
- `coord_task_queue_idx`：`CREATE INDEX coord_task_queue_idx ON public.adc_coordination_task USING btree (state, created_at)`。

跨表及历史触发器：

- `coordination_task_history_guard`：`CREATE TRIGGER coordination_task_history_guard BEFORE DELETE OR UPDATE ON public.adc_coordination_task FOR EACH ROW EXECUTE FUNCTION adc_protect_coord_task()`。

## adc_correction_request

模型：`care.CorrectionRequest`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| visit_id | bigint | FK | 否 | `adc_visit.id` |
| kind | character varying(24) | — | 否 | — |
| base_record_version_id | bigint | FK | 是 | `adc_visit_record_version.id` |
| expected_visit_lock_version | integer | — | 否 | — |
| requester_id | bigint | FK | 否 | `adc_user.id` |
| reviewer_id | bigint | FK | 是 | `adc_user.id` |
| dentist_confirmed_by_id | bigint | FK | 是 | `adc_user.id` |
| status | character varying(12) | — | 否 | — |
| reason | text | — | 否 | — |
| proposed_change | jsonb | — | 否 | — |
| requested_at | timestamp with time zone | — | 否 | — |
| applied_at | timestamp with time zone | — | 是 | — |

数据库约束：

- `adc_correction_reque_base_record_version__78f4237e_fk_adc_visit`：`FOREIGN KEY (base_record_version_id) REFERENCES adc_visit_record_version(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_correction_reque_dentist_confirmed_by_4783661f_fk_adc_user_`：`FOREIGN KEY (dentist_confirmed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_correction_request_expected_visit_lock_version_check`：`CHECK ((expected_visit_lock_version >= 0))`。
- `adc_correction_request_pkey`：`PRIMARY KEY (id)`。
- `adc_correction_request_requester_id_4e899b38_fk_adc_user_id`：`FOREIGN KEY (requester_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_correction_request_reviewer_id_6ab618bf_fk_adc_user_id`：`FOREIGN KEY (reviewer_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_correction_request_visit_id_8b8fcf3e_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `correction_applied_metadata`：`CHECK ((((applied_at IS NOT NULL) AND (reviewer_id IS NOT NULL) AND ((status)::text = 'APPLIED'::text)) OR ((NOT ((status)::text = 'APPLIED'::text)) AND (applied_at IS NULL))))`。
- `correction_base_required`：`CHECK ((((base_record_version_id IS NULL) AND ((kind)::text = 'APPOINTMENT_STATUS'::text)) OR ((base_record_version_id IS NOT NULL) AND ((kind)::text = 'RECORD_CONTENT'::text))))`。
- `correction_kind_valid`：`CHECK (((kind)::text = ANY ((ARRAY['APPOINTMENT_STATUS'::character varying, 'RECORD_CONTENT'::character varying])::text[])))`。
- `correction_no_self_approval`：`CHECK ((NOT ((requester_id = reviewer_id) AND (reviewer_id IS NOT NULL))))`。
- `correction_status_valid`：`CHECK (((status)::text = ANY ((ARRAY['OPEN'::character varying, 'APPLIED'::character varying, 'REJECTED'::character varying, 'WITHDRAWN'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_correction_request_base_record_version_id_78f4237e`：`CREATE INDEX adc_correction_request_base_record_version_id_78f4237e ON public.adc_correction_request USING btree (base_record_version_id)`。
- `adc_correction_request_dentist_confirmed_by_id_4783661f`：`CREATE INDEX adc_correction_request_dentist_confirmed_by_id_4783661f ON public.adc_correction_request USING btree (dentist_confirmed_by_id)`。
- `adc_correction_request_pkey`：`CREATE UNIQUE INDEX adc_correction_request_pkey ON public.adc_correction_request USING btree (id)`。
- `adc_correction_request_requester_id_4e899b38`：`CREATE INDEX adc_correction_request_requester_id_4e899b38 ON public.adc_correction_request USING btree (requester_id)`。
- `adc_correction_request_reviewer_id_6ab618bf`：`CREATE INDEX adc_correction_request_reviewer_id_6ab618bf ON public.adc_correction_request USING btree (reviewer_id)`。
- `adc_correction_request_visit_id_8b8fcf3e`：`CREATE INDEX adc_correction_request_visit_id_8b8fcf3e ON public.adc_correction_request USING btree (visit_id)`。
- `one_open_correction_per_visit`：`CREATE UNIQUE INDEX one_open_correction_per_visit ON public.adc_correction_request USING btree (visit_id) WHERE ((status)::text = 'OPEN'::text)`。

跨表及历史触发器：

- `correction_history_guard`：`CREATE TRIGGER correction_history_guard BEFORE DELETE OR UPDATE ON public.adc_correction_request FOR EACH ROW EXECUTE FUNCTION adc_protect_closed_correction()`。

## adc_daily_close

模型：`finance.DailyClose`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| operation_id | uuid | UK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| business_date | date | — | 否 | — |
| version | integer | — | 否 | — |
| previous_id | bigint | UK / FK | 是 | `adc_daily_close.id` |
| snapshot | jsonb | — | 否 | — |
| declared | jsonb | — | 否 | — |
| evidence | character varying(500) | — | 否 | — |
| reason | character varying(500) | — | 否 | — |
| state | character varying(10) | — | 否 | — |
| lock_version | integer | — | 否 | — |
| prepared_by_id | bigint | FK | 否 | `adc_user.id` |
| prepared_at | timestamp with time zone | — | 否 | — |
| reviewed_by_id | bigint | FK | 是 | `adc_user.id` |
| reviewed_at | timestamp with time zone | — | 是 | — |
| review_reason | character varying(500) | — | 否 | — |

数据库约束：

- `adc_daily_close_clinic_id_e236946f_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_daily_close_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_daily_close_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_daily_close_pkey`：`PRIMARY KEY (id)`。
- `adc_daily_close_prepared_by_id_9f033988_fk_adc_user_id`：`FOREIGN KEY (prepared_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_daily_close_previous_id_8167a489_fk_adc_daily_close_id`：`FOREIGN KEY (previous_id) REFERENCES adc_daily_close(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_daily_close_previous_id_key`：`UNIQUE (previous_id)`。
- `adc_daily_close_reviewed_by_id_65105bf9_fk_adc_user_id`：`FOREIGN KEY (reviewed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_daily_close_version_check`：`CHECK ((version >= 0))`。
- `daily_independent_review`：`CHECK (((reviewed_by_id IS NULL) OR (NOT ((prepared_by_id = reviewed_by_id) AND (reviewed_by_id IS NOT NULL)))))`。
- `daily_positive_version`：`CHECK ((version >= 1))`。
- `daily_review_metadata`：`CHECK ((((lock_version = 0) AND ((review_reason)::text = ''::text) AND (reviewed_at IS NULL) AND (reviewed_by_id IS NULL) AND ((state)::text = 'PENDING'::text)) OR ((lock_version = 1) AND (reviewed_at IS NOT NULL) AND (reviewed_by_id IS NOT NULL) AND ((state)::text = ANY ((ARRAY['APPROVED'::character varying, 'REJECTED'::character varying])::text[])) AND (NOT ((review_reason)::text = ''::text)))))`。
- `daily_version_unique`：`UNIQUE (clinic_id, business_date, version)`。

索引（含条件唯一索引）：

- `adc_daily_close_clinic_id_e236946f`：`CREATE INDEX adc_daily_close_clinic_id_e236946f ON public.adc_daily_close USING btree (clinic_id)`。
- `adc_daily_close_operation_id_key`：`CREATE UNIQUE INDEX adc_daily_close_operation_id_key ON public.adc_daily_close USING btree (operation_id)`。
- `adc_daily_close_pkey`：`CREATE UNIQUE INDEX adc_daily_close_pkey ON public.adc_daily_close USING btree (id)`。
- `adc_daily_close_prepared_by_id_9f033988`：`CREATE INDEX adc_daily_close_prepared_by_id_9f033988 ON public.adc_daily_close USING btree (prepared_by_id)`。
- `adc_daily_close_previous_id_key`：`CREATE UNIQUE INDEX adc_daily_close_previous_id_key ON public.adc_daily_close USING btree (previous_id)`。
- `adc_daily_close_reviewed_by_id_65105bf9`：`CREATE INDEX adc_daily_close_reviewed_by_id_65105bf9 ON public.adc_daily_close USING btree (reviewed_by_id)`。
- `daily_one_pending`：`CREATE UNIQUE INDEX daily_one_pending ON public.adc_daily_close USING btree (clinic_id, business_date) WHERE ((state)::text = 'PENDING'::text)`。
- `daily_queue_idx`：`CREATE INDEX daily_queue_idx ON public.adc_daily_close USING btree (state, business_date)`。
- `daily_version_unique`：`CREATE UNIQUE INDEX daily_version_unique ON public.adc_daily_close USING btree (clinic_id, business_date, version)`。

跨表及历史触发器：

- `daily_close_history`：`CREATE TRIGGER daily_close_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_daily_close FOR EACH ROW EXECUTE FUNCTION adc_daily_close_guard()`。

## adc_dentist

模型：`registry.Dentist`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| employee_no | character varying(24) | UK | 否 | — |
| name | character varying(80) | — | 否 | — |
| date_of_birth | date | — | 否 | — |
| home_address | character varying(255) | — | 否 | — |
| phone | character varying(32) | — | 否 | — |
| email | character varying(254) | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_dentist_employee_no_key`：`UNIQUE (employee_no)`。
- `adc_dentist_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `adc_dentist_employee_no_16716599_like`：`CREATE INDEX adc_dentist_employee_no_16716599_like ON public.adc_dentist USING btree (employee_no varchar_pattern_ops)`。
- `adc_dentist_employee_no_key`：`CREATE UNIQUE INDEX adc_dentist_employee_no_key ON public.adc_dentist USING btree (employee_no)`。
- `adc_dentist_pkey`：`CREATE UNIQUE INDEX adc_dentist_pkey ON public.adc_dentist USING btree (id)`。

跨表及历史触发器：


## adc_dentist_qualification

模型：`registry.DentistQualification`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| dentist_id | bigint | FK | 否 | `adc_dentist.id` |
| qualification_id | bigint | FK | 否 | `adc_qualification.id` |
| notes | text | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_dentist_qualific_qualification_id_805becd7_fk_adc_quali`：`FOREIGN KEY (qualification_id) REFERENCES adc_qualification(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_dentist_qualification_dentist_id_dd3b620d_fk_adc_dentist_id`：`FOREIGN KEY (dentist_id) REFERENCES adc_dentist(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_dentist_qualification_pkey`：`PRIMARY KEY (id)`。
- `dentist_qualification_unique`：`UNIQUE (dentist_id, qualification_id)`。

索引（含条件唯一索引）：

- `adc_dentist_qualification_dentist_id_dd3b620d`：`CREATE INDEX adc_dentist_qualification_dentist_id_dd3b620d ON public.adc_dentist_qualification USING btree (dentist_id)`。
- `adc_dentist_qualification_pkey`：`CREATE UNIQUE INDEX adc_dentist_qualification_pkey ON public.adc_dentist_qualification USING btree (id)`。
- `adc_dentist_qualification_qualification_id_805becd7`：`CREATE INDEX adc_dentist_qualification_qualification_id_805becd7 ON public.adc_dentist_qualification USING btree (qualification_id)`。
- `dentist_qualification_unique`：`CREATE UNIQUE INDEX dentist_qualification_unique ON public.adc_dentist_qualification USING btree (dentist_id, qualification_id)`。

跨表及历史触发器：


## adc_dentist_quarter_cost

模型：`finance.DentistQuarterCost`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| quarter_id | bigint | FK | 否 | `adc_quarter.id` |
| dentist_id | bigint | FK | 否 | `adc_dentist.id` |
| cost_status | character varying(12) | — | 否 | — |
| supply_cost | numeric(16,2) | — | 是 | — |
| operating_expense | numeric(16,2) | — | 是 | — |
| confirmed_by_id | bigint | FK | 是 | `adc_user.id` |
| confirmed_at | timestamp with time zone | — | 是 | — |
| notes | text | — | 否 | — |

数据库约束：

- `adc_dentist_quarter__confirmed_by_id_ccef4ccd_fk_adc_user_`：`FOREIGN KEY (confirmed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_dentist_quarter_cost_dentist_id_88932853_fk_adc_dentist_id`：`FOREIGN KEY (dentist_id) REFERENCES adc_dentist(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_dentist_quarter_cost_pkey`：`PRIMARY KEY (id)`。
- `adc_dentist_quarter_cost_quarter_id_e640de6c_fk_adc_quarter_id`：`FOREIGN KEY (quarter_id) REFERENCES adc_quarter(id) DEFERRABLE INITIALLY DEFERRED`。
- `cost_confirmation_valid`：`CHECK ((((confirmed_at IS NOT NULL) AND (confirmed_by_id IS NOT NULL) AND ((cost_status)::text = 'CONFIRMED'::text) AND (operating_expense IS NOT NULL) AND (supply_cost IS NOT NULL)) OR ((NOT ((cost_status)::text = 'CONFIRMED'::text)) AND (confirmed_at IS NULL) AND (confirmed_by_id IS NULL))))`。
- `cost_nonnegative`：`CHECK ((((supply_cost IS NULL) OR (supply_cost >= (0)::numeric)) AND ((operating_expense IS NULL) OR (operating_expense >= (0)::numeric))))`。
- `cost_status_valid`：`CHECK (((cost_status)::text = ANY ((ARRAY['MISSING'::character varying, 'DRAFT'::character varying, 'CONFIRMED'::character varying])::text[])))`。
- `dentist_quarter_unique`：`UNIQUE (quarter_id, dentist_id)`。
- `missing_cost_is_null`：`CHECK (((NOT ((cost_status)::text = 'MISSING'::text)) OR ((operating_expense IS NULL) AND (supply_cost IS NULL))))`。

索引（含条件唯一索引）：

- `adc_dentist_quarter_cost_confirmed_by_id_ccef4ccd`：`CREATE INDEX adc_dentist_quarter_cost_confirmed_by_id_ccef4ccd ON public.adc_dentist_quarter_cost USING btree (confirmed_by_id)`。
- `adc_dentist_quarter_cost_dentist_id_88932853`：`CREATE INDEX adc_dentist_quarter_cost_dentist_id_88932853 ON public.adc_dentist_quarter_cost USING btree (dentist_id)`。
- `adc_dentist_quarter_cost_pkey`：`CREATE UNIQUE INDEX adc_dentist_quarter_cost_pkey ON public.adc_dentist_quarter_cost USING btree (id)`。
- `adc_dentist_quarter_cost_quarter_id_e640de6c`：`CREATE INDEX adc_dentist_quarter_cost_quarter_id_e640de6c ON public.adc_dentist_quarter_cost USING btree (quarter_id)`。
- `dentist_quarter_unique`：`CREATE UNIQUE INDEX dentist_quarter_unique ON public.adc_dentist_quarter_cost USING btree (quarter_id, dentist_id)`。

跨表及历史触发器：


## adc_department

模型：`scheduling.Department`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| code | character varying(40) | — | 否 | — |
| name | character varying(100) | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_department_clinic_id_3dacec5d_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_department_pkey`：`PRIMARY KEY (id)`。
- `department_clinic_code`：`UNIQUE (clinic_id, code)`。

索引（含条件唯一索引）：

- `adc_department_clinic_id_3dacec5d`：`CREATE INDEX adc_department_clinic_id_3dacec5d ON public.adc_department USING btree (clinic_id)`。
- `adc_department_pkey`：`CREATE UNIQUE INDEX adc_department_pkey ON public.adc_department USING btree (id)`。
- `department_clinic_code`：`CREATE UNIQUE INDEX department_clinic_code ON public.adc_department USING btree (clinic_id, code)`。

跨表及历史触发器：


## adc_department_hours

模型：`scheduling.DepartmentHours`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| department_id | bigint | FK | 否 | `adc_department.id` |
| weekday | smallint | — | 否 | — |
| opens_at | time without time zone | — | 否 | — |
| closes_at | time without time zone | — | 否 | — |

数据库约束：

- `adc_department_hours_department_id_661a9154_fk_adc_depar`：`FOREIGN KEY (department_id) REFERENCES adc_department(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_department_hours_pkey`：`PRIMARY KEY (id)`。
- `adc_department_hours_weekday_check`：`CHECK ((weekday >= 0))`。
- `department_hours_valid`：`CHECK (((closes_at > opens_at) AND (weekday <= 6)))`。

索引（含条件唯一索引）：

- `adc_department_hours_department_id_661a9154`：`CREATE INDEX adc_department_hours_department_id_661a9154 ON public.adc_department_hours USING btree (department_id)`。
- `adc_department_hours_pkey`：`CREATE UNIQUE INDEX adc_department_hours_pkey ON public.adc_department_hours USING btree (id)`。

跨表及历史触发器：


## adc_equipment_asset

模型：`equipment.EquipmentAsset`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| asset_code | character varying(40) | — | 否 | — |
| name | character varying(120) | — | 否 | — |
| category | character varying(16) | — | 否 | — |
| location | character varying(120) | — | 否 | — |
| acquired_on | date | — | 否 | — |
| acquisition_cost | numeric(16,2) | — | 是 | — |
| next_service_due | date | — | 是 | — |
| state | character varying(16) | — | 否 | — |
| lock_version | integer | — | 否 | — |
| registered_by_id | bigint | FK | 否 | `adc_user.id` |
| registered_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_equipment_asset_clinic_id_b7a09438_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_equipment_asset_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_equipment_asset_pkey`：`PRIMARY KEY (id)`。
- `adc_equipment_asset_registered_by_id_94b16682_fk_adc_user_id`：`FOREIGN KEY (registered_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `equipment_category_valid`：`CHECK (((category)::text = ANY ((ARRAY['CHAIR'::character varying, 'IMAGING'::character varying, 'STERILIZER'::character varying, 'OTHER'::character varying])::text[])))`。
- `equipment_code_unique`：`UNIQUE (asset_code)`。
- `equipment_cost_nonnegative`：`CHECK (((acquisition_cost IS NULL) OR (acquisition_cost >= (0)::numeric)))`。
- `equipment_final_consistency`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。
- `equipment_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['IN_SERVICE'::character varying, 'MAINTENANCE'::character varying, 'RETIRED'::character varying])::text[])))`。
- `maintenance_asset_consistency`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。

索引（含条件唯一索引）：

- `adc_equipment_asset_clinic_id_b7a09438`：`CREATE INDEX adc_equipment_asset_clinic_id_b7a09438 ON public.adc_equipment_asset USING btree (clinic_id)`。
- `adc_equipment_asset_pkey`：`CREATE UNIQUE INDEX adc_equipment_asset_pkey ON public.adc_equipment_asset USING btree (id)`。
- `adc_equipment_asset_registered_by_id_94b16682`：`CREATE INDEX adc_equipment_asset_registered_by_id_94b16682 ON public.adc_equipment_asset USING btree (registered_by_id)`。
- `equipment_code_unique`：`CREATE UNIQUE INDEX equipment_code_unique ON public.adc_equipment_asset USING btree (asset_code)`。

跨表及历史触发器：

- `equipment_asset_history`：`CREATE TRIGGER equipment_asset_history BEFORE DELETE OR UPDATE ON public.adc_equipment_asset FOR EACH ROW EXECUTE FUNCTION adc_equipment_asset_guard()`。
- `equipment_final_consistency`：`CREATE CONSTRAINT TRIGGER equipment_final_consistency AFTER INSERT OR UPDATE ON public.adc_equipment_asset DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_equipment_final_guard()`。
- `maintenance_asset_consistency`：`CREATE CONSTRAINT TRIGGER maintenance_asset_consistency AFTER INSERT OR UPDATE ON public.adc_equipment_asset DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_maintenance_final_guard()`。

## adc_equipment_cost_amendment

模型：`equipment.EquipmentCostAmendment`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| event_id | bigint | FK | 否 | `adc_equipment_event.id` |
| operation_id | uuid | UK | 否 | — |
| based_amendment_id | bigint | FK | 是 | `adc_equipment_cost_amendment.id` |
| previous_cost | numeric(16,2) | — | 是 | — |
| proposed_cost | numeric(16,2) | — | 否 | — |
| reason | character varying(500) | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| lock_version | integer | — | 否 | — |
| prepared_by_id | bigint | FK | 否 | `adc_user.id` |
| prepared_at | timestamp with time zone | — | 否 | — |
| reviewed_by_id | bigint | FK | 是 | `adc_user.id` |
| reviewed_at | timestamp with time zone | — | 是 | — |
| review_reason | character varying(500) | — | 否 | — |

数据库约束：

- `adc_equipment_cost_a_based_amendment_id_1058b1a6_fk_adc_equip`：`FOREIGN KEY (based_amendment_id) REFERENCES adc_equipment_cost_amendment(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_equipment_cost_a_event_id_ae5c468c_fk_adc_equip`：`FOREIGN KEY (event_id) REFERENCES adc_equipment_event(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_equipment_cost_a_prepared_by_id_ad609aa8_fk_adc_user_`：`FOREIGN KEY (prepared_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_equipment_cost_a_reviewed_by_id_a0069238_fk_adc_user_`：`FOREIGN KEY (reviewed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_equipment_cost_amendment_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_equipment_cost_amendment_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_equipment_cost_amendment_pkey`：`PRIMARY KEY (id)`。
- `equip_cost_no_self_review`：`CHECK ((NOT ((prepared_by_id = reviewed_by_id) AND (reviewed_by_id IS NOT NULL))))`。
- `equip_cost_nonnegative`：`CHECK ((proposed_cost >= (0)::numeric))`。
- `equip_cost_review_metadata`：`CHECK ((((lock_version = 0) AND (reviewed_at IS NULL) AND (reviewed_by_id IS NULL) AND ((state)::text = 'PENDING'::text)) OR ((lock_version = 1) AND (reviewed_at IS NOT NULL) AND (reviewed_by_id IS NOT NULL) AND ((state)::text = ANY ((ARRAY['APPROVED'::character varying, 'REJECTED'::character varying])::text[])))))`。
- `equip_cost_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['PENDING'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_equipment_cost_amendment_based_amendment_id_1058b1a6`：`CREATE INDEX adc_equipment_cost_amendment_based_amendment_id_1058b1a6 ON public.adc_equipment_cost_amendment USING btree (based_amendment_id)`。
- `adc_equipment_cost_amendment_event_id_ae5c468c`：`CREATE INDEX adc_equipment_cost_amendment_event_id_ae5c468c ON public.adc_equipment_cost_amendment USING btree (event_id)`。
- `adc_equipment_cost_amendment_operation_id_key`：`CREATE UNIQUE INDEX adc_equipment_cost_amendment_operation_id_key ON public.adc_equipment_cost_amendment USING btree (operation_id)`。
- `adc_equipment_cost_amendment_pkey`：`CREATE UNIQUE INDEX adc_equipment_cost_amendment_pkey ON public.adc_equipment_cost_amendment USING btree (id)`。
- `adc_equipment_cost_amendment_prepared_by_id_ad609aa8`：`CREATE INDEX adc_equipment_cost_amendment_prepared_by_id_ad609aa8 ON public.adc_equipment_cost_amendment USING btree (prepared_by_id)`。
- `adc_equipment_cost_amendment_reviewed_by_id_a0069238`：`CREATE INDEX adc_equipment_cost_amendment_reviewed_by_id_a0069238 ON public.adc_equipment_cost_amendment USING btree (reviewed_by_id)`。
- `equip_cost_event_state_idx`：`CREATE INDEX equip_cost_event_state_idx ON public.adc_equipment_cost_amendment USING btree (event_id, state, id)`。
- `equip_cost_one_pending`：`CREATE UNIQUE INDEX equip_cost_one_pending ON public.adc_equipment_cost_amendment USING btree (event_id) WHERE ((state)::text = 'PENDING'::text)`。

跨表及历史触发器：

- `equipment_cost_history`：`CREATE TRIGGER equipment_cost_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_equipment_cost_amendment FOR EACH ROW EXECUTE FUNCTION adc_equipment_cost_guard()`。

## adc_equipment_event

模型：`equipment.EquipmentEvent`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| asset_id | bigint | FK | 否 | `adc_equipment_asset.id` |
| operation_id | uuid | UK | 否 | — |
| sequence | integer | — | 否 | — |
| kind | character varying(16) | — | 否 | — |
| previous_state | character varying(16) | — | 否 | — |
| next_state | character varying(16) | — | 否 | — |
| performed_on | date | — | 否 | — |
| next_service_due | date | — | 是 | — |
| cost | numeric(16,2) | — | 是 | — |
| note | character varying(500) | — | 否 | — |
| recorded_by_id | bigint | FK | 否 | `adc_user.id` |
| recorded_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_equipment_event_asset_id_ecd6bb05_fk_adc_equipment_asset_id`：`FOREIGN KEY (asset_id) REFERENCES adc_equipment_asset(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_equipment_event_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_equipment_event_pkey`：`PRIMARY KEY (id)`。
- `adc_equipment_event_recorded_by_id_4c2c7ad0_fk_adc_user_id`：`FOREIGN KEY (recorded_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_equipment_event_sequence_check`：`CHECK ((sequence >= 0))`。
- `equipment_event_cost_nonnegative`：`CHECK (((cost IS NULL) OR (cost >= (0)::numeric)))`。
- `equipment_event_kind_valid`：`CHECK (((kind)::text = ANY ((ARRAY['REGISTER'::character varying, 'MAINTENANCE'::character varying, 'SERVICE'::character varying, 'RETIRE'::character varying])::text[])))`。
- `equipment_event_sequence_unique`：`UNIQUE (asset_id, sequence)`。
- `equipment_event_state_valid`：`CHECK (((next_state)::text = ANY ((ARRAY['IN_SERVICE'::character varying, 'MAINTENANCE'::character varying, 'RETIRED'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_equipment_event_asset_id_ecd6bb05`：`CREATE INDEX adc_equipment_event_asset_id_ecd6bb05 ON public.adc_equipment_event USING btree (asset_id)`。
- `adc_equipment_event_operation_id_key`：`CREATE UNIQUE INDEX adc_equipment_event_operation_id_key ON public.adc_equipment_event USING btree (operation_id)`。
- `adc_equipment_event_pkey`：`CREATE UNIQUE INDEX adc_equipment_event_pkey ON public.adc_equipment_event USING btree (id)`。
- `adc_equipment_event_recorded_by_id_4c2c7ad0`：`CREATE INDEX adc_equipment_event_recorded_by_id_4c2c7ad0 ON public.adc_equipment_event USING btree (recorded_by_id)`。
- `equipment_event_sequence_unique`：`CREATE UNIQUE INDEX equipment_event_sequence_unique ON public.adc_equipment_event USING btree (asset_id, sequence)`。

跨表及历史触发器：

- `equipment_event_history`：`CREATE TRIGGER equipment_event_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_equipment_event FOR EACH ROW EXECUTE FUNCTION adc_equipment_event_guard()`。

## adc_inbox_message

模型：`notifications.InboxMessage`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| event_id | bigint | FK | 否 | `adc_notification_outbox.id` |
| recipient_id | bigint | FK | 否 | `adc_user.id` |
| grant_id | bigint | FK | 否 | `adc_role_assignment.id` |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| role | character varying(16) | — | 否 | — |
| delivered_at | timestamp with time zone | — | 否 | — |
| read_at | timestamp with time zone | — | 是 | — |

数据库约束：

- `adc_inbox_message_clinic_id_0cd4c427_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_inbox_message_event_id_d18878b9_fk_adc_notif`：`FOREIGN KEY (event_id) REFERENCES adc_notification_outbox(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_inbox_message_grant_id_d851c1ae_fk_adc_role_assignment_id`：`FOREIGN KEY (grant_id) REFERENCES adc_role_assignment(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_inbox_message_pkey`：`PRIMARY KEY (id)`。
- `adc_inbox_message_recipient_id_062919cc_fk_adc_user_id`：`FOREIGN KEY (recipient_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `inbox_event_grant_unique`：`UNIQUE (event_id, grant_id)`。
- `inbox_read_after_delivery`：`CHECK (((read_at IS NULL) OR (read_at >= delivered_at)))`。
- `inbox_role_valid`：`CHECK (((role)::text = ANY ((ARRAY['FRONT_DESK'::character varying, 'MANAGER'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_inbox_message_clinic_id_0cd4c427`：`CREATE INDEX adc_inbox_message_clinic_id_0cd4c427 ON public.adc_inbox_message USING btree (clinic_id)`。
- `adc_inbox_message_event_id_d18878b9`：`CREATE INDEX adc_inbox_message_event_id_d18878b9 ON public.adc_inbox_message USING btree (event_id)`。
- `adc_inbox_message_grant_id_d851c1ae`：`CREATE INDEX adc_inbox_message_grant_id_d851c1ae ON public.adc_inbox_message USING btree (grant_id)`。
- `adc_inbox_message_pkey`：`CREATE UNIQUE INDEX adc_inbox_message_pkey ON public.adc_inbox_message USING btree (id)`。
- `adc_inbox_message_recipient_id_062919cc`：`CREATE INDEX adc_inbox_message_recipient_id_062919cc ON public.adc_inbox_message USING btree (recipient_id)`。
- `inbox_event_grant_unique`：`CREATE UNIQUE INDEX inbox_event_grant_unique ON public.adc_inbox_message USING btree (event_id, grant_id)`。
- `inbox_scope_idx`：`CREATE INDEX inbox_scope_idx ON public.adc_inbox_message USING btree (recipient_id, clinic_id, role, read_at)`。

跨表及历史触发器：

- `inbox_ownership_guard`：`CREATE TRIGGER inbox_ownership_guard BEFORE INSERT OR DELETE OR UPDATE ON public.adc_inbox_message FOR EACH ROW EXECUTE FUNCTION adc_inbox_ownership()`。

## adc_invoice

模型：`care.Invoice`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| invoice_no | character varying(40) | UK | 否 | — |
| visit_id | bigint | UK / FK | 否 | `adc_visit.id` |
| current_record_version_id | bigint | UK / FK | 否 | `adc_visit_record_version.id` |
| first_issued_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_invoice_current_record_versi_f441c74e_fk_adc_visit`：`FOREIGN KEY (current_record_version_id) REFERENCES adc_visit_record_version(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_invoice_current_record_version_id_key`：`UNIQUE (current_record_version_id)`。
- `adc_invoice_final_consistency`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。
- `adc_invoice_invoice_no_key`：`UNIQUE (invoice_no)`。
- `adc_invoice_pkey`：`PRIMARY KEY (id)`。
- `adc_invoice_visit_id_e82f7f85_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_invoice_visit_id_key`：`UNIQUE (visit_id)`。
- `invoice_correction_approval`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。
- `invoice_same_visit_fk`：`FOREIGN KEY (current_record_version_id, visit_id) REFERENCES adc_visit_record_version(id, visit_id) DEFERRABLE INITIALLY DEFERRED`。

索引（含条件唯一索引）：

- `adc_invoice_current_record_version_id_key`：`CREATE UNIQUE INDEX adc_invoice_current_record_version_id_key ON public.adc_invoice USING btree (current_record_version_id)`。
- `adc_invoice_invoice_no_9355305d_like`：`CREATE INDEX adc_invoice_invoice_no_9355305d_like ON public.adc_invoice USING btree (invoice_no varchar_pattern_ops)`。
- `adc_invoice_invoice_no_key`：`CREATE UNIQUE INDEX adc_invoice_invoice_no_key ON public.adc_invoice USING btree (invoice_no)`。
- `adc_invoice_pkey`：`CREATE UNIQUE INDEX adc_invoice_pkey ON public.adc_invoice USING btree (id)`。
- `adc_invoice_visit_id_key`：`CREATE UNIQUE INDEX adc_invoice_visit_id_key ON public.adc_invoice USING btree (visit_id)`。

跨表及历史触发器：

- `adc_invoice_final_consistency`：`CREATE CONSTRAINT TRIGGER adc_invoice_final_consistency AFTER INSERT OR DELETE OR UPDATE ON public.adc_invoice DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_check_visit_final()`。
- `invoice_correction_approval`：`CREATE CONSTRAINT TRIGGER invoice_correction_approval AFTER INSERT OR UPDATE ON public.adc_invoice DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_validate_correction_publication()`。

## adc_maintenance_action

模型：`equipment.MaintenanceAction`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| order_id | bigint | FK | 否 | `adc_maintenance_order.id` |
| operation_id | uuid | UK | 否 | — |
| sequence | integer | — | 否 | — |
| action | character varying(10) | — | 否 | — |
| actor_id | bigint | FK | 否 | `adc_user.id` |
| note | character varying(500) | — | 否 | — |
| snapshot | jsonb | — | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_maintenance_acti_order_id_01035220_fk_adc_maint`：`FOREIGN KEY (order_id) REFERENCES adc_maintenance_order(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_maintenance_action_actor_id_641ebba0_fk_adc_user_id`：`FOREIGN KEY (actor_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_maintenance_action_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_maintenance_action_pkey`：`PRIMARY KEY (id)`。
- `adc_maintenance_action_sequence_check`：`CHECK ((sequence >= 0))`。
- `maintenance_action_sequence`：`UNIQUE (order_id, sequence)`。
- `maintenance_action_valid`：`CHECK (((action)::text = ANY ((ARRAY['OPEN'::character varying, 'START'::character varying, 'ASSIGN'::character varying, 'SUBMIT'::character varying, 'RETURN'::character varying, 'WITHDRAW'::character varying, 'APPROVE'::character varying, 'CANCEL'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_maintenance_action_actor_id_641ebba0`：`CREATE INDEX adc_maintenance_action_actor_id_641ebba0 ON public.adc_maintenance_action USING btree (actor_id)`。
- `adc_maintenance_action_operation_id_key`：`CREATE UNIQUE INDEX adc_maintenance_action_operation_id_key ON public.adc_maintenance_action USING btree (operation_id)`。
- `adc_maintenance_action_order_id_01035220`：`CREATE INDEX adc_maintenance_action_order_id_01035220 ON public.adc_maintenance_action USING btree (order_id)`。
- `adc_maintenance_action_pkey`：`CREATE UNIQUE INDEX adc_maintenance_action_pkey ON public.adc_maintenance_action USING btree (id)`。
- `maintenance_action_sequence`：`CREATE UNIQUE INDEX maintenance_action_sequence ON public.adc_maintenance_action USING btree (order_id, sequence)`。

跨表及历史触发器：

- `maintenance_action_history`：`CREATE TRIGGER maintenance_action_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_maintenance_action FOR EACH ROW EXECUTE FUNCTION adc_maintenance_action_guard()`。

## adc_maintenance_order

模型：`equipment.MaintenanceOrder`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| asset_id | bigint | FK | 否 | `adc_equipment_asset.id` |
| maintenance_event_id | bigint | FK | 否 | `adc_equipment_event.id` |
| issue | character varying(500) | — | 否 | — |
| created_by_id | bigint | FK | 否 | `adc_user.id` |
| created_at | timestamp with time zone | — | 否 | — |
| assigned_to_id | bigint | FK | 否 | `adc_user.id` |
| due_on | date | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| lock_version | integer | — | 否 | — |
| performed_on | date | — | 是 | — |
| cost | numeric(16,2) | — | 是 | — |
| next_service_due | date | — | 是 | — |
| completion_note | character varying(500) | — | 否 | — |
| schedule_checked | boolean | — | 否 | — |
| submitted_by_id | bigint | FK | 是 | `adc_user.id` |
| submitted_at | timestamp with time zone | — | 是 | — |
| reviewed_by_id | bigint | FK | 是 | `adc_user.id` |
| reviewed_at | timestamp with time zone | — | 是 | — |
| review_reason | character varying(500) | — | 否 | — |
| service_event_id | bigint | UK / FK | 是 | `adc_equipment_event.id` |

数据库约束：

- `adc_maintenance_orde_asset_id_74a576ac_fk_adc_equip`：`FOREIGN KEY (asset_id) REFERENCES adc_equipment_asset(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_maintenance_orde_maintenance_event_id_1167ee28_fk_adc_equip`：`FOREIGN KEY (maintenance_event_id) REFERENCES adc_equipment_event(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_maintenance_orde_service_event_id_37fa4024_fk_adc_equip`：`FOREIGN KEY (service_event_id) REFERENCES adc_equipment_event(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_maintenance_order_assigned_to_id_9ba5934b_fk_adc_user_id`：`FOREIGN KEY (assigned_to_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_maintenance_order_created_by_id_1cd457b4_fk_adc_user_id`：`FOREIGN KEY (created_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_maintenance_order_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_maintenance_order_pkey`：`PRIMARY KEY (id)`。
- `adc_maintenance_order_reviewed_by_id_d081b891_fk_adc_user_id`：`FOREIGN KEY (reviewed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_maintenance_order_service_event_id_key`：`UNIQUE (service_event_id)`。
- `adc_maintenance_order_submitted_by_id_6bbb8e49_fk_adc_user_id`：`FOREIGN KEY (submitted_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `maintenance_cost_valid`：`CHECK (((cost IS NULL) OR (cost >= (0)::numeric)))`。
- `maintenance_final_consistency`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。
- `maintenance_report_metadata`：`CHECK (((((completion_note)::text = ''::text) AND (cost IS NULL) AND (next_service_due IS NULL) AND (performed_on IS NULL) AND ((review_reason)::text = ''::text) AND (reviewed_at IS NULL) AND (reviewed_by_id IS NULL) AND (NOT schedule_checked) AND (service_event_id IS NULL) AND ((state)::text = ANY ((ARRAY['ASSIGNED'::character varying, 'IN_PROGRESS'::character varying, 'CANCELLED'::character varying])::text[])) AND (submitted_at IS NULL) AND (submitted_by_id IS NULL)) OR ((performed_on IS NOT NULL) AND schedule_checked AND ((state)::text = ANY ((ARRAY['READY'::character varying, 'CLOSED'::character varying])::text[])) AND (submitted_at IS NOT NULL) AND (submitted_by_id = assigned_to_id) AND (submitted_by_id IS NOT NULL) AND (NOT ((completion_note)::text = ''::text)) AND ((((review_reason)::text = ''::text) AND (reviewed_at IS NULL) AND (reviewed_by_id IS NULL) AND (service_event_id IS NULL) AND ((state)::text = 'READY'::text)) OR ((reviewed_at IS NOT NULL) AND (reviewed_by_id IS NOT NULL) AND (service_event_id IS NOT NULL) AND ((state)::text = 'CLOSED'::text) AND (NOT ((review_reason)::text = ''::text)))))))`。
- `maintenance_separate_review`：`CHECK (((reviewed_by_id IS NULL) OR ((NOT ((reviewed_by_id = submitted_by_id) AND (reviewed_by_id IS NOT NULL) AND (submitted_by_id IS NOT NULL))) AND (NOT ((reviewed_by_id = assigned_to_id) AND (reviewed_by_id IS NOT NULL))))))`。
- `maintenance_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['ASSIGNED'::character varying, 'IN_PROGRESS'::character varying, 'READY'::character varying, 'CLOSED'::character varying, 'CANCELLED'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_maintenance_order_asset_id_74a576ac`：`CREATE INDEX adc_maintenance_order_asset_id_74a576ac ON public.adc_maintenance_order USING btree (asset_id)`。
- `adc_maintenance_order_assigned_to_id_9ba5934b`：`CREATE INDEX adc_maintenance_order_assigned_to_id_9ba5934b ON public.adc_maintenance_order USING btree (assigned_to_id)`。
- `adc_maintenance_order_created_by_id_1cd457b4`：`CREATE INDEX adc_maintenance_order_created_by_id_1cd457b4 ON public.adc_maintenance_order USING btree (created_by_id)`。
- `adc_maintenance_order_maintenance_event_id_1167ee28`：`CREATE INDEX adc_maintenance_order_maintenance_event_id_1167ee28 ON public.adc_maintenance_order USING btree (maintenance_event_id)`。
- `adc_maintenance_order_pkey`：`CREATE UNIQUE INDEX adc_maintenance_order_pkey ON public.adc_maintenance_order USING btree (id)`。
- `adc_maintenance_order_reviewed_by_id_d081b891`：`CREATE INDEX adc_maintenance_order_reviewed_by_id_d081b891 ON public.adc_maintenance_order USING btree (reviewed_by_id)`。
- `adc_maintenance_order_service_event_id_key`：`CREATE UNIQUE INDEX adc_maintenance_order_service_event_id_key ON public.adc_maintenance_order USING btree (service_event_id)`。
- `adc_maintenance_order_submitted_by_id_6bbb8e49`：`CREATE INDEX adc_maintenance_order_submitted_by_id_6bbb8e49 ON public.adc_maintenance_order USING btree (submitted_by_id)`。
- `maintenance_one_active`：`CREATE UNIQUE INDEX maintenance_one_active ON public.adc_maintenance_order USING btree (asset_id) WHERE ((state)::text = ANY ((ARRAY['ASSIGNED'::character varying, 'IN_PROGRESS'::character varying, 'READY'::character varying])::text[]))`。
- `maintenance_queue_idx`：`CREATE INDEX maintenance_queue_idx ON public.adc_maintenance_order USING btree (state, due_on)`。

跨表及历史触发器：

- `maintenance_final_consistency`：`CREATE CONSTRAINT TRIGGER maintenance_final_consistency AFTER INSERT OR UPDATE ON public.adc_maintenance_order DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_maintenance_final_guard()`。
- `maintenance_order_history`：`CREATE TRIGGER maintenance_order_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_maintenance_order FOR EACH ROW EXECUTE FUNCTION adc_maintenance_order_guard()`。

## adc_notification_outbox

模型：`notifications.NotificationOutbox`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| source_event_id | bigint | UK / FK | 否 | `adc_audit_event.id` |
| task_id | bigint | FK | 否 | `adc_coordination_task.id` |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| task_revision | bigint | — | 否 | — |
| action | character varying(12) | — | 否 | — |
| event_state | character varying(12) | — | 否 | — |
| occurred_at | timestamp with time zone | — | 否 | — |
| recipients | jsonb | — | 否 | — |
| state | character varying(16) | — | 否 | — |
| attempts | smallint | — | 否 | — |
| retry_round | integer | — | 否 | — |
| next_attempt_at | timestamp with time zone | — | 是 | — |
| completed_at | timestamp with time zone | — | 是 | — |
| delivered_count | integer | — | 否 | — |
| suppressed_count | integer | — | 否 | — |
| error_code | character varying(24) | — | 否 | — |

数据库约束：

- `adc_notification_out_source_event_id_3f6ec0b0_fk_adc_audit`：`FOREIGN KEY (source_event_id) REFERENCES adc_audit_event(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_notification_out_task_id_fc8830c7_fk_adc_coord`：`FOREIGN KEY (task_id) REFERENCES adc_coordination_task(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_notification_outbox_attempts_check`：`CHECK ((attempts >= 0))`。
- `adc_notification_outbox_clinic_id_00ce60c6_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_notification_outbox_delivered_count_check`：`CHECK ((delivered_count >= 0))`。
- `adc_notification_outbox_pkey`：`PRIMARY KEY (id)`。
- `adc_notification_outbox_retry_round_check`：`CHECK ((retry_round >= 0))`。
- `adc_notification_outbox_source_event_id_key`：`UNIQUE (source_event_id)`。
- `adc_notification_outbox_suppressed_count_check`：`CHECK ((suppressed_count >= 0))`。
- `adc_notification_outbox_task_revision_check`：`CHECK ((task_revision >= 0))`。
- `notice_attempt_limit`：`CHECK ((attempts <= 5))`。
- `notice_delivery_nonzero`：`CHECK (((NOT ((state)::text = 'DELIVERED'::text)) OR (delivered_count > 0)))`。
- `notice_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['PENDING'::character varying, 'DELIVERED'::character varying, 'NO_RECIPIENTS'::character varying, 'FAILED'::character varying])::text[])))`。
- `notice_timing_valid`：`CHECK ((((completed_at IS NULL) AND (next_attempt_at IS NOT NULL) AND ((state)::text = 'PENDING'::text)) OR ((NOT ((state)::text = 'PENDING'::text)) AND (completed_at IS NOT NULL) AND (next_attempt_at IS NULL))))`。

索引（含条件唯一索引）：

- `adc_notification_outbox_clinic_id_00ce60c6`：`CREATE INDEX adc_notification_outbox_clinic_id_00ce60c6 ON public.adc_notification_outbox USING btree (clinic_id)`。
- `adc_notification_outbox_pkey`：`CREATE UNIQUE INDEX adc_notification_outbox_pkey ON public.adc_notification_outbox USING btree (id)`。
- `adc_notification_outbox_source_event_id_key`：`CREATE UNIQUE INDEX adc_notification_outbox_source_event_id_key ON public.adc_notification_outbox USING btree (source_event_id)`。
- `adc_notification_outbox_task_id_fc8830c7`：`CREATE INDEX adc_notification_outbox_task_id_fc8830c7 ON public.adc_notification_outbox USING btree (task_id)`。
- `notice_due_idx`：`CREATE INDEX notice_due_idx ON public.adc_notification_outbox USING btree (state, next_attempt_at, id)`。

跨表及历史触发器：

- `notice_identity_guard`：`CREATE TRIGGER notice_identity_guard BEFORE DELETE OR UPDATE ON public.adc_notification_outbox FOR EACH ROW EXECUTE FUNCTION adc_notice_immutable()`。

## adc_patient

模型：`patients.Patient`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| patient_no | character varying(40) | UK | 否 | — |
| name | character varying(80) | — | 否 | — |
| date_of_birth | date | — | 否 | — |
| billing_address | character varying(255) | — | 否 | — |
| phone | character varying(32) | — | 否 | — |
| email | character varying(254) | — | 否 | — |
| emergency_name | character varying(80) | — | 否 | — |
| emergency_phone | character varying(32) | — | 否 | — |
| allergy_status | character varying(12) | — | 否 | — |
| allergy_info_version | integer | — | 否 | — |
| created_in_clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_patient_allergy_info_version_check`：`CHECK ((allergy_info_version >= 0))`。
- `adc_patient_created_in_clinic_id_1a42f38a_fk_adc_clinic_id`：`FOREIGN KEY (created_in_clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_patient_patient_no_key`：`UNIQUE (patient_no)`。
- `adc_patient_pkey`：`PRIMARY KEY (id)`。
- `allergy_version_positive`：`CHECK ((allergy_info_version >= 1))`。
- `patient_allergy_status_valid`：`CHECK (((allergy_status)::text = ANY ((ARRAY['UNKNOWN'::character varying, 'NO_KNOWN'::character varying, 'KNOWN'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_patient_created_in_clinic_id_1a42f38a`：`CREATE INDEX adc_patient_created_in_clinic_id_1a42f38a ON public.adc_patient USING btree (created_in_clinic_id)`。
- `adc_patient_patient_no_a79d65f0_like`：`CREATE INDEX adc_patient_patient_no_a79d65f0_like ON public.adc_patient USING btree (patient_no varchar_pattern_ops)`。
- `adc_patient_patient_no_key`：`CREATE UNIQUE INDEX adc_patient_patient_no_key ON public.adc_patient USING btree (patient_no)`。
- `adc_patient_pkey`：`CREATE UNIQUE INDEX adc_patient_pkey ON public.adc_patient USING btree (id)`。
- `patient_phone_idx`：`CREATE INDEX patient_phone_idx ON public.adc_patient USING btree (phone)`。

跨表及历史触发器：


## adc_patient_access

模型：`portal.PatientAccess`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| user_id | bigint | UK / FK | 否 | `adc_user.id` |
| patient_id | bigint | UK / FK | 否 | `adc_patient.id` |
| is_active | boolean | — | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_patient_access_patient_id_d7799900_fk_adc_patient_id`：`FOREIGN KEY (patient_id) REFERENCES adc_patient(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_patient_access_patient_id_key`：`UNIQUE (patient_id)`。
- `adc_patient_access_pkey`：`PRIMARY KEY (id)`。
- `adc_patient_access_user_id_c24b5ae0_fk_adc_user_id`：`FOREIGN KEY (user_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_patient_access_user_id_key`：`UNIQUE (user_id)`。

索引（含条件唯一索引）：

- `adc_patient_access_patient_id_key`：`CREATE UNIQUE INDEX adc_patient_access_patient_id_key ON public.adc_patient_access USING btree (patient_id)`。
- `adc_patient_access_pkey`：`CREATE UNIQUE INDEX adc_patient_access_pkey ON public.adc_patient_access USING btree (id)`。
- `adc_patient_access_user_id_key`：`CREATE UNIQUE INDEX adc_patient_access_user_id_key ON public.adc_patient_access USING btree (user_id)`。

跨表及历史触发器：


## adc_patient_allergy

模型：`patients.PatientAllergy`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| patient_id | bigint | FK | 否 | `adc_patient.id` |
| allergy_id | bigint | FK | 否 | `adc_allergy.id` |
| notes | text | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_patient_allergy_allergy_id_d17f4cfd_fk_adc_allergy_id`：`FOREIGN KEY (allergy_id) REFERENCES adc_allergy(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_patient_allergy_patient_id_597e0d3b_fk_adc_patient_id`：`FOREIGN KEY (patient_id) REFERENCES adc_patient(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_patient_allergy_pkey`：`PRIMARY KEY (id)`。
- `patient_allergy_unique`：`UNIQUE (patient_id, allergy_id)`。

索引（含条件唯一索引）：

- `adc_patient_allergy_allergy_id_d17f4cfd`：`CREATE INDEX adc_patient_allergy_allergy_id_d17f4cfd ON public.adc_patient_allergy USING btree (allergy_id)`。
- `adc_patient_allergy_patient_id_597e0d3b`：`CREATE INDEX adc_patient_allergy_patient_id_597e0d3b ON public.adc_patient_allergy USING btree (patient_id)`。
- `adc_patient_allergy_pkey`：`CREATE UNIQUE INDEX adc_patient_allergy_pkey ON public.adc_patient_allergy USING btree (id)`。
- `patient_allergy_unique`：`CREATE UNIQUE INDEX patient_allergy_unique ON public.adc_patient_allergy USING btree (patient_id, allergy_id)`。

跨表及历史触发器：


## adc_payment_account

模型：`finance.PaymentAccount`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| code | character varying(40) | — | 否 | — |
| method | character varying(16) | — | 否 | — |
| is_active | boolean | — | 否 | — |
| lock_version | integer | — | 否 | — |
| operation_id | uuid | UK | 否 | — |
| last_operation_id | uuid | — | 否 | — |
| created_by_id | bigint | FK | 否 | `adc_user.id` |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_payment_account_clinic_id_89887fe7_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_payment_account_created_by_id_170a44d2_fk_adc_user_id`：`FOREIGN KEY (created_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_payment_account_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_payment_account_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_payment_account_pkey`：`PRIMARY KEY (id)`。
- `payment_account_code_unique`：`UNIQUE (clinic_id, code)`。
- `payment_account_method_valid`：`CHECK (((method)::text = ANY ((ARRAY['CASH'::character varying, 'CARD'::character varying, 'BANK_TRANSFER'::character varying, 'E_WALLET'::character varying, 'OTHER'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_payment_account_clinic_id_89887fe7`：`CREATE INDEX adc_payment_account_clinic_id_89887fe7 ON public.adc_payment_account USING btree (clinic_id)`。
- `adc_payment_account_created_by_id_170a44d2`：`CREATE INDEX adc_payment_account_created_by_id_170a44d2 ON public.adc_payment_account USING btree (created_by_id)`。
- `adc_payment_account_operation_id_key`：`CREATE UNIQUE INDEX adc_payment_account_operation_id_key ON public.adc_payment_account USING btree (operation_id)`。
- `adc_payment_account_pkey`：`CREATE UNIQUE INDEX adc_payment_account_pkey ON public.adc_payment_account USING btree (id)`。
- `payment_account_code_unique`：`CREATE UNIQUE INDEX payment_account_code_unique ON public.adc_payment_account USING btree (clinic_id, code)`。

跨表及历史触发器：

- `payment_account_history`：`CREATE TRIGGER payment_account_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_payment_account FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard()`。

## adc_portal_booking_receipt

模型：`portal.BookingReceipt`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| nonce | uuid | UK | 否 | — |
| access_id | bigint | FK | 否 | `adc_patient_access.id` |
| visit_id | bigint | UK / FK | 否 | `adc_visit.id` |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_portal_booking_r_access_id_db4e47dc_fk_adc_patie`：`FOREIGN KEY (access_id) REFERENCES adc_patient_access(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_portal_booking_receipt_nonce_key`：`UNIQUE (nonce)`。
- `adc_portal_booking_receipt_pkey`：`PRIMARY KEY (id)`。
- `adc_portal_booking_receipt_visit_id_284edf2a_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_portal_booking_receipt_visit_id_key`：`UNIQUE (visit_id)`。

索引（含条件唯一索引）：

- `adc_portal_booking_receipt_access_id_db4e47dc`：`CREATE INDEX adc_portal_booking_receipt_access_id_db4e47dc ON public.adc_portal_booking_receipt USING btree (access_id)`。
- `adc_portal_booking_receipt_nonce_key`：`CREATE UNIQUE INDEX adc_portal_booking_receipt_nonce_key ON public.adc_portal_booking_receipt USING btree (nonce)`。
- `adc_portal_booking_receipt_pkey`：`CREATE UNIQUE INDEX adc_portal_booking_receipt_pkey ON public.adc_portal_booking_receipt USING btree (id)`。
- `adc_portal_booking_receipt_visit_id_key`：`CREATE UNIQUE INDEX adc_portal_booking_receipt_visit_id_key ON public.adc_portal_booking_receipt USING btree (visit_id)`。

跨表及历史触发器：


## adc_qualification

模型：`registry.Qualification`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| code | character varying(24) | UK | 否 | — |
| name | character varying(120) | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_qualification_code_key`：`UNIQUE (code)`。
- `adc_qualification_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `adc_qualification_code_b4282804_like`：`CREATE INDEX adc_qualification_code_b4282804_like ON public.adc_qualification USING btree (code varchar_pattern_ops)`。
- `adc_qualification_code_key`：`CREATE UNIQUE INDEX adc_qualification_code_key ON public.adc_qualification USING btree (code)`。
- `adc_qualification_pkey`：`CREATE UNIQUE INDEX adc_qualification_pkey ON public.adc_qualification USING btree (id)`。

跨表及历史触发器：


## adc_quarter

模型：`finance.Quarter`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| lock_version | integer | — | 否 | — |
| year | smallint | — | 否 | — |
| quarter_no | smallint | — | 否 | — |
| roster_status | character varying(12) | — | 否 | — |
| roster_confirmed_by_id | bigint | FK | 是 | `adc_user.id` |
| roster_confirmed_at | timestamp with time zone | — | 是 | — |

数据库约束：

- `adc_quarter_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_quarter_pkey`：`PRIMARY KEY (id)`。
- `adc_quarter_quarter_no_check`：`CHECK ((quarter_no >= 0))`。
- `adc_quarter_roster_confirmed_by_id_6b58e2a2_fk_adc_user_id`：`FOREIGN KEY (roster_confirmed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_quarter_year_check`：`CHECK ((year >= 0))`。
- `quarter_confirmation_valid`：`CHECK ((((roster_confirmed_at IS NOT NULL) AND (roster_confirmed_by_id IS NOT NULL) AND ((roster_status)::text = 'CONFIRMED'::text)) OR ((roster_confirmed_at IS NULL) AND (roster_confirmed_by_id IS NULL) AND ((roster_status)::text = 'DRAFT'::text))))`。
- `quarter_range_valid`：`CHECK (((quarter_no >= 1) AND (quarter_no <= 4) AND (year >= 1900) AND (year <= 9998)))`。
- `quarter_unique`：`UNIQUE (year, quarter_no)`。

索引（含条件唯一索引）：

- `adc_quarter_pkey`：`CREATE UNIQUE INDEX adc_quarter_pkey ON public.adc_quarter USING btree (id)`。
- `adc_quarter_roster_confirmed_by_id_6b58e2a2`：`CREATE INDEX adc_quarter_roster_confirmed_by_id_6b58e2a2 ON public.adc_quarter USING btree (roster_confirmed_by_id)`。
- `quarter_unique`：`CREATE UNIQUE INDEX quarter_unique ON public.adc_quarter USING btree (year, quarter_no)`。

跨表及历史触发器：


## adc_reception_case

模型：`reception.ReceptionCase`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| caller_name | character varying(80) | — | 否 | — |
| relationship | character varying(80) | — | 否 | — |
| contact | character varying(120) | — | 否 | — |
| patient_hint | character varying(80) | — | 否 | — |
| patient_id | bigint | FK | 是 | `adc_patient.id` |
| service_id | bigint | FK | 是 | `adc_booking_service.id` |
| preferred_dentist_id | bigint | FK | 是 | `adc_dentist.id` |
| preferred_day | date | — | 是 | — |
| state | character varying(12) | — | 否 | — |
| owner_id | bigint | FK | 否 | `adc_user.id` |
| due_at | timestamp with time zone | — | 是 | — |
| reason_code | character varying(20) | — | 否 | — |
| wait_request_id | bigint | UK / FK | 是 | `adc_wait_request.id` |
| visit_id | bigint | UK / FK | 是 | `adc_visit.id` |
| revision | integer | — | 否 | — |
| created_by_id | bigint | FK | 否 | `adc_user.id` |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_reception_case_clinic_id_e09a4e35_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_case_created_by_id_0c6ed5d1_fk_adc_user_id`：`FOREIGN KEY (created_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_case_owner_id_1bc81785_fk_adc_user_id`：`FOREIGN KEY (owner_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_case_patient_id_e7e68ea1_fk_adc_patient_id`：`FOREIGN KEY (patient_id) REFERENCES adc_patient(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_case_pkey`：`PRIMARY KEY (id)`。
- `adc_reception_case_preferred_dentist_id_8875e7c0_fk_adc_denti`：`FOREIGN KEY (preferred_dentist_id) REFERENCES adc_dentist(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_case_revision_check`：`CHECK ((revision >= 0))`。
- `adc_reception_case_service_id_f58c7dde_fk_adc_booki`：`FOREIGN KEY (service_id) REFERENCES adc_booking_service(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_case_visit_id_b4ba0acc_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_case_visit_id_key`：`UNIQUE (visit_id)`。
- `adc_reception_case_wait_request_id_b8845c5d_fk_adc_wait_`：`FOREIGN KEY (wait_request_id) REFERENCES adc_wait_request(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_case_wait_request_id_key`：`UNIQUE (wait_request_id)`。
- `reception_booking_fact`：`CHECK ((((patient_id IS NOT NULL) AND ((state)::text = 'BOOKED'::text) AND (visit_id IS NOT NULL)) OR ((NOT ((state)::text = 'BOOKED'::text)) AND (visit_id IS NULL))))`。
- `reception_contact_due`：`CHECK (((NOT ((state)::text = ANY ((ARRAY['CONTACT'::character varying, 'CONFIRM'::character varying, 'WAITLIST'::character varying])::text[]))) OR (due_at IS NOT NULL)))`。
- `reception_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['VERIFY'::character varying, 'CONTACT'::character varying, 'CONFIRM'::character varying, 'WAITLIST'::character varying, 'BOOKED'::character varying, 'UNBOOKED'::character varying, 'WITHDRAWN'::character varying])::text[])))`。
- `reception_unbooked_reason`：`CHECK (((NOT ((state)::text = 'UNBOOKED'::text)) OR (NOT ((reason_code)::text = ''::text))))`。

索引（含条件唯一索引）：

- `adc_reception_case_clinic_id_e09a4e35`：`CREATE INDEX adc_reception_case_clinic_id_e09a4e35 ON public.adc_reception_case USING btree (clinic_id)`。
- `adc_reception_case_created_by_id_0c6ed5d1`：`CREATE INDEX adc_reception_case_created_by_id_0c6ed5d1 ON public.adc_reception_case USING btree (created_by_id)`。
- `adc_reception_case_owner_id_1bc81785`：`CREATE INDEX adc_reception_case_owner_id_1bc81785 ON public.adc_reception_case USING btree (owner_id)`。
- `adc_reception_case_patient_id_e7e68ea1`：`CREATE INDEX adc_reception_case_patient_id_e7e68ea1 ON public.adc_reception_case USING btree (patient_id)`。
- `adc_reception_case_pkey`：`CREATE UNIQUE INDEX adc_reception_case_pkey ON public.adc_reception_case USING btree (id)`。
- `adc_reception_case_preferred_dentist_id_8875e7c0`：`CREATE INDEX adc_reception_case_preferred_dentist_id_8875e7c0 ON public.adc_reception_case USING btree (preferred_dentist_id)`。
- `adc_reception_case_service_id_f58c7dde`：`CREATE INDEX adc_reception_case_service_id_f58c7dde ON public.adc_reception_case USING btree (service_id)`。
- `adc_reception_case_visit_id_key`：`CREATE UNIQUE INDEX adc_reception_case_visit_id_key ON public.adc_reception_case USING btree (visit_id)`。
- `adc_reception_case_wait_request_id_key`：`CREATE UNIQUE INDEX adc_reception_case_wait_request_id_key ON public.adc_reception_case USING btree (wait_request_id)`。
- `reception_worklist`：`CREATE INDEX reception_worklist ON public.adc_reception_case USING btree (clinic_id, state, due_at)`。

跨表及历史触发器：

- `reception_case_history`：`CREATE TRIGGER reception_case_history BEFORE DELETE OR UPDATE ON public.adc_reception_case FOR EACH ROW EXECUTE FUNCTION adc_reception_case_guard()`。

## adc_reception_communication

模型：`reception.ReceptionCommunication`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| case_id | bigint | FK | 否 | `adc_reception_case.id` |
| sequence | integer | — | 否 | — |
| kind | character varying(24) | — | 否 | — |
| note | character varying(2000) | — | 否 | — |
| actor_id | bigint | FK | 否 | `adc_user.id` |
| snapshot | jsonb | — | 否 | — |
| operation_id | uuid | UK | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_reception_commun_case_id_15356ad0_fk_adc_recep`：`FOREIGN KEY (case_id) REFERENCES adc_reception_case(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_communication_actor_id_20d9fd03_fk_adc_user_id`：`FOREIGN KEY (actor_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reception_communication_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_reception_communication_pkey`：`PRIMARY KEY (id)`。
- `adc_reception_communication_sequence_check`：`CHECK ((sequence >= 0))`。
- `reception_history_sequence`：`UNIQUE (case_id, sequence)`。

索引（含条件唯一索引）：

- `adc_reception_communication_actor_id_20d9fd03`：`CREATE INDEX adc_reception_communication_actor_id_20d9fd03 ON public.adc_reception_communication USING btree (actor_id)`。
- `adc_reception_communication_case_id_15356ad0`：`CREATE INDEX adc_reception_communication_case_id_15356ad0 ON public.adc_reception_communication USING btree (case_id)`。
- `adc_reception_communication_operation_id_key`：`CREATE UNIQUE INDEX adc_reception_communication_operation_id_key ON public.adc_reception_communication USING btree (operation_id)`。
- `adc_reception_communication_pkey`：`CREATE UNIQUE INDEX adc_reception_communication_pkey ON public.adc_reception_communication USING btree (id)`。
- `reception_history_sequence`：`CREATE UNIQUE INDEX reception_history_sequence ON public.adc_reception_communication USING btree (case_id, sequence)`。

跨表及历史触发器：

- `reception_communication_history`：`CREATE TRIGGER reception_communication_history BEFORE DELETE OR UPDATE ON public.adc_reception_communication FOR EACH ROW EXECUTE FUNCTION adc_reception_history_guard()`。

## adc_reconciliation_match

模型：`finance.ReconciliationMatch`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| cash_entry_id | bigint | FK | 否 | `adc_cash_entry.id` |
| evidence_id | bigint | FK | 否 | `adc_cash_evidence.id` |
| line_id | bigint | FK | 否 | `adc_statement_line.id` |
| state | character varying(12) | — | 否 | — |
| operation_id | uuid | UK | 否 | — |
| prepared_by_id | bigint | FK | 否 | `adc_user.id` |
| prepared_at | timestamp with time zone | — | 否 | — |
| reviewed_by_id | bigint | FK | 是 | `adc_user.id` |
| reviewed_at | timestamp with time zone | — | 是 | — |
| review_reason | character varying(500) | — | 否 | — |
| invalidated_by_id | bigint | FK | 是 | `adc_user.id` |
| invalidated_at | timestamp with time zone | — | 是 | — |

数据库约束：

- `adc_reconciliation_m_cash_entry_id_e7712714_fk_adc_cash_`：`FOREIGN KEY (cash_entry_id) REFERENCES adc_cash_entry(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reconciliation_m_evidence_id_0b34e1f3_fk_adc_cash_`：`FOREIGN KEY (evidence_id) REFERENCES adc_cash_evidence(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reconciliation_m_invalidated_by_id_9f9c0838_fk_adc_user_`：`FOREIGN KEY (invalidated_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reconciliation_m_line_id_1c015f29_fk_adc_state`：`FOREIGN KEY (line_id) REFERENCES adc_statement_line(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reconciliation_match_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_reconciliation_match_pkey`：`PRIMARY KEY (id)`。
- `adc_reconciliation_match_prepared_by_id_58e9060f_fk_adc_user_id`：`FOREIGN KEY (prepared_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_reconciliation_match_reviewed_by_id_897e9161_fk_adc_user_id`：`FOREIGN KEY (reviewed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `reconciliation_review_metadata`：`CHECK ((((invalidated_at IS NULL) AND (invalidated_by_id IS NULL) AND ((review_reason)::text = ''::text) AND (reviewed_at IS NULL) AND (reviewed_by_id IS NULL) AND ((state)::text = 'PENDING'::text)) OR ((invalidated_at IS NULL) AND (invalidated_by_id IS NULL) AND (reviewed_at IS NOT NULL) AND (reviewed_by_id IS NOT NULL) AND ((state)::text = ANY ((ARRAY['CONFIRMED'::character varying, 'REJECTED'::character varying])::text[])) AND (NOT ((review_reason)::text = ''::text))) OR ((invalidated_at IS NOT NULL) AND (invalidated_by_id IS NOT NULL) AND ((state)::text = 'STALE'::text))))`。
- `reconciliation_separate_review`：`CHECK (((reviewed_by_id IS NULL) OR (NOT ((prepared_by_id = reviewed_by_id) AND (reviewed_by_id IS NOT NULL)))))`。
- `reconciliation_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['PENDING'::character varying, 'CONFIRMED'::character varying, 'REJECTED'::character varying, 'STALE'::character varying])::text[])))`。

索引（含条件唯一索引）：

- `adc_reconciliation_match_cash_entry_id_e7712714`：`CREATE INDEX adc_reconciliation_match_cash_entry_id_e7712714 ON public.adc_reconciliation_match USING btree (cash_entry_id)`。
- `adc_reconciliation_match_evidence_id_0b34e1f3`：`CREATE INDEX adc_reconciliation_match_evidence_id_0b34e1f3 ON public.adc_reconciliation_match USING btree (evidence_id)`。
- `adc_reconciliation_match_invalidated_by_id_9f9c0838`：`CREATE INDEX adc_reconciliation_match_invalidated_by_id_9f9c0838 ON public.adc_reconciliation_match USING btree (invalidated_by_id)`。
- `adc_reconciliation_match_line_id_1c015f29`：`CREATE INDEX adc_reconciliation_match_line_id_1c015f29 ON public.adc_reconciliation_match USING btree (line_id)`。
- `adc_reconciliation_match_operation_id_key`：`CREATE UNIQUE INDEX adc_reconciliation_match_operation_id_key ON public.adc_reconciliation_match USING btree (operation_id)`。
- `adc_reconciliation_match_pkey`：`CREATE UNIQUE INDEX adc_reconciliation_match_pkey ON public.adc_reconciliation_match USING btree (id)`。
- `adc_reconciliation_match_prepared_by_id_58e9060f`：`CREATE INDEX adc_reconciliation_match_prepared_by_id_58e9060f ON public.adc_reconciliation_match USING btree (prepared_by_id)`。
- `adc_reconciliation_match_reviewed_by_id_897e9161`：`CREATE INDEX adc_reconciliation_match_reviewed_by_id_897e9161 ON public.adc_reconciliation_match USING btree (reviewed_by_id)`。
- `reconciliation_cash_active`：`CREATE UNIQUE INDEX reconciliation_cash_active ON public.adc_reconciliation_match USING btree (cash_entry_id) WHERE ((state)::text = ANY ((ARRAY['PENDING'::character varying, 'CONFIRMED'::character varying])::text[]))`。
- `reconciliation_line_active`：`CREATE UNIQUE INDEX reconciliation_line_active ON public.adc_reconciliation_match USING btree (line_id) WHERE ((state)::text = ANY ((ARRAY['PENDING'::character varying, 'CONFIRMED'::character varying])::text[]))`。

跨表及历史触发器：

- `reconciliation_history`：`CREATE TRIGGER reconciliation_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_reconciliation_match FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard()`。

## adc_resource_action

模型：`scheduling.ResourceAction`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| operation_id | uuid | UK | 否 | — |
| actor_id | bigint | FK | 否 | `adc_user.id` |
| kind | character varying(40) | — | 否 | — |
| result | jsonb | — | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_resource_action_actor_id_4236a5c5_fk_adc_user_id`：`FOREIGN KEY (actor_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_action_clinic_id_3063f327_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_action_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_resource_action_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `adc_resource_action_actor_id_4236a5c5`：`CREATE INDEX adc_resource_action_actor_id_4236a5c5 ON public.adc_resource_action USING btree (actor_id)`。
- `adc_resource_action_clinic_id_3063f327`：`CREATE INDEX adc_resource_action_clinic_id_3063f327 ON public.adc_resource_action USING btree (clinic_id)`。
- `adc_resource_action_operation_id_key`：`CREATE UNIQUE INDEX adc_resource_action_operation_id_key ON public.adc_resource_action USING btree (operation_id)`。
- `adc_resource_action_pkey`：`CREATE UNIQUE INDEX adc_resource_action_pkey ON public.adc_resource_action USING btree (id)`。

跨表及历史触发器：

- `resource_action_history`：`CREATE TRIGGER resource_action_history BEFORE DELETE OR UPDATE ON public.adc_resource_action FOR EACH ROW EXECUTE FUNCTION adc_resource_action_guard()`。

## adc_resource_binding

模型：`scheduling.ResourceBinding`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| asset_id | bigint | UK / FK | 否 | `adc_equipment_asset.id` |
| room_id | bigint | FK | 是 | `adc_treatment_room.id` |
| shared | boolean | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_resource_binding_asset_id_c8a477f6_fk_adc_equip`：`FOREIGN KEY (asset_id) REFERENCES adc_equipment_asset(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_binding_asset_id_key`：`UNIQUE (asset_id)`。
- `adc_resource_binding_pkey`：`PRIMARY KEY (id)`。
- `adc_resource_binding_room_id_bb0065c6_fk_adc_treatment_room_id`：`FOREIGN KEY (room_id) REFERENCES adc_treatment_room(id) DEFERRABLE INITIALLY DEFERRED`。
- `binding_location_valid`：`CHECK ((((room_id IS NULL) AND shared) OR ((room_id IS NOT NULL) AND (NOT shared))))`。

索引（含条件唯一索引）：

- `adc_resource_binding_asset_id_key`：`CREATE UNIQUE INDEX adc_resource_binding_asset_id_key ON public.adc_resource_binding USING btree (asset_id)`。
- `adc_resource_binding_pkey`：`CREATE UNIQUE INDEX adc_resource_binding_pkey ON public.adc_resource_binding USING btree (id)`。
- `adc_resource_binding_room_id_bb0065c6`：`CREATE INDEX adc_resource_binding_room_id_bb0065c6 ON public.adc_resource_binding USING btree (room_id)`。

跨表及历史触发器：

- `binding_business_relation`：`CREATE TRIGGER binding_business_relation BEFORE INSERT OR UPDATE ON public.adc_resource_binding FOR EACH ROW EXECUTE FUNCTION adc_scheduling_relation_guard()`。

## adc_resource_block

模型：`scheduling.ResourceBlock`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| department_id | bigint | FK | 是 | `adc_department.id` |
| room_id | bigint | FK | 是 | `adc_treatment_room.id` |
| asset_id | bigint | FK | 是 | `adc_equipment_asset.id` |
| starts_at | timestamp with time zone | — | 否 | — |
| ends_at | timestamp with time zone | — | 否 | — |
| reason | character varying(500) | — | 否 | — |
| is_active | boolean | — | 否 | — |
| recorded_by_id | bigint | FK | 否 | `adc_user.id` |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_resource_block_asset_id_e3a78bf2_fk_adc_equipment_asset_id`：`FOREIGN KEY (asset_id) REFERENCES adc_equipment_asset(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_block_clinic_id_eb5dd77d_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_block_department_id_17dcbf65_fk_adc_department_id`：`FOREIGN KEY (department_id) REFERENCES adc_department(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_block_pkey`：`PRIMARY KEY (id)`。
- `adc_resource_block_recorded_by_id_c801afa1_fk_adc_user_id`：`FOREIGN KEY (recorded_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_block_room_id_ee7b4a78_fk_adc_treatment_room_id`：`FOREIGN KEY (room_id) REFERENCES adc_treatment_room(id) DEFERRABLE INITIALLY DEFERRED`。
- `resource_block_one_target`：`CHECK ((((asset_id IS NULL) AND (department_id IS NOT NULL) AND (room_id IS NULL)) OR ((asset_id IS NULL) AND (department_id IS NULL) AND (room_id IS NOT NULL)) OR ((asset_id IS NOT NULL) AND (department_id IS NULL) AND (room_id IS NULL))))`。
- `resource_block_time_order`：`CHECK ((ends_at > starts_at))`。

索引（含条件唯一索引）：

- `adc_resource_block_asset_id_e3a78bf2`：`CREATE INDEX adc_resource_block_asset_id_e3a78bf2 ON public.adc_resource_block USING btree (asset_id)`。
- `adc_resource_block_clinic_id_eb5dd77d`：`CREATE INDEX adc_resource_block_clinic_id_eb5dd77d ON public.adc_resource_block USING btree (clinic_id)`。
- `adc_resource_block_department_id_17dcbf65`：`CREATE INDEX adc_resource_block_department_id_17dcbf65 ON public.adc_resource_block USING btree (department_id)`。
- `adc_resource_block_pkey`：`CREATE UNIQUE INDEX adc_resource_block_pkey ON public.adc_resource_block USING btree (id)`。
- `adc_resource_block_recorded_by_id_c801afa1`：`CREATE INDEX adc_resource_block_recorded_by_id_c801afa1 ON public.adc_resource_block USING btree (recorded_by_id)`。
- `adc_resource_block_room_id_ee7b4a78`：`CREATE INDEX adc_resource_block_room_id_ee7b4a78 ON public.adc_resource_block USING btree (room_id)`。

跨表及历史触发器：

- `block_business_relation`：`CREATE TRIGGER block_business_relation BEFORE INSERT OR UPDATE ON public.adc_resource_block FOR EACH ROW EXECUTE FUNCTION adc_scheduling_relation_guard()`。

## adc_resource_claim

模型：`scheduling.ResourceClaim`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| plan_id | bigint | FK | 否 | `adc_resource_plan.id` |
| asset_id | bigint | FK | 否 | `adc_equipment_asset.id` |
| starts_at | timestamp with time zone | — | 否 | — |
| ends_at | timestamp with time zone | — | 否 | — |
| kind | character varying(8) | — | 否 | — |
| expires_at | timestamp with time zone | — | 是 | — |
| active | boolean | — | 否 | — |
| released_at | timestamp with time zone | — | 是 | — |
| release_reason | character varying(40) | — | 否 | — |

数据库约束：

- `adc_resource_claim_asset_id_06d93d4c_fk_adc_equipment_asset_id`：`FOREIGN KEY (asset_id) REFERENCES adc_equipment_asset(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_claim_pkey`：`PRIMARY KEY (id)`。
- `adc_resource_claim_plan_id_7cf339be_fk_adc_resource_plan_id`：`FOREIGN KEY (plan_id) REFERENCES adc_resource_plan(id) DEFERRABLE INITIALLY DEFERRED`。
- `physical_resource_no_overlap`：`EXCLUDE USING gist (asset_id WITH =, tstzrange(starts_at, ends_at, '[)'::text) WITH &&) WHERE (active)`。
- `resource_claim_time_order`：`CHECK ((ends_at > starts_at))`。
- `resource_plan_asset_unique`：`UNIQUE (plan_id, asset_id)`。

索引（含条件唯一索引）：

- `adc_resource_claim_asset_id_06d93d4c`：`CREATE INDEX adc_resource_claim_asset_id_06d93d4c ON public.adc_resource_claim USING btree (asset_id)`。
- `adc_resource_claim_pkey`：`CREATE UNIQUE INDEX adc_resource_claim_pkey ON public.adc_resource_claim USING btree (id)`。
- `adc_resource_claim_plan_id_7cf339be`：`CREATE INDEX adc_resource_claim_plan_id_7cf339be ON public.adc_resource_claim USING btree (plan_id)`。
- `physical_resource_no_overlap`：`CREATE INDEX physical_resource_no_overlap ON public.adc_resource_claim USING gist (asset_id, tstzrange(starts_at, ends_at, '[)'::text)) WHERE active`。
- `resource_claim_lookup`：`CREATE INDEX resource_claim_lookup ON public.adc_resource_claim USING btree (asset_id, active, starts_at)`。
- `resource_plan_asset_unique`：`CREATE UNIQUE INDEX resource_plan_asset_unique ON public.adc_resource_claim USING btree (plan_id, asset_id)`。

跨表及历史触发器：

- `claim_business_relation`：`CREATE TRIGGER claim_business_relation BEFORE INSERT OR UPDATE ON public.adc_resource_claim FOR EACH ROW EXECUTE FUNCTION adc_scheduling_relation_guard()`。
- `resource_claim_history`：`CREATE TRIGGER resource_claim_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_resource_claim FOR EACH ROW EXECUTE FUNCTION adc_resource_claim_guard()`。

## adc_resource_coordination

模型：`scheduling.ResourceCoordination`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| plan_id | bigint | FK | 否 | `adc_resource_plan.id` |
| asset_id | bigint | FK | 否 | `adc_equipment_asset.id` |
| state | character varying(16) | — | 否 | — |
| owner_id | bigint | FK | 是 | `adc_user.id` |
| due_at | timestamp with time zone | — | 是 | — |
| reason | character varying(500) | — | 否 | — |
| revision | integer | — | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_resource_coordin_asset_id_98f7bcfb_fk_adc_equip`：`FOREIGN KEY (asset_id) REFERENCES adc_equipment_asset(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_coordin_plan_id_e22f1263_fk_adc_resou`：`FOREIGN KEY (plan_id) REFERENCES adc_resource_plan(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_coordination_owner_id_35c6eb42_fk_adc_user_id`：`FOREIGN KEY (owner_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_coordination_pkey`：`PRIMARY KEY (id)`。
- `adc_resource_coordination_revision_check`：`CHECK ((revision >= 0))`。

索引（含条件唯一索引）：

- `adc_resource_coordination_asset_id_98f7bcfb`：`CREATE INDEX adc_resource_coordination_asset_id_98f7bcfb ON public.adc_resource_coordination USING btree (asset_id)`。
- `adc_resource_coordination_owner_id_35c6eb42`：`CREATE INDEX adc_resource_coordination_owner_id_35c6eb42 ON public.adc_resource_coordination USING btree (owner_id)`。
- `adc_resource_coordination_pkey`：`CREATE UNIQUE INDEX adc_resource_coordination_pkey ON public.adc_resource_coordination USING btree (id)`。
- `adc_resource_coordination_plan_id_e22f1263`：`CREATE INDEX adc_resource_coordination_plan_id_e22f1263 ON public.adc_resource_coordination USING btree (plan_id)`。
- `one_open_resource_issue`：`CREATE UNIQUE INDEX one_open_resource_issue ON public.adc_resource_coordination USING btree (plan_id, asset_id) WHERE ((state)::text = ANY ((ARRAY['OPEN'::character varying, 'CONTACT'::character varying])::text[]))`。

跨表及历史触发器：


## adc_resource_plan

模型：`scheduling.ResourcePlan`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| visit_id | bigint | FK | 是 | `adc_visit.id` |
| offer_id | bigint | FK | 是 | `adc_wait_offer.id` |
| service_id | bigint | FK | 否 | `adc_booking_service.id` |
| room_id | bigint | FK | 否 | `adc_treatment_room.id` |
| snapshot | jsonb | — | 否 | — |
| version | integer | — | 否 | — |
| is_current | boolean | — | 否 | — |
| reason | character varying(500) | — | 否 | — |
| recorded_by_id | bigint | FK | 否 | `adc_user.id` |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_resource_plan_offer_id_854661e0_fk_adc_wait_offer_id`：`FOREIGN KEY (offer_id) REFERENCES adc_wait_offer(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_plan_pkey`：`PRIMARY KEY (id)`。
- `adc_resource_plan_recorded_by_id_6b27a921_fk_adc_user_id`：`FOREIGN KEY (recorded_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_plan_room_id_aef8a919_fk_adc_treatment_room_id`：`FOREIGN KEY (room_id) REFERENCES adc_treatment_room(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_plan_service_id_ca57362a_fk_adc_booking_service_id`：`FOREIGN KEY (service_id) REFERENCES adc_booking_service(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_plan_version_check`：`CHECK ((version >= 0))`。
- `adc_resource_plan_visit_id_6ba019ea_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `resource_plan_source`：`CHECK (((visit_id IS NOT NULL) OR (offer_id IS NOT NULL)))`。

索引（含条件唯一索引）：

- `adc_resource_plan_offer_id_854661e0`：`CREATE INDEX adc_resource_plan_offer_id_854661e0 ON public.adc_resource_plan USING btree (offer_id)`。
- `adc_resource_plan_pkey`：`CREATE UNIQUE INDEX adc_resource_plan_pkey ON public.adc_resource_plan USING btree (id)`。
- `adc_resource_plan_recorded_by_id_6b27a921`：`CREATE INDEX adc_resource_plan_recorded_by_id_6b27a921 ON public.adc_resource_plan USING btree (recorded_by_id)`。
- `adc_resource_plan_room_id_aef8a919`：`CREATE INDEX adc_resource_plan_room_id_aef8a919 ON public.adc_resource_plan USING btree (room_id)`。
- `adc_resource_plan_service_id_ca57362a`：`CREATE INDEX adc_resource_plan_service_id_ca57362a ON public.adc_resource_plan USING btree (service_id)`。
- `adc_resource_plan_visit_id_6ba019ea`：`CREATE INDEX adc_resource_plan_visit_id_6ba019ea ON public.adc_resource_plan USING btree (visit_id)`。
- `offer_current_resource_plan`：`CREATE UNIQUE INDEX offer_current_resource_plan ON public.adc_resource_plan USING btree (offer_id) WHERE (is_current AND (offer_id IS NOT NULL))`。
- `visit_current_resource_plan`：`CREATE UNIQUE INDEX visit_current_resource_plan ON public.adc_resource_plan USING btree (visit_id) WHERE (is_current AND (visit_id IS NOT NULL))`。

跨表及历史触发器：

- `plan_business_relation`：`CREATE TRIGGER plan_business_relation BEFORE INSERT OR UPDATE ON public.adc_resource_plan FOR EACH ROW EXECUTE FUNCTION adc_scheduling_relation_guard()`。
- `resource_plan_history`：`CREATE TRIGGER resource_plan_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_resource_plan FOR EACH ROW EXECUTE FUNCTION adc_resource_plan_guard()`。

## adc_resource_policy

模型：`scheduling.ResourcePolicy`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_id | bigint | UK / FK | 否 | `adc_clinic.id` |
| state | character varying(12) | — | 否 | — |
| revision | integer | — | 否 | — |
| activated_at | timestamp with time zone | — | 是 | — |

数据库约束：

- `adc_resource_policy_clinic_id_39eede4c_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_resource_policy_clinic_id_key`：`UNIQUE (clinic_id)`。
- `adc_resource_policy_pkey`：`PRIMARY KEY (id)`。
- `adc_resource_policy_revision_check`：`CHECK ((revision >= 0))`。

索引（含条件唯一索引）：

- `adc_resource_policy_clinic_id_key`：`CREATE UNIQUE INDEX adc_resource_policy_clinic_id_key ON public.adc_resource_policy USING btree (clinic_id)`。
- `adc_resource_policy_pkey`：`CREATE UNIQUE INDEX adc_resource_policy_pkey ON public.adc_resource_policy USING btree (id)`。

跨表及历史触发器：


## adc_role_assignment

模型：`accounts.RoleAssignment`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| user_id | bigint | FK | 否 | `adc_user.id` |
| role | character varying(16) | — | 否 | — |
| scope_kind | character varying(16) | — | 否 | — |
| clinic_id | bigint | FK | 是 | `adc_clinic.id` |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_role_assignment_clinic_id_06c108de_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_role_assignment_pkey`：`PRIMARY KEY (id)`。
- `adc_role_assignment_user_id_49685fe0_fk_adc_user_id`：`FOREIGN KEY (user_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `role_scope_valid`：`CHECK ((((clinic_id IS NOT NULL) AND ((role)::text = ANY ((ARRAY['FRONT_DESK'::character varying, 'MANAGER'::character varying])::text[])) AND ((scope_kind)::text = 'CLINIC'::text)) OR ((clinic_id IS NULL) AND ((role)::text = 'DENTIST'::text) AND ((scope_kind)::text = 'SELF_DENTIST'::text)) OR ((clinic_id IS NULL) AND ((role)::text = ANY ((ARRAY['HQ'::character varying, 'FINANCE'::character varying])::text[])) AND ((scope_kind)::text = 'CHAIN'::text)) OR ((clinic_id IS NULL) AND ((role)::text = 'SYSADMIN'::text) AND ((scope_kind)::text = 'TECHNICAL'::text))))`。

索引（含条件唯一索引）：

- `adc_role_assignment_clinic_id_06c108de`：`CREATE INDEX adc_role_assignment_clinic_id_06c108de ON public.adc_role_assignment USING btree (clinic_id)`。
- `adc_role_assignment_pkey`：`CREATE UNIQUE INDEX adc_role_assignment_pkey ON public.adc_role_assignment USING btree (id)`。
- `adc_role_assignment_user_id_49685fe0`：`CREATE INDEX adc_role_assignment_user_id_49685fe0 ON public.adc_role_assignment USING btree (user_id)`。
- `role_clinic_unique`：`CREATE UNIQUE INDEX role_clinic_unique ON public.adc_role_assignment USING btree (user_id, role, scope_kind, clinic_id) WHERE (clinic_id IS NOT NULL)`。
- `role_noclinic_unique`：`CREATE UNIQUE INDEX role_noclinic_unique ON public.adc_role_assignment USING btree (user_id, role, scope_kind) WHERE (clinic_id IS NULL)`。

跨表及历史触发器：


## adc_schedule_plan

模型：`coordination.SchedulePlan`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| created_by_id | bigint | FK | 否 | `adc_user.id` |
| created_at | timestamp with time zone | — | 否 | — |
| suggestions | jsonb | — | 否 | — |
| metadata | jsonb | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| published_at | timestamp with time zone | — | 是 | — |

数据库约束：

- `adc_schedule_plan_clinic_id_edac77fb_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_schedule_plan_created_by_id_c94552ee_fk_adc_user_id`：`FOREIGN KEY (created_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_schedule_plan_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `adc_schedule_plan_clinic_id_edac77fb`：`CREATE INDEX adc_schedule_plan_clinic_id_edac77fb ON public.adc_schedule_plan USING btree (clinic_id)`。
- `adc_schedule_plan_created_by_id_c94552ee`：`CREATE INDEX adc_schedule_plan_created_by_id_c94552ee ON public.adc_schedule_plan USING btree (created_by_id)`。
- `adc_schedule_plan_pkey`：`CREATE UNIQUE INDEX adc_schedule_plan_pkey ON public.adc_schedule_plan USING btree (id)`。

跨表及历史触发器：


## adc_service_requirement

模型：`scheduling.ServiceRequirement`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| service_id | bigint | FK | 否 | `adc_booking_service.id` |
| category | character varying(16) | — | 否 | — |
| quantity | smallint | — | 否 | — |

数据库约束：

- `adc_service_requirem_service_id_8a7429d0_fk_adc_booki`：`FOREIGN KEY (service_id) REFERENCES adc_booking_service(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_service_requirement_pkey`：`PRIMARY KEY (id)`。
- `adc_service_requirement_quantity_check`：`CHECK ((quantity >= 0))`。
- `requirement_quantity_valid`：`CHECK (((quantity >= 1) AND (quantity <= 8)))`。
- `service_category_unique`：`UNIQUE (service_id, category)`。

索引（含条件唯一索引）：

- `adc_service_requirement_pkey`：`CREATE UNIQUE INDEX adc_service_requirement_pkey ON public.adc_service_requirement USING btree (id)`。
- `adc_service_requirement_service_id_8a7429d0`：`CREATE INDEX adc_service_requirement_service_id_8a7429d0 ON public.adc_service_requirement USING btree (service_id)`。
- `service_category_unique`：`CREATE UNIQUE INDEX service_category_unique ON public.adc_service_requirement USING btree (service_id, category)`。

跨表及历史触发器：


## adc_statement_batch

模型：`finance.StatementBatch`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| account_id | bigint | FK | 否 | `adc_payment_account.id` |
| created_by_id | bigint | FK | 否 | `adc_user.id` |
| created_at | timestamp with time zone | — | 否 | — |
| source_bytes | bytea | — | 否 | — |
| digest | character varying(64) | — | 否 | — |
| parser_version | character varying(12) | — | 否 | — |
| normalized_rows | jsonb | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| operation_id | uuid | UK | 是 | — |
| imported_at | timestamp with time zone | — | 是 | — |
| new_count | integer | — | 否 | — |
| skipped_count | integer | — | 否 | — |

数据库约束：

- `adc_statement_batch_account_id_1534d446_fk_adc_payme`：`FOREIGN KEY (account_id) REFERENCES adc_payment_account(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_statement_batch_created_by_id_adcce174_fk_adc_user_id`：`FOREIGN KEY (created_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_statement_batch_new_count_check`：`CHECK ((new_count >= 0))`。
- `adc_statement_batch_operation_id_key`：`UNIQUE (operation_id)`。
- `adc_statement_batch_pkey`：`PRIMARY KEY (id)`。
- `adc_statement_batch_skipped_count_check`：`CHECK ((skipped_count >= 0))`。
- `statement_batch_state_valid`：`CHECK ((((imported_at IS NULL) AND (new_count = 0) AND (operation_id IS NULL) AND (skipped_count = 0) AND ((state)::text = 'DRAFT'::text)) OR ((imported_at IS NOT NULL) AND (operation_id IS NOT NULL) AND ((state)::text = 'IMPORTED'::text))))`。
- `statement_import_complete`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。

索引（含条件唯一索引）：

- `adc_statement_batch_account_id_1534d446`：`CREATE INDEX adc_statement_batch_account_id_1534d446 ON public.adc_statement_batch USING btree (account_id)`。
- `adc_statement_batch_created_by_id_adcce174`：`CREATE INDEX adc_statement_batch_created_by_id_adcce174 ON public.adc_statement_batch USING btree (created_by_id)`。
- `adc_statement_batch_operation_id_key`：`CREATE UNIQUE INDEX adc_statement_batch_operation_id_key ON public.adc_statement_batch USING btree (operation_id)`。
- `adc_statement_batch_pkey`：`CREATE UNIQUE INDEX adc_statement_batch_pkey ON public.adc_statement_batch USING btree (id)`。

跨表及历史触发器：

- `statement_batch_history`：`CREATE TRIGGER statement_batch_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_statement_batch FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard()`。
- `statement_import_complete`：`CREATE CONSTRAINT TRIGGER statement_import_complete AFTER INSERT OR UPDATE ON public.adc_statement_batch DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_evidence_commit_guard()`。

## adc_statement_line

模型：`finance.StatementLine`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| batch_id | bigint | FK | 否 | `adc_statement_batch.id` |
| account_id | bigint | FK | 否 | `adc_payment_account.id` |
| transaction_id | character varying(80) | — | 否 | — |
| booked_on | date | — | 否 | — |
| direction | character varying(3) | — | 否 | — |
| amount | numeric(16,2) | — | 否 | — |
| currency | character varying(3) | — | 否 | — |
| reference | character varying(80) | — | 否 | — |

数据库约束：

- `adc_statement_line_account_id_dc681515_fk_adc_payme`：`FOREIGN KEY (account_id) REFERENCES adc_payment_account(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_statement_line_batch_id_8050226e_fk_adc_statement_batch_id`：`FOREIGN KEY (batch_id) REFERENCES adc_statement_batch(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_statement_line_pkey`：`PRIMARY KEY (id)`。
- `statement_direction_valid`：`CHECK (((direction)::text = ANY ((ARRAY['IN'::character varying, 'OUT'::character varying])::text[])))`。
- `statement_positive_amount`：`CHECK ((amount > (0)::numeric))`。
- `statement_transaction_unique`：`UNIQUE (account_id, transaction_id)`。

索引（含条件唯一索引）：

- `adc_statement_line_account_id_dc681515`：`CREATE INDEX adc_statement_line_account_id_dc681515 ON public.adc_statement_line USING btree (account_id)`。
- `adc_statement_line_batch_id_8050226e`：`CREATE INDEX adc_statement_line_batch_id_8050226e ON public.adc_statement_line USING btree (batch_id)`。
- `adc_statement_line_pkey`：`CREATE UNIQUE INDEX adc_statement_line_pkey ON public.adc_statement_line USING btree (id)`。
- `statement_reference_idx`：`CREATE INDEX statement_reference_idx ON public.adc_statement_line USING btree (account_id, reference)`。
- `statement_transaction_unique`：`CREATE UNIQUE INDEX statement_transaction_unique ON public.adc_statement_line USING btree (account_id, transaction_id)`。

跨表及历史触发器：

- `statement_line_history`：`CREATE TRIGGER statement_line_history BEFORE INSERT OR DELETE OR UPDATE ON public.adc_statement_line FOR EACH ROW EXECUTE FUNCTION adc_financial_evidence_guard()`。

## adc_treatment_record

模型：`care.TreatmentRecord`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| record_version_id | bigint | FK | 否 | `adc_visit_record_version.id` |
| line_no | integer | — | 否 | — |
| treatment_type_id | bigint | FK | 否 | `adc_treatment_type.id` |
| name_snapshot | character varying(120) | — | 否 | — |
| unit_snapshot | character varying(120) | — | 否 | — |
| quantity | numeric(12,3) | — | 否 | — |
| unit_price | numeric(12,2) | — | 否 | — |
| line_amount | numeric(16,2) | — | 否 | — |
| confirmed_by_id | bigint | FK | 是 | `adc_user.id` |
| confirmed_at | timestamp with time zone | — | 是 | — |
| price_reason | character varying(500) | — | 否 | — |

数据库约束：

- `adc_treatment_record_confirmed_by_id_c4e5c557_fk_adc_user_id`：`FOREIGN KEY (confirmed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_treatment_record_final_consistency`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。
- `adc_treatment_record_line_no_check`：`CHECK ((line_no >= 0))`。
- `adc_treatment_record_pkey`：`PRIMARY KEY (id)`。
- `adc_treatment_record_record_version_id_0be3c6b9_fk_adc_visit`：`FOREIGN KEY (record_version_id) REFERENCES adc_visit_record_version(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_treatment_record_treatment_type_id_979e40f2_fk_adc_treat`：`FOREIGN KEY (treatment_type_id) REFERENCES adc_treatment_type(id) DEFERRABLE INITIALLY DEFERRED`。
- `line_amount_exact`：`CHECK ((line_amount = round((quantity * unit_price), 2)))`。
- `line_confirmation_consistent`：`CHECK ((((confirmed_at IS NULL) AND (confirmed_by_id IS NULL)) OR ((confirmed_at IS NOT NULL) AND (confirmed_by_id IS NOT NULL))))`。
- `record_line_unique`：`UNIQUE (record_version_id, line_no)`。
- `record_values_valid`：`CHECK (((line_amount >= (0)::numeric) AND (line_no >= 1) AND (quantity > (0)::numeric) AND (unit_price >= (0)::numeric)))`。
- `zero_price_reason_required`：`CHECK (((unit_price > (0)::numeric) OR (NOT ((price_reason)::text = ''::text))))`。

索引（含条件唯一索引）：

- `adc_treatment_record_confirmed_by_id_c4e5c557`：`CREATE INDEX adc_treatment_record_confirmed_by_id_c4e5c557 ON public.adc_treatment_record USING btree (confirmed_by_id)`。
- `adc_treatment_record_pkey`：`CREATE UNIQUE INDEX adc_treatment_record_pkey ON public.adc_treatment_record USING btree (id)`。
- `adc_treatment_record_record_version_id_0be3c6b9`：`CREATE INDEX adc_treatment_record_record_version_id_0be3c6b9 ON public.adc_treatment_record USING btree (record_version_id)`。
- `adc_treatment_record_treatment_type_id_979e40f2`：`CREATE INDEX adc_treatment_record_treatment_type_id_979e40f2 ON public.adc_treatment_record USING btree (treatment_type_id)`。
- `record_line_unique`：`CREATE UNIQUE INDEX record_line_unique ON public.adc_treatment_record USING btree (record_version_id, line_no)`。

跨表及历史触发器：

- `adc_treatment_record_final_consistency`：`CREATE CONSTRAINT TRIGGER adc_treatment_record_final_consistency AFTER INSERT OR DELETE OR UPDATE ON public.adc_treatment_record DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_check_visit_final()`。
- `published_line_guard`：`CREATE TRIGGER published_line_guard BEFORE INSERT OR DELETE OR UPDATE ON public.adc_treatment_record FOR EACH ROW EXECUTE FUNCTION adc_protect_published_line()`。

## adc_treatment_room

模型：`scheduling.TreatmentRoom`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| department_id | bigint | FK | 否 | `adc_department.id` |
| code | character varying(40) | — | 否 | — |
| name | character varying(100) | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_treatment_room_department_id_ac8fc9cf_fk_adc_department_id`：`FOREIGN KEY (department_id) REFERENCES adc_department(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_treatment_room_pkey`：`PRIMARY KEY (id)`。
- `room_department_code`：`UNIQUE (department_id, code)`。

索引（含条件唯一索引）：

- `adc_treatment_room_department_id_ac8fc9cf`：`CREATE INDEX adc_treatment_room_department_id_ac8fc9cf ON public.adc_treatment_room USING btree (department_id)`。
- `adc_treatment_room_pkey`：`CREATE UNIQUE INDEX adc_treatment_room_pkey ON public.adc_treatment_room USING btree (id)`。
- `room_department_code`：`CREATE UNIQUE INDEX room_department_code ON public.adc_treatment_room USING btree (department_id, code)`。

跨表及历史触发器：


## adc_treatment_type

模型：`registry.TreatmentType`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| code | character varying(24) | UK | 否 | — |
| name | character varying(120) | — | 否 | — |
| unit_definition | character varying(120) | — | 否 | — |
| standard_unit_price | numeric(12,2) | — | 否 | — |
| is_active | boolean | — | 否 | — |

数据库约束：

- `adc_treatment_type_code_key`：`UNIQUE (code)`。
- `adc_treatment_type_pkey`：`PRIMARY KEY (id)`。
- `treatment_price_nonnegative`：`CHECK ((standard_unit_price >= (0)::numeric))`。

索引（含条件唯一索引）：

- `adc_treatment_type_code_11978108_like`：`CREATE INDEX adc_treatment_type_code_11978108_like ON public.adc_treatment_type USING btree (code varchar_pattern_ops)`。
- `adc_treatment_type_code_key`：`CREATE UNIQUE INDEX adc_treatment_type_code_key ON public.adc_treatment_type USING btree (code)`。
- `adc_treatment_type_pkey`：`CREATE UNIQUE INDEX adc_treatment_type_pkey ON public.adc_treatment_type USING btree (id)`。

跨表及历史触发器：


## adc_user

模型：`accounts.UserAccount`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| password | character varying(128) | — | 否 | — |
| last_login | timestamp with time zone | — | 是 | — |
| is_superuser | boolean | — | 否 | — |
| username | character varying(150) | UK | 否 | — |
| first_name | character varying(150) | — | 否 | — |
| last_name | character varying(150) | — | 否 | — |
| email | character varying(254) | — | 否 | — |
| is_staff | boolean | — | 否 | — |
| is_active | boolean | — | 否 | — |
| date_joined | timestamp with time zone | — | 否 | — |
| dentist_id | bigint | UK / FK | 是 | `adc_dentist.id` |

数据库约束：

- `adc_user_dentist_id_41944940_fk_adc_dentist_id`：`FOREIGN KEY (dentist_id) REFERENCES adc_dentist(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_user_dentist_id_key`：`UNIQUE (dentist_id)`。
- `adc_user_pkey`：`PRIMARY KEY (id)`。
- `adc_user_username_key`：`UNIQUE (username)`。

索引（含条件唯一索引）：

- `adc_user_dentist_id_key`：`CREATE UNIQUE INDEX adc_user_dentist_id_key ON public.adc_user USING btree (dentist_id)`。
- `adc_user_pkey`：`CREATE UNIQUE INDEX adc_user_pkey ON public.adc_user USING btree (id)`。
- `adc_user_username_11f8da29_like`：`CREATE INDEX adc_user_username_11f8da29_like ON public.adc_user USING btree (username varchar_pattern_ops)`。
- `adc_user_username_key`：`CREATE UNIQUE INDEX adc_user_username_key ON public.adc_user USING btree (username)`。

跨表及历史触发器：


## adc_user_groups

模型：`accounts.UserAccount_groups`；ORM生成的连接表。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| useraccount_id | bigint | FK | 否 | `adc_user.id` |
| group_id | integer | FK | 否 | `auth_group.id` |

数据库约束：

- `adc_user_groups_group_id_0f3e1d7d_fk_auth_group_id`：`FOREIGN KEY (group_id) REFERENCES auth_group(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_user_groups_pkey`：`PRIMARY KEY (id)`。
- `adc_user_groups_useraccount_id_cdfc6c5e_fk_adc_user_id`：`FOREIGN KEY (useraccount_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_user_groups_useraccount_id_group_id_a85dd0fa_uniq`：`UNIQUE (useraccount_id, group_id)`。

索引（含条件唯一索引）：

- `adc_user_groups_group_id_0f3e1d7d`：`CREATE INDEX adc_user_groups_group_id_0f3e1d7d ON public.adc_user_groups USING btree (group_id)`。
- `adc_user_groups_pkey`：`CREATE UNIQUE INDEX adc_user_groups_pkey ON public.adc_user_groups USING btree (id)`。
- `adc_user_groups_useraccount_id_cdfc6c5e`：`CREATE INDEX adc_user_groups_useraccount_id_cdfc6c5e ON public.adc_user_groups USING btree (useraccount_id)`。
- `adc_user_groups_useraccount_id_group_id_a85dd0fa_uniq`：`CREATE UNIQUE INDEX adc_user_groups_useraccount_id_group_id_a85dd0fa_uniq ON public.adc_user_groups USING btree (useraccount_id, group_id)`。

跨表及历史触发器：


## adc_user_user_permissions

模型：`accounts.UserAccount_user_permissions`；ORM生成的连接表。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| useraccount_id | bigint | FK | 否 | `adc_user.id` |
| permission_id | integer | FK | 否 | `auth_permission.id` |

数据库约束：

- `adc_user_user_permis_permission_id_ce7f8ae8_fk_auth_perm`：`FOREIGN KEY (permission_id) REFERENCES auth_permission(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_user_user_permis_useraccount_id_8d0bb1bb_fk_adc_user_`：`FOREIGN KEY (useraccount_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_user_user_permission_useraccount_id_permissio_60b10b3a_uniq`：`UNIQUE (useraccount_id, permission_id)`。
- `adc_user_user_permissions_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `adc_user_user_permission_useraccount_id_permissio_60b10b3a_uniq`：`CREATE UNIQUE INDEX adc_user_user_permission_useraccount_id_permissio_60b10b3a_uniq ON public.adc_user_user_permissions USING btree (useraccount_id, permission_id)`。
- `adc_user_user_permissions_permission_id_ce7f8ae8`：`CREATE INDEX adc_user_user_permissions_permission_id_ce7f8ae8 ON public.adc_user_user_permissions USING btree (permission_id)`。
- `adc_user_user_permissions_pkey`：`CREATE UNIQUE INDEX adc_user_user_permissions_pkey ON public.adc_user_user_permissions USING btree (id)`。
- `adc_user_user_permissions_useraccount_id_8d0bb1bb`：`CREATE INDEX adc_user_user_permissions_useraccount_id_8d0bb1bb ON public.adc_user_user_permissions USING btree (useraccount_id)`。

跨表及历史触发器：


## adc_visit

模型：`scheduling.Visit`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| visit_no | character varying(40) | UK | 否 | — |
| patient_id | bigint | FK | 否 | `adc_patient.id` |
| dentist_id | bigint | FK | 否 | `adc_dentist.id` |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| availability_slot_id | bigint | FK | 否 | `adc_availability_slot.id` |
| scheduled_start | timestamp with time zone | — | 否 | — |
| scheduled_end | timestamp with time zone | — | 否 | — |
| status | character varying(24) | — | 否 | — |
| attended | boolean | — | 否 | — |
| attended_at | timestamp with time zone | — | 是 | — |
| completed_at | timestamp with time zone | — | 是 | — |
| chief_complaint | text | — | 否 | — |
| special_needs | text | — | 否 | — |
| cancellation_party | character varying(8) | — | 否 | — |
| cancellation_reason | text | — | 否 | — |
| replaces_visit_id | bigint | UK / FK | 是 | `adc_visit.id` |
| lock_version | integer | — | 否 | — |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_visit_availability_slot_id_14162f1f_fk_adc_avail`：`FOREIGN KEY (availability_slot_id) REFERENCES adc_availability_slot(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_clinic_id_7eabd51e_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_dentist_id_65507aa7_fk_adc_dentist_id`：`FOREIGN KEY (dentist_id) REFERENCES adc_dentist(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_final_consistency`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_lock_version_check`：`CHECK ((lock_version >= 0))`。
- `adc_visit_patient_id_55b243d8_fk_adc_patient_id`：`FOREIGN KEY (patient_id) REFERENCES adc_patient(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_pkey`：`PRIMARY KEY (id)`。
- `adc_visit_replaces_visit_id_218b6b6a_fk_adc_visit_id`：`FOREIGN KEY (replaces_visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_replaces_visit_id_key`：`UNIQUE (replaces_visit_id)`。
- `adc_visit_visit_no_key`：`UNIQUE (visit_no)`。
- `visit_attendance_consistent`：`CHECK (((attended AND (attended_at IS NOT NULL) AND ((status)::text = ANY ((ARRAY['CHECKED_IN'::character varying, 'COMPLETED'::character varying, 'CLOSED_NO_TREATMENT'::character varying])::text[]))) OR ((NOT ((status)::text = ANY ((ARRAY['CHECKED_IN'::character varying, 'COMPLETED'::character varying, 'CLOSED_NO_TREATMENT'::character varying])::text[]))) AND (NOT attended) AND (attended_at IS NULL))))`。
- `visit_cancellation_consistent`：`CHECK (((((cancellation_party)::text = ANY ((ARRAY['PATIENT'::character varying, 'CLINIC'::character varying])::text[])) AND ((status)::text = 'CANCELLED'::text) AND (NOT (cancellation_reason = ''::text))) OR ((NOT ((status)::text = 'CANCELLED'::text)) AND ((cancellation_party)::text = ''::text) AND (cancellation_reason = ''::text))))`。
- `visit_completion_consistent`：`CHECK (((((status)::text = ANY ((ARRAY['COMPLETED'::character varying, 'CLOSED_NO_TREATMENT'::character varying])::text[])) AND (completed_at >= attended_at) AND (completed_at IS NOT NULL)) OR ((NOT ((status)::text = ANY ((ARRAY['COMPLETED'::character varying, 'CLOSED_NO_TREATMENT'::character varying])::text[]))) AND (completed_at IS NULL))))`。
- `visit_dentist_no_overlap`：`EXCLUDE USING gist (tstzrange(scheduled_start, scheduled_end, '[)'::text) WITH &&, dentist_id WITH =) WHERE (((status)::text = ANY ((ARRAY['SCHEDULED'::character varying, 'CHECKED_IN'::character varying, 'COMPLETED'::character varying, 'CLOSED_NO_TREATMENT'::character varying])::text[])))`。
- `visit_not_replace_self`：`CHECK ((NOT ((replaces_visit_id = id) AND (replaces_visit_id IS NOT NULL))))`。
- `visit_patient_no_overlap`：`EXCLUDE USING gist (tstzrange(scheduled_start, scheduled_end, '[)'::text) WITH &&, patient_id WITH =) WHERE (((status)::text = ANY ((ARRAY['SCHEDULED'::character varying, 'CHECKED_IN'::character varying, 'COMPLETED'::character varying, 'CLOSED_NO_TREATMENT'::character varying])::text[])))`。
- `visit_status_valid`：`CHECK (((status)::text = ANY ((ARRAY['SCHEDULED'::character varying, 'CHECKED_IN'::character varying, 'COMPLETED'::character varying, 'CLOSED_NO_TREATMENT'::character varying, 'CANCELLED'::character varying, 'NO_SHOW'::character varying, 'RESCHEDULED'::character varying])::text[])))`。
- `visit_time_order`：`CHECK ((scheduled_end > scheduled_start))`。

索引（含条件唯一索引）：

- `adc_visit_availability_slot_id_14162f1f`：`CREATE INDEX adc_visit_availability_slot_id_14162f1f ON public.adc_visit USING btree (availability_slot_id)`。
- `adc_visit_clinic_id_7eabd51e`：`CREATE INDEX adc_visit_clinic_id_7eabd51e ON public.adc_visit USING btree (clinic_id)`。
- `adc_visit_dentist_id_65507aa7`：`CREATE INDEX adc_visit_dentist_id_65507aa7 ON public.adc_visit USING btree (dentist_id)`。
- `adc_visit_patient_id_55b243d8`：`CREATE INDEX adc_visit_patient_id_55b243d8 ON public.adc_visit USING btree (patient_id)`。
- `adc_visit_pkey`：`CREATE UNIQUE INDEX adc_visit_pkey ON public.adc_visit USING btree (id)`。
- `adc_visit_replaces_visit_id_key`：`CREATE UNIQUE INDEX adc_visit_replaces_visit_id_key ON public.adc_visit USING btree (replaces_visit_id)`。
- `adc_visit_visit_no_bb4c80c0_like`：`CREATE INDEX adc_visit_visit_no_bb4c80c0_like ON public.adc_visit USING btree (visit_no varchar_pattern_ops)`。
- `adc_visit_visit_no_key`：`CREATE UNIQUE INDEX adc_visit_visit_no_key ON public.adc_visit USING btree (visit_no)`。
- `visit_clinic_time_idx`：`CREATE INDEX visit_clinic_time_idx ON public.adc_visit USING btree (clinic_id, scheduled_start)`。
- `visit_dentist_completed_idx`：`CREATE INDEX visit_dentist_completed_idx ON public.adc_visit USING btree (dentist_id, completed_at)`。
- `visit_dentist_no_overlap`：`CREATE INDEX visit_dentist_no_overlap ON public.adc_visit USING gist (tstzrange(scheduled_start, scheduled_end, '[)'::text), dentist_id) WHERE ((status)::text = ANY ((ARRAY['SCHEDULED'::character varying, 'CHECKED_IN'::character varying, 'COMPLETED'::character varying, 'CLOSED_NO_TREATMENT'::character varying])::text[]))`。
- `visit_patient_no_overlap`：`CREATE INDEX visit_patient_no_overlap ON public.adc_visit USING gist (tstzrange(scheduled_start, scheduled_end, '[)'::text), patient_id) WHERE ((status)::text = ANY ((ARRAY['SCHEDULED'::character varying, 'CHECKED_IN'::character varying, 'COMPLETED'::character varying, 'CLOSED_NO_TREATMENT'::character varying])::text[]))`。

跨表及历史触发器：

- `adc_visit_final_consistency`：`CREATE CONSTRAINT TRIGGER adc_visit_final_consistency AFTER INSERT OR DELETE OR UPDATE ON public.adc_visit DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_check_visit_final()`。
- `visit_slot_guard`：`CREATE TRIGGER visit_slot_guard BEFORE INSERT OR UPDATE ON public.adc_visit FOR EACH ROW EXECUTE FUNCTION adc_check_visit_slot()`。

## adc_visit_record_version

模型：`care.VisitRecordVersion`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| visit_id | bigint | FK | 否 | `adc_visit.id` |
| revision_no | integer | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| outcome | character varying(16) | — | 否 | — |
| previous_version_id | bigint | FK | 是 | `adc_visit_record_version.id` |
| correction_request_id | bigint | UK / FK | 是 | `adc_correction_request.id` |
| prepared_by_id | bigint | FK | 否 | `adc_user.id` |
| reviewed_by_id | bigint | FK | 是 | `adc_user.id` |
| created_at | timestamp with time zone | — | 否 | — |
| published_at | timestamp with time zone | — | 是 | — |
| allergy_review_snapshot | jsonb | — | 否 | — |
| billing_header_snapshot | jsonb | — | 否 | — |
| clinical_note | text | — | 否 | — |
| no_treatment_reason | text | — | 否 | — |
| total_amount | numeric(16,2) | — | 否 | — |
| currency | character varying(3) | — | 否 | — |

数据库约束：

- `adc_visit_record_ver_correction_request_i_ab2debb8_fk_adc_corre`：`FOREIGN KEY (correction_request_id) REFERENCES adc_correction_request(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_record_ver_previous_version_id_93f3b17a_fk_adc_visit`：`FOREIGN KEY (previous_version_id) REFERENCES adc_visit_record_version(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_record_version_correction_request_id_key`：`UNIQUE (correction_request_id)`。
- `adc_visit_record_version_final_consistency`：`TRIGGER DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_record_version_pkey`：`PRIMARY KEY (id)`。
- `adc_visit_record_version_prepared_by_id_5f3aa35b_fk_adc_user_id`：`FOREIGN KEY (prepared_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_record_version_reviewed_by_id_1d37d554_fk_adc_user_id`：`FOREIGN KEY (reviewed_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_record_version_revision_no_check`：`CHECK ((revision_no >= 0))`。
- `adc_visit_record_version_visit_id_04dceb5e_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `revision_positive`：`CHECK ((revision_no >= 1))`。
- `snapshots_are_objects`：`CHECK (((jsonb_typeof(allergy_review_snapshot) = 'object'::text) AND (jsonb_typeof(billing_header_snapshot) = 'object'::text)))`。
- `version_id_visit_unique`：`UNIQUE (id, visit_id)`。
- `version_money_valid`：`CHECK ((((currency)::text = 'CNY'::text) AND (total_amount >= (0)::numeric)))`。
- `version_not_previous_self`：`CHECK ((NOT ((previous_version_id = id) AND (previous_version_id IS NOT NULL))))`。
- `version_outcome_valid`：`CHECK (((outcome)::text = ANY ((ARRAY['TREATED'::character varying, 'NO_TREATMENT'::character varying])::text[])))`。
- `version_publish_metadata`：`CHECK ((((published_at IS NOT NULL) AND ((state)::text = 'PUBLISHED'::text)) OR ((NOT ((state)::text = 'PUBLISHED'::text)) AND (published_at IS NULL))))`。
- `version_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['DRAFT'::character varying, 'PUBLISHED'::character varying, 'ABANDONED'::character varying])::text[])))`。
- `visit_revision_unique`：`UNIQUE (visit_id, revision_no)`。

索引（含条件唯一索引）：

- `adc_visit_record_version_correction_request_id_key`：`CREATE UNIQUE INDEX adc_visit_record_version_correction_request_id_key ON public.adc_visit_record_version USING btree (correction_request_id)`。
- `adc_visit_record_version_pkey`：`CREATE UNIQUE INDEX adc_visit_record_version_pkey ON public.adc_visit_record_version USING btree (id)`。
- `adc_visit_record_version_prepared_by_id_5f3aa35b`：`CREATE INDEX adc_visit_record_version_prepared_by_id_5f3aa35b ON public.adc_visit_record_version USING btree (prepared_by_id)`。
- `adc_visit_record_version_previous_version_id_93f3b17a`：`CREATE INDEX adc_visit_record_version_previous_version_id_93f3b17a ON public.adc_visit_record_version USING btree (previous_version_id)`。
- `adc_visit_record_version_reviewed_by_id_1d37d554`：`CREATE INDEX adc_visit_record_version_reviewed_by_id_1d37d554 ON public.adc_visit_record_version USING btree (reviewed_by_id)`。
- `adc_visit_record_version_visit_id_04dceb5e`：`CREATE INDEX adc_visit_record_version_visit_id_04dceb5e ON public.adc_visit_record_version USING btree (visit_id)`。
- `one_draft_per_visit`：`CREATE UNIQUE INDEX one_draft_per_visit ON public.adc_visit_record_version USING btree (visit_id) WHERE ((state)::text = 'DRAFT'::text)`。
- `version_id_visit_unique`：`CREATE UNIQUE INDEX version_id_visit_unique ON public.adc_visit_record_version USING btree (id, visit_id)`。
- `visit_revision_unique`：`CREATE UNIQUE INDEX visit_revision_unique ON public.adc_visit_record_version USING btree (visit_id, revision_no)`。

跨表及历史触发器：

- `adc_visit_record_version_final_consistency`：`CREATE CONSTRAINT TRIGGER adc_visit_record_version_final_consistency AFTER INSERT OR DELETE OR UPDATE ON public.adc_visit_record_version DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_check_visit_final()`。
- `published_version_guard`：`CREATE TRIGGER published_version_guard BEFORE DELETE OR UPDATE ON public.adc_visit_record_version FOR EACH ROW EXECUTE FUNCTION adc_protect_published_version()`。

## adc_visit_request

模型：`scheduling.VisitRequest`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| visit_id | bigint | FK | 否 | `adc_visit.id` |
| description | character varying(500) | — | 否 | — |
| treatment_type_id | bigint | FK | 是 | `adc_treatment_type.id` |

数据库约束：

- `adc_visit_request_pkey`：`PRIMARY KEY (id)`。
- `adc_visit_request_treatment_type_id_a9447146_fk_adc_treat`：`FOREIGN KEY (treatment_type_id) REFERENCES adc_treatment_type(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_visit_request_visit_id_a2459cbd_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。

索引（含条件唯一索引）：

- `adc_visit_request_pkey`：`CREATE UNIQUE INDEX adc_visit_request_pkey ON public.adc_visit_request USING btree (id)`。
- `adc_visit_request_treatment_type_id_a9447146`：`CREATE INDEX adc_visit_request_treatment_type_id_a9447146 ON public.adc_visit_request USING btree (treatment_type_id)`。
- `adc_visit_request_visit_id_a2459cbd`：`CREATE INDEX adc_visit_request_visit_id_a2459cbd ON public.adc_visit_request USING btree (visit_id)`。

跨表及历史触发器：


## adc_wait_offer

模型：`coordination.WaitOffer`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| request_id | bigint | FK | 否 | `adc_wait_request.id` |
| plan_id | bigint | FK | 否 | `adc_schedule_plan.id` |
| slot_id | bigint | FK | 否 | `adc_availability_slot.id` |
| starts_at | timestamp with time zone | — | 否 | — |
| ends_at | timestamp with time zone | — | 否 | — |
| expires_at | timestamp with time zone | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| visit_id | bigint | UK / FK | 是 | `adc_visit.id` |
| created_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_wait_offer_pkey`：`PRIMARY KEY (id)`。
- `adc_wait_offer_plan_id_c61e2016_fk_adc_schedule_plan_id`：`FOREIGN KEY (plan_id) REFERENCES adc_schedule_plan(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_wait_offer_request_id_1d32b897_fk_adc_wait_request_id`：`FOREIGN KEY (request_id) REFERENCES adc_wait_request(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_wait_offer_slot_id_6e416543_fk_adc_availability_slot_id`：`FOREIGN KEY (slot_id) REFERENCES adc_availability_slot(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_wait_offer_visit_id_7bdf85de_fk_adc_visit_id`：`FOREIGN KEY (visit_id) REFERENCES adc_visit(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_wait_offer_visit_id_key`：`UNIQUE (visit_id)`。
- `offer_expires_before_visit`：`CHECK ((expires_at <= starts_at))`。
- `offer_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['PENDING'::character varying, 'ACCEPTED'::character varying, 'DECLINED'::character varying, 'EXPIRED'::character varying, 'REVOKED'::character varying])::text[])))`。
- `offer_time_order`：`CHECK ((ends_at > starts_at))`。
- `offer_visit_state`：`CHECK (((((state)::text = 'ACCEPTED'::text) AND (visit_id IS NOT NULL)) OR ((NOT ((state)::text = 'ACCEPTED'::text)) AND (visit_id IS NULL))))`。

索引（含条件唯一索引）：

- `adc_wait_offer_pkey`：`CREATE UNIQUE INDEX adc_wait_offer_pkey ON public.adc_wait_offer USING btree (id)`。
- `adc_wait_offer_plan_id_c61e2016`：`CREATE INDEX adc_wait_offer_plan_id_c61e2016 ON public.adc_wait_offer USING btree (plan_id)`。
- `adc_wait_offer_request_id_1d32b897`：`CREATE INDEX adc_wait_offer_request_id_1d32b897 ON public.adc_wait_offer USING btree (request_id)`。
- `adc_wait_offer_slot_id_6e416543`：`CREATE INDEX adc_wait_offer_slot_id_6e416543 ON public.adc_wait_offer USING btree (slot_id)`。
- `adc_wait_offer_visit_id_key`：`CREATE UNIQUE INDEX adc_wait_offer_visit_id_key ON public.adc_wait_offer USING btree (visit_id)`。
- `offer_expiry_idx`：`CREATE INDEX offer_expiry_idx ON public.adc_wait_offer USING btree (state, expires_at)`。
- `offer_one_pending_request`：`CREATE UNIQUE INDEX offer_one_pending_request ON public.adc_wait_offer USING btree (request_id) WHERE ((state)::text = 'PENDING'::text)`。
- `offer_slot_state_exp_idx`：`CREATE INDEX offer_slot_state_exp_idx ON public.adc_wait_offer USING btree (slot_id, state, expires_at)`。

跨表及历史触发器：


## adc_wait_request

模型：`coordination.WaitRequest`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| patient_id | bigint | FK | 否 | `adc_patient.id` |
| clinic_id | bigint | FK | 否 | `adc_clinic.id` |
| service_id | bigint | FK | 是 | `adc_booking_service.id` |
| preferred_dentist_id | bigint | FK | 是 | `adc_dentist.id` |
| earliest | timestamp with time zone | — | 否 | — |
| latest | timestamp with time zone | — | 否 | — |
| state | character varying(12) | — | 否 | — |
| created_by_id | bigint | FK | 否 | `adc_user.id` |
| created_at | timestamp with time zone | — | 否 | — |
| revision | integer | — | 否 | — |

数据库约束：

- `adc_wait_request_clinic_id_6daac263_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_wait_request_created_by_id_40f07fce_fk_adc_user_id`：`FOREIGN KEY (created_by_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_wait_request_patient_id_a5cbe983_fk_adc_patient_id`：`FOREIGN KEY (patient_id) REFERENCES adc_patient(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_wait_request_pkey`：`PRIMARY KEY (id)`。
- `adc_wait_request_preferred_dentist_id_bc68cadd_fk_adc_denti`：`FOREIGN KEY (preferred_dentist_id) REFERENCES adc_dentist(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_wait_request_revision_check`：`CHECK ((revision >= 0))`。
- `adc_wait_request_service_id_4da6945a_fk_adc_booking_service_id`：`FOREIGN KEY (service_id) REFERENCES adc_booking_service(id) DEFERRABLE INITIALLY DEFERRED`。
- `wait_state_valid`：`CHECK (((state)::text = ANY ((ARRAY['WAITING'::character varying, 'OFFERED'::character varying, 'BOOKED'::character varying, 'WITHDRAWN'::character varying])::text[])))`。
- `wait_time_order`：`CHECK ((latest > earliest))`。

索引（含条件唯一索引）：

- `adc_wait_request_clinic_id_6daac263`：`CREATE INDEX adc_wait_request_clinic_id_6daac263 ON public.adc_wait_request USING btree (clinic_id)`。
- `adc_wait_request_created_by_id_40f07fce`：`CREATE INDEX adc_wait_request_created_by_id_40f07fce ON public.adc_wait_request USING btree (created_by_id)`。
- `adc_wait_request_patient_id_a5cbe983`：`CREATE INDEX adc_wait_request_patient_id_a5cbe983 ON public.adc_wait_request USING btree (patient_id)`。
- `adc_wait_request_pkey`：`CREATE UNIQUE INDEX adc_wait_request_pkey ON public.adc_wait_request USING btree (id)`。
- `adc_wait_request_preferred_dentist_id_bc68cadd`：`CREATE INDEX adc_wait_request_preferred_dentist_id_bc68cadd ON public.adc_wait_request USING btree (preferred_dentist_id)`。
- `adc_wait_request_service_id_4da6945a`：`CREATE INDEX adc_wait_request_service_id_4da6945a ON public.adc_wait_request USING btree (service_id)`。
- `wait_one_open_patient`：`CREATE UNIQUE INDEX wait_one_open_patient ON public.adc_wait_request USING btree (patient_id) WHERE ((state)::text = ANY ((ARRAY['WAITING'::character varying, 'OFFERED'::character varying])::text[]))`。

跨表及历史触发器：


## adc_workspace_context

模型：`workspaces.WorkspaceContext`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | uuid | PK | 否 | — |
| user_id | bigint | FK | 否 | `adc_user.id` |
| role | character varying(16) | — | 否 | — |
| clinic_id | bigint | FK | 是 | `adc_clinic.id` |
| revision | integer | — | 否 | — |
| updated_at | timestamp with time zone | — | 否 | — |

数据库约束：

- `adc_workspace_context_clinic_id_0ce9581c_fk_adc_clinic_id`：`FOREIGN KEY (clinic_id) REFERENCES adc_clinic(id) DEFERRABLE INITIALLY DEFERRED`。
- `adc_workspace_context_pkey`：`PRIMARY KEY (id)`。
- `adc_workspace_context_revision_check`：`CHECK ((revision >= 0))`。
- `adc_workspace_context_user_id_88d56c99_fk_adc_user_id`：`FOREIGN KEY (user_id) REFERENCES adc_user(id) DEFERRABLE INITIALLY DEFERRED`。
- `workspace_clinic_role`：`CHECK (((clinic_id IS NULL) OR ((role)::text = ANY ((ARRAY['MANAGER'::character varying, 'FRONT_DESK'::character varying])::text[]))))`。

索引（含条件唯一索引）：

- `adc_workspace_context_clinic_id_0ce9581c`：`CREATE INDEX adc_workspace_context_clinic_id_0ce9581c ON public.adc_workspace_context USING btree (clinic_id)`。
- `adc_workspace_context_pkey`：`CREATE UNIQUE INDEX adc_workspace_context_pkey ON public.adc_workspace_context USING btree (id)`。
- `adc_workspace_context_user_id_88d56c99`：`CREATE INDEX adc_workspace_context_user_id_88d56c99 ON public.adc_workspace_context USING btree (user_id)`。

跨表及历史触发器：


## auth_group

模型：`auth.Group`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | integer | PK | 否 | — |
| name | character varying(150) | UK | 否 | — |

数据库约束：

- `auth_group_name_key`：`UNIQUE (name)`。
- `auth_group_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `auth_group_name_a6ea08ec_like`：`CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops)`。
- `auth_group_name_key`：`CREATE UNIQUE INDEX auth_group_name_key ON public.auth_group USING btree (name)`。
- `auth_group_pkey`：`CREATE UNIQUE INDEX auth_group_pkey ON public.auth_group USING btree (id)`。

跨表及历史触发器：


## auth_group_permissions

模型：`auth.Group_permissions`；ORM生成的连接表。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | bigint | PK | 否 | — |
| group_id | integer | FK | 否 | `auth_group.id` |
| permission_id | integer | FK | 否 | `auth_permission.id` |

兼容性记录：`id`的模型类型为`integer`，实际数据库类型为`bigint`。本目录按实际类型记录；未执行缩窄字段或改写历史。

数据库约束：

- `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm`：`FOREIGN KEY (permission_id) REFERENCES auth_permission(id) DEFERRABLE INITIALLY DEFERRED`。
- `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id`：`FOREIGN KEY (group_id) REFERENCES auth_group(id) DEFERRABLE INITIALLY DEFERRED`。
- `auth_group_permissions_group_id_permission_id_0cd325b0_uniq`：`UNIQUE (group_id, permission_id)`。
- `auth_group_permissions_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `auth_group_permissions_group_id_b120cbf9`：`CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id)`。
- `auth_group_permissions_group_id_permission_id_0cd325b0_uniq`：`CREATE UNIQUE INDEX auth_group_permissions_group_id_permission_id_0cd325b0_uniq ON public.auth_group_permissions USING btree (group_id, permission_id)`。
- `auth_group_permissions_permission_id_84c5c92e`：`CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id)`。
- `auth_group_permissions_pkey`：`CREATE UNIQUE INDEX auth_group_permissions_pkey ON public.auth_group_permissions USING btree (id)`。

跨表及历史触发器：


## auth_permission

模型：`auth.Permission`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | integer | PK | 否 | — |
| name | character varying(255) | — | 否 | — |
| content_type_id | integer | FK | 否 | `django_content_type.id` |
| codename | character varying(100) | — | 否 | — |

数据库约束：

- `auth_permission_content_type_id_2f476e4b_fk_django_co`：`FOREIGN KEY (content_type_id) REFERENCES django_content_type(id) DEFERRABLE INITIALLY DEFERRED`。
- `auth_permission_content_type_id_codename_01ab375a_uniq`：`UNIQUE (content_type_id, codename)`。
- `auth_permission_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `auth_permission_content_type_id_2f476e4b`：`CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id)`。
- `auth_permission_content_type_id_codename_01ab375a_uniq`：`CREATE UNIQUE INDEX auth_permission_content_type_id_codename_01ab375a_uniq ON public.auth_permission USING btree (content_type_id, codename)`。
- `auth_permission_pkey`：`CREATE UNIQUE INDEX auth_permission_pkey ON public.auth_permission USING btree (id)`。

跨表及历史触发器：


## django_content_type

模型：`contenttypes.ContentType`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| id | integer | PK | 否 | — |
| app_label | character varying(100) | — | 否 | — |
| model | character varying(100) | — | 否 | — |

数据库约束：

- `django_content_type_app_label_model_76bd3d3b_uniq`：`UNIQUE (app_label, model)`。
- `django_content_type_pkey`：`PRIMARY KEY (id)`。

索引（含条件唯一索引）：

- `django_content_type_app_label_model_76bd3d3b_uniq`：`CREATE UNIQUE INDEX django_content_type_app_label_model_76bd3d3b_uniq ON public.django_content_type USING btree (app_label, model)`。
- `django_content_type_pkey`：`CREATE UNIQUE INDEX django_content_type_pkey ON public.django_content_type USING btree (id)`。

跨表及历史触发器：


## django_session

模型：`sessions.Session`。

| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |
|---|---|---|---|---|
| session_key | character varying(40) | PK | 否 | — |
| session_data | text | — | 否 | — |
| expire_date | timestamp with time zone | — | 否 | — |

数据库约束：

- `django_session_pkey`：`PRIMARY KEY (session_key)`。

索引（含条件唯一索引）：

- `django_session_expire_date_a5c62663`：`CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date)`。
- `django_session_pkey`：`CREATE UNIQUE INDEX django_session_pkey ON public.django_session USING btree (session_key)`。
- `django_session_session_key_c0390e0f_like`：`CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops)`。

跨表及历史触发器：
