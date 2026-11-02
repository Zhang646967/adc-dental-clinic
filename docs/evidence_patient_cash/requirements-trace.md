# 患者费用查询需求与验收追踪

| 业务问题 | 岗位及行为 | 不变量及失败处理 | 可执行证据 |
|---|---|---|---|
| 净额不能解释收退款构成 | 本人查看分别记账的收款及退款 | 待审／拒绝不计作资金；不会新增支付 | `test_totals_and_entries_exclude_pending_and_rejected_requests` |
| 医保承担被误当作现金 | 本人同时核对非现金分担与患者责任 | 基金应收不是现金到账，原待处理提示保留 | `test_non_cash_responsibility_remains_visible_and_is_not_counted_as_receipts`，该新增用例是受控保险投影组合，真实保险结算仍有原独立回归 |
| 长清单或遗漏条目 | 本人按稳定顺序翻页 | 每页至多20笔，总额覆盖所有页，不按本页求余额 | `test_pagination_is_bounded_and_totals_cover_all_pages` |
| 逐笔读取导致重复查询 | 两端读取同一投影 | 无逐条补查，总查询量不随条目增多 | `test_number_of_queries_does_not_grow_per_cash_entry` |
| 员工备注或凭据泄露 | 本人仅查看必要费用信息 | 种类／金额／日期／状态白名单，不返回渠道与员工字段 | `test_projection_does_not_disclose_staff_or_channel_evidence` |
| 日期与历史版本混淆 | 本人区分收费版本及当前收退款 | 保留历史收费，总额和明细说明当前口径 | `test_historical_bill_keeps_current_cash_history_and_labels_it`及冻结浏览器／原生处理器接真实HTTP |
| 空记录被理解为免费 | 本人读取未收退款账单 | 显式零总额和空态，应收仍由账单计算 | `test_empty_history_is_explicit_zero_not_missing` |
| 翻页后撤权或跨患者读取 | 原入口每次核对本人权限 | 拒绝返回费用投影，旧内容清除 | `test_revocation_between_pages_removes_cash_projection`、`test_other_patient_cannot_obtain_paginated_cash_history`；原预约／医疗代理隔离回归继续适用 |
| 重复读取产生业务副作用 | 网站及小程序均只读 | 不新增治疗、账单、收退款或决定 | `test_repeated_reads_and_bad_page_values_never_change_money`，独立数据比对 |

上述测试位于`tests/test_patient_cash_activity.py`；网站与原生既有账单规则位于`tests/test_patient_alignment.py`，医疗代理边界位于`tests/test_medical_proxy_preflight.py`。原生处理器另有6项受控传输场景，冻结源处理函数接真实后端的检查不冒充官方工具和真机验收。

正式报告扩展SU-113，无新增业务用例编号或数据库表。准确源提交、完整CI、图片／历史／资金恢复、保护更新及WorkBuddy状态见同目录交付清单。公开证据仅含汇总；个案编号、问答、实际试用金额和账号指南留在本机私有材料。
