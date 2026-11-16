# Tasks — 报告复诊名称与本人查阅提示

## 规格与准备

- [x] T001 根据 18539 回传定义 FR-001 至 FR-004 与跨端验收。Codex · `spec.md`。
- [x] T002 冻结服务名称与本人限读接口。Codex · `contracts/report-followup.md`。

## US1 · 同一服务（FR-001，SC-001）

- [x] T003 [US1] 接入患者目录标题，验证目录退出及历史兼容。Codex · `portal/report_followup.py`、`tests/test_examination_followup.py`。
- [x] T004 [US1] 独立实例的网页和小程序均通过同名复诊核对。Codex 核对网页和接口，WorkBuddy 完成 WB-S1。

## US2 · 明确本人限定（FR-002 至 FR-004，SC-002）

- [x] T005 [US2] 区分有效代理本人限定、授权变化及跨患者拒绝。Codex · `portal/policies.py`、`workspaces/middleware.py`、`templates/portal/report_self_required.html`。
- [x] T006 [P] [US2] 在提醒及报告详情接入本人限定反馈，保留返回和清空。Codex 实现，WorkBuddy 独立复测。
- [x] T007 [US2] WorkBuddy 在微信开发者工具 390 宽完成 WB-S1 至 WB-S4，已核对查询编号与本机截图。

## 集成（SC-003）

- [x] T008 核对后端、网页、真实 HTTP、原生源码和 18540 数据，检查业务新增为零。Codex。
- [x] T009 提交 `0c4c654` 的完整 CI 通过。已核对 11 个查询编号及 13 张业务表的逐表校验值，见 [18540 验收](../../docs/EXAMINATION_FOLLOWUP.md#18540-一致性验证)。
