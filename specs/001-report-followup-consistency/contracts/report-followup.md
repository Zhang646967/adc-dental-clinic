# Contract — 复诊服务及本人限读

## 服务名称

报告详情 `GET /api/mini/v1/visits/<visit>/examinations/<order>/?revision=<revision>` 与网页共用投影。`followup.service_id` 保持原编号。`followup.service` 在服务正常公开时等于公开目录标题。服务退出目录时沿用指示服务名称及原联系或查看既有预约路径。

## 本人限定

有效预约代办或医疗代理访问以下三个接口，返回 **403**。

- `GET /api/mini/v1/report-notices/`
- `POST /api/mini/v1/report-notices/<id>/read/`，沿用 CSRF 和工作区约束
- `GET /api/mini/v1/visits/<visit>/examinations/<order>/`

```json
{
  "ok": false,
  "code": "REPORT_SELF_REQUIRED",
  "message": "检查报告与提醒仅限患者本人查看。请由患者本人登录后办理。",
  "request_id": "<查询编号>"
}
```

失效工作区及授权继续按原流程处理。本人访问他人报告为通用 404。网页对应路径在 403 页面显示同一句提示、查询编号及返回患者工作台入口。

小程序对 `REPORT_SELF_REQUIRED` 清空私有状态并保留返回入口。该代码不进入会话过期恢复。旧后端沿用既有兼容路径。

## 患者下一步与前台筛选

`GET /api/mini/v1/overview/` 的 `primary_action` 增加 `REPORT_FOLLOWUP`。该类型保留 `label`、`button`、`hint`，携带 `report: {visit_id, id, revision}` 三个正整数。双端以同一报告版本进入现有详情。其他类型沿用既有字段。旧后端继续返回原有类型。

当前已发布报告的最近一项决策为 BOOK 或仍待联系的 CONTACT 时，按复诊进度生成候选。实际目标完成、已约在办、无后续事项及撤回均从该待办排除。原建议期内取消无后继可重新查号，超范围或需核对则给出联系指引。报告详情仍决定是否能查号或提交。

前台 `/clinical/recalls/?queue=past_unbooked` 按本门店、现行指示与 `latest_on < 北京日期` 筛选。按现有预约链和实际完成规则核对是否仍待安排。`queue=overdue` 仍使用 `followup_due_at`。两端刷新和筛选不改变提醒读态、预约、随访和临床状态。

## 18547 · 已约复诊的来源

患者网页和 `GET /api/mini/v1/visits/<id>/` 共用 `review.return_sources`。它是数组，普通预约、已取消或已改期的原记录、预约代理均为空。旧后端可能缺此字段。每一行含 `source_visit_id`、`source_visit_no`、`service`、`state`、`label`、`report`。以 `CURRENT` 表示已核对一次有效关联，`CONTACT` 表示需联系本门店。报告仅在关联及当前发布均有效时返回 `{id, number, project, revision}`，使用原就诊 id 打开。其余情况为 null。普通的已关联复诊也可以没有报告。患者响应只含这些导航字段，病历、过敏信息、医师目标、治疗步骤和内部执行阶段均在医师端按权限读取。

从报告返回应回到发起查看的复诊，再从该预约按需查看原就诊。多个来源逐项呈现。点击查看、刷新、换账号及返回均不新增预约、不标记提醒已读、不保存临床事实。

正式配置沿用既有网址与响应字段。工作清单、报告版本、提醒计数、复诊来源及确认必须属于已开通项目且项目门店与原就诊一致。技术管理命令独立管理开通、暂停与职责撤销。暂停不改写已成立预约。站内发布不构成手机推送或已读回执。
