# 病历副本需求与验收追踪

问题 → 岗位 → 可观察规则 → 失败继续 → 验收。

所有函数名位于 `tests/test_record_copies.py`；单项专项执行和准确完整CI分开记录。浏览器、恢复、微信官方工具及实际手机按各自范围留证。

| 用例 | 岗位与不变量 | 主要验收方法 |
|---|---|---|
| SU-141 本人申请 | 只选本人同店已结束就诊和明确类别；缺固定来源仍保留申请；重复确认唯一 | `test_complete_self_application_verification_review_and_authenticated_pickup`；`test_missing_fixed_file_keeps_application_without_fake_approval`；`test_repeat_confirmation_creates_one_application`；真实浏览器 |
| SU-142 材料核验 | 本用途身份、原件引用、领取账号、范围、期限及指定审核人；专项职责默认关闭 | `test_material_duty_and_copy_review_duty_are_default_off`；`test_revoked_material_duty_invalidates_old_verification` |
| SU-143 独立审核 | 原负责医师、申请人、核验人及非医务岗位不能自审；身份变化退回重新核验 | `test_nonmedical_roles_and_original_author_cannot_approve`；`test_identity_change_blocks_approval_but_allows_return_to_material_queue` |
| SU-144 固定副本 | 只投影所选来源；没有员工归档PDF或内部材料；失败明确重试、并发生成唯一 | `test_scope_projection_omits_other_categories_and_material_references`；`test_render_failure_can_retry_original_approved_scope`；`test_concurrent_generation_publishes_one_file`；加密空库恢复 |
| SU-145 受控领取 | 原账号、会话及期限重新核验；持链接不能独立领取；同一传输去重；不改变资金 | `test_native_authenticated_pdf_delivery_and_bearer_link_rejection`；`test_wrong_recipient_cannot_read_or_consume_ticket`；`test_repeated_transport_records_one_response_without_changing_money`；原生传输与Page处理器另列 |
| SU-146 专项代理 | 监护/书面受托逐申请核验；预约、医疗决定或微信身份不能自动变成复制权 | `test_minor_guardian_copy_is_separately_verified`；`test_written_proxy_gets_only_the_separately_verified_copy`；`test_appointment_authority_does_not_allow_self_copy_of_delegated_patient`；`test_copy_only_registered_account_can_pickup_without_patient_chart_access` |
| SU-147 补充及停止领取 | 退回后明确补充；撤销、到期或失效阻止新增领取；旧文件与历史不删 | `test_identity_return_and_explicit_resubmission_preserve_history`；`test_expired_pickup_is_visible_but_history_and_file_remain`；`test_concurrent_revocation_and_pickup_preserve_ordered_result`；自然等待到期案例 |

网站实际375/390/430宽、200%文字及键盘检查与微信原生设备结果分开。WorkBuddy只处理冻结工程部署与新增患者侧回归，不办理员工审核或修改数据库；准确进度见[执行清单](release.json)。本批不宣称新的三十分钟容量结论、实际机构证明或可靠电子签名。
