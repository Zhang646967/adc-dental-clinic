# 患者复诊随访接口

沿用已授权的患者概览 GET /api/mini/v1/overview/ 与原就诊详情 GET /api/mini/v1/visits/<id>/。GET 保持只读。服务端选择一个主行动。查阅、联系原门店和到店预约是三个独立事实。

| 服务端结果 | 网页与原生端处理 |
| --- | --- |
| primary_action.kind 为 VISIT_FOLLOWUP | 仅本人。使用 label、button、hint 与 followup.visit_id、followup.instruction_id 两个正整数，在同一就诊标出对应的下次安排。visit 和 offer 为空。选择服务或其他预约入口继续按原功能办理。 |
| REPORT_FOLLOWUP | 依照 report.visit_id、id、revision 打开当前发布报告。 |
| UPCOMING_VISIT 或 CHECKED_IN | 使用原预约的实际到店日期与编号。建议窗口继续留在原指示。 |
| 原就诊 review.followups[] | 每项 id 对应指示编号。status=REVIEW 可用于暂缓或其他需核对状态，展示服务端 label。暂缓时 label 为“复诊安排已暂缓”，可选 message 为“需要继续安排时，可联系原门店。”；action=CONTACT。一个指示可同时含 active_appointment 和 historical_appointment，分别呈现。 |
| 权限或数据变化 | 使用已授权的原详情和既有清空/重载机制。只允许用同一就诊在本次响应内的指示定位。过时、他人的编号或缺失参数均不能展示缓存中的指示。 |

普通指示的示例（示意编号随样本库生成）

    {"kind":"VISIT_FOLLOWUP","label":"复诊时间待安排","button":"查看下次安排","hint":"建议日期已过，您尚未预约。可联系原门店核对时间。","visit":null,"offer":null,"followup":{"visit_id":1,"instruction_id":2}}

兼容示例：旧概览的 BOOK 无 followup 字段。旧的原就诊详情可能没有 message 或下次安排。保留原首页、原详情和返回路径。缺编号时保留原就诊可用入口，禁止拼接未授权地址。医师内部核对依据、前台最近联系结果、负责人和内部期限不进入上述接口。
