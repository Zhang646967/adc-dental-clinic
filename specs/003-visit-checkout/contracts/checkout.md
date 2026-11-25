# 离店核对读接口

患者本人从现有就诊详情 GET 读取 `review`。预约代办的 `care`、`settlement` 为 null，`followups` 为空。前台网页只从当前门店的已授权就诊生成结算和预约摘要。一笔查询内的发票版本、分摊、收退与预约链按同一 PostgreSQL 快照读取。

| 字段 | 含义 |
| --- | --- |
| `settlement_state` | 已发布 PUBLISHED，到诊后尚未发布 AWAITING_PUBLICATION。就诊前或无权访问为 null。 |
| `settlement` | 已发布才提供。保留 invoice_id、invoice_no、revision、total、remaining、refund_due、review_pending。金额均为人民币十进制字符串，零为 0.00。 |
| `receipts / refunds / net_received` | 当前结算单已记账收款、已记账退款、两者净额。 |
| `advance_applied / insurance_fund / insurance_personal_account` | 此单已抵扣预收、已核对的基金、个人账户。待复核金额不计入已记账。 |
| `pending_refunds` | 待审核退款申请金额，独立于已退与应退余额。 |
| `followups[]` | 每条医师指示占一行。沿用 id、service、窗口、status、label、appointment。clinic、clinic_id 标识原门店。 |
| `active_appointment / historical_appointment` | 有效预约与最近相关历史分列，可同时存在。字段 id、visit_no、start、status、status_label、clinic。预约改期显示有效后继，取消无后继仅属历史。 |
| `action` | VIEW_APPOINTMENT 看有效预约，BOOK 按指定报告查号，CONTACT 联系原门店，NONE 查阅记录。处于 CONTACT 时仍可查看保留的有效预约。 |
| `booking_source` | 仅本人、允许 BOOK 时给出 clinic、service、followup_visit、followup_examination、followup_revision。查号、预览、确认继续校验现有报告约束。 |

读取、返回和刷新均无业务写入。未发布和已发布零元要分别显示。历史账单使用原有版本读取接口，当版费用和当前余额分开。
