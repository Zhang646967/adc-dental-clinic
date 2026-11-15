# Tasks — 报告复诊名称与本人查阅提示

## 规格与准备

- [x] T001 根据 18539 回传定义 FR-001 至 FR-004 与跨端验收。Codex · `spec.md`。
- [x] T002 冻结服务名称与本人限读接口。Codex · `contracts/report-followup.md`。

## US1 · 同一服务（FR-001，SC-001）

- [x] T003 [US1] 接入患者目录标题，验证目录退出及历史兼容。Codex · `portal/report_followup.py`、`tests/test_examination_followup.py`。
- [ ] T004 [US1] 在独立实例比对网页与小程序的报告及确认页。Codex 验证网页，WorkBuddy 验证原生流程。

## US2 · 明确本人限定（FR-002 至 FR-004，SC-002）

- [x] T005 [US2] 区分有效代理本人限定、授权变化及跨患者拒绝。Codex · `portal/policies.py`、`workspaces/middleware.py`、`templates/portal/report_self_required.html`。
- [ ] T006 [P] [US2] 在提醒及报告详情接入本人限定反馈，保留返回和清空。WorkBuddy · `clients/wechat/`。
- [ ] T007 [US2] 在开发者工具实际复测 390 宽，记录正常入口、换身份结果和查询编号。WorkBuddy。

## 集成（SC-003）

- [ ] T008 核对后端、网页、真实 HTTP、原生源码和 18540 数据，检查业务新增为零。Codex。
- [ ] T009 核对差异与准确版本的完整 CI，归档双端实际验收。Codex。
