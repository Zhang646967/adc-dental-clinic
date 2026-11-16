# Implementation Plan — 报告复诊名称与本人查阅提示

**Branch** `ci/spec-kit-report-followup-consistency`
**Date** 2026-11-15
**Spec** [spec.md](spec.md)

## Summary

复用已发布服务投影修正报告服务名称。现有工作区先核验当前授权，再把有效代理的本人限定结果传给网页和小程序。试用环境使用新合成实例 18540。

## Technical Context

| 项目 | 本轮选择 |
|---|---|
| 后端和网页 | Django、既有患者角色中间件、报告投影和模板 |
| 小程序 | 31 页及现有会话状态处理，WorkBuddy 使用独立分支 |
| 数据库 | PostgreSQL 17，98 份现有迁移 |
| 验证 | PostgreSQL、Chrome、真实小程序 HTTP、微信开发者工具 |

## Constitution Check

FR 与验收见 [任务](tasks.md)。报告只改患者投影，预约编号和金额仍由既有命令持有。代理拒绝在查询前完成，版本与运行环境分别核对。

## Project Structure

- `portal/report_followup.py` 读取有效公开服务名称。
- `portal/policies.py` 区分本人权限和有效代理权限。
- `workspaces/middleware.py`、`templates/portal/report_self_required.html` 映射报告拒绝结果。
- `clients/wechat/miniprogram/pages/{examination,report-notices}/` 处理本人限定。
- `tests/test_examination_followup.py`、`scripts/verify_native_alignment.cjs` 验证实际访问和页面回退。

## Design

[调查与决策](research.md) · [现有数据关系](data-model.md) · [接口合同](contracts/report-followup.md) · [试用流程](quickstart.md)

## 18541 · 复诊待办与异常接续

- 以 `4870a6e` 为基线，扩展 `portal/patient_dashboard.py` 的共用投影与原网页、小程序主行动。只查询本人最新有效发布决策，按原报告规则决定查号或联系，沿用改期链及实际完成依据。
- 扩展 `clinical/continuity_selectors.py` 与现有前台清单，使用同一预约投影区分建议期与跟进期限。数据库结构和预约确认合同沿用现状。
- 用独立 PostgreSQL 18541 准备已读未约、无号、超期和取消样本。Codex 核对网页、接口、岗位及准确提交 CI，WorkBuddy 独立完成工具正常点击复测。
