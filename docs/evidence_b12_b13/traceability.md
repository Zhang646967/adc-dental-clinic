# 问题—岗位—规则—验收追踪

业务问题 → 岗位责任 → 可观察结果 → 正常与异常验收。

下表指向`tests/test_reception_resources.py`内实际执行的测试；完整回归为1,256项真实PostgreSQL／HTTP／并发测试，新增56项。浏览器和独立数据库事实在[执行记录](README.md)分列，测试数量不等于用例覆盖率。

| 场景／问题 | 岗位与关键不变量 | 自动测试及实际场景 |
|---|---|---|
| 1 新患者电话、多次沟通、完整建档与唯一成约 | 前台；咨询不占位、不授临床权限；明确同意；原子关联 | `test_consultation_no_booking_no_clinical_grant`、`test_required_patient_and_explicit_consent`、`test_multicommunication_and_unique_atomic_booking`、`test_full_patient_is_required_without_fabricating_allergies`；五店Chrome各完成治疗结算 |
| 2 老患者无时间，候补后关联原成功结果 | 前台／患者／主管；一个接待关联同一接受预约 | `test_telephone_waitlist_accepts_same_original_visit`、`test_waitlist_15_minute_service`；Chrome临时关闭科室、无建议、恢复、发布及患者接受 |
| 3 多椅并行及共享设备争用 | 排班；同资源无有效重叠 | `test_parallel_chairs_same_room`、`test_shared_device_contention`、`test_postgres_exclusion_enforces_real_asset`、`test_two_front_desks_one_chair_one_winner`、`test_website_and_frontdesk_compete_for_same_chair`；最终数据库重叠数0 |
| 4 服务时长、科室、医师、维修影响候选 | 主管配置、统一排班核验；服务不是收费 | `test_mismatched_duration_rejected`、`test_closed_department_and_blocks`、`test_provider_eligibility`、`test_maintenance_unavailable`、`test_portal_service_duration_and_no_equipment_selection`；Chrome45分钟网站与15分钟候补 |
| 5 资源被抢、重试、断网后核对、旧预览、撤权与跨店 | 各入口当前授权和事务重检；只产生一个结果 | `test_front_preview_replay_and_stale_catalogue`、`test_same_preview_concurrent_retry_single_effect`、`test_revocation_and_clinic_rejection`、`test_seven_roles_new_route_boundaries`；Chrome并发重复同POST、重新读取原结果，七角色与外店访问 |
| 6 预约与送修并发，原约、替换与拒绝改期 | 设备主管／前台；原医师和时间不隐式改变 | `test_booking_races_maintenance_without_losing_original_promise`、`test_maintenance_preserves_promise_and_records_impact`、`test_compatible_replacement_retains_versions`、`test_unanswered_contact_keeps_original_booking`；Chrome患者拒绝时间变化，维修不同账号验收后明确同时间替换 |
| 7 不可用或上一患者未结束 | 前台／医生；阻止重复实际接诊；治疗中不搬迁 | `test_previous_patient_overrun_blocks_checkin`、`test_fault_during_treatment_does_not_move_patient`、`test_new_contact_for_overrun_is_explicit`、`test_premature_resolve_rejected`；Chrome阻止在用椅位及故障设备接诊 |
| 8 预约—治疗—结算 | 负责牙医／前台／独立财务；资源不制造治疗和资金 | `test_booking_and_resources_do_not_invent_financial_facts`；五店各100元实际治疗及不同账号审核收款，独立核算合计500元；容量中原账单和资金不变 |
| 历史、责任、配置和启用 | 主管／前台；追加历史、失效责任重分配、旧承诺逐项核实 | `test_history_plan_and_communication_are_immutable`、`test_reassign_revoked_owner_retains_communication`、`test_configuration_is_preview_first_and_idempotent`、`test_activation_requires_mapping_existing_promises` |
| 可继续办理的错误与手机操作 | 前台／主管；短窗口返回说明，设备选择可识别 | `test_too_short_window_returns_business_feedback_without_creating_wait_request`；最终版本Chrome13项含390px大字号及设备代码／名称 |

重试验收包括并发相同确认、重新查询原结果，以及真实Chrome本地拦截已保存确认的响应后收到连接失败、重试原令牌。对应数据库只保留一条沟通；该实验不代表外部运营商或公网网络测试。不同渠道资源竞争及事务失败保留由真实PostgreSQL独立连接测试覆盖。

联系人与临床文字不进入运行日志或总部汇总；咨询联系方式不自动改写患者档案。合成资料不能证明真实经营效果、全球最优排程、云容量或临床设备认证。
