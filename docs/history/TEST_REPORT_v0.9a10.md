# v0.9.0-alpha.10 实际开发检查记录

日期2026-10-08；环境时点见docs/evidence_v09a10/environment.json。父版alpha.9检查重跑并保存parent_checks.log，父版原记录归档于docs/history/TEST_REPORT_v0.9a9.md。

用户本机部署/集中版本验收留到v1.0候选；本轮不要求安装、不访问Windows实例。Mac迁移暂停，R4.4冻结。

|检查层次|本轮结果|边界|
|---|---|---|
|父版基础重跑|708个方法通过|原源码纯规则/合同/替身，不是PG|
|当前基础|767个方法通过，新增59个|通知规则、路由/边界、队列代码合同与原检查；不是767个业务端到端|
|新通知静态浏览器|756条断言通过|13种合成状态，320/390/1440px、标准/大字；实际导航从NAV声明构造，模板经转换|
|原任务界面回归|888条静态断言通过|当前源模板、合成数据|
|原前台协调/接收控制|684条/498条静态断言通过|不是实际Django会话或真实数据库页面|
|两组JavaScript|18条/16条断言通过|候补与出诊选时算术，不是表单提交|
|Python compileall|通过|仅语法，非Django导入或迁移验证|
|原模型/迁移|旧10份models.py、15份迁移逐字节不变|新增notifications/models.py及1份迁移未在数据库执行|
|Django/PostgreSQL|673个测试方法已编写，新增53个，尚未执行|真实模型、事务、HTTP、两连接worker竞争；不用SQLite替代|
|用户实例/公网/worker运行/恢复/外部AI|本轮未执行|无相关通过证据|

本轮未重跑全部历史静态组（例如目录、联络更正与财务页面），不把父版结果冒充本轮执行。当前截图是STATIC FIXTURE，并非用户实例图片。实际查看通知窄屏与失败状态宽屏，检查字形、确认控件和时间/状态区分。

## 环境核对

Python3.13.5/Linux x86_64；无Docker、psql、Django、psycopg。尝试下载父版固定requirements失败，输出保留dependency_attempt.log；独立DNS查询pypi.org失败，errno=-3。未偷偷改动固定版本、未借用SQLite/模拟ORM冒充PG测试。当前没有启动后台worker或执行任何数据库模式变更。

## 新PG/HTTP测试的目标

任务预览不入队、事务回滚无幽灵消息、入队失败回滚任务和审计、重复任务命令不重复事件、收件快照和当前授权双检查、后加授权不补发、撤权/停用抑制、先插入再失败全撤销、有界重试、失败重排不重做任务、显式本人已读、跨店/当前角色/CSRF/旧页、只读模式、已读首次时间、原目标不可改写、去重约束、事件反向迁移保护、SKIP LOCKED并行选择、两个worker不重复生成。定义数不是通过数。

## 检查中发现并修正

- 重试命令的行锁明确限制of=('self',)，不从关联查询额外取得任务/出诊锁，以免颠倒既有锁顺序。
- 派发验证补齐原审计动作、任务修订、状态、出诊和时间关联；消息状态不能伪装为当前任务状态。
- 幂等投递命中已有消息时进一步核对原所有权，不能忽略异常收件记录。
- 新静态页面按真实NAV声明生成前台/主管导航，避免只用空导航检查响应式。

以上修正经纯检查/源码审查及静态UI检验，不宣称相应SQL已执行。

## 可重复开发入口（到1.0再要求用户统一运行）

```text
python -m unittest discover -s checks -v
node checks/test_wait_window_node.cjs
node checks/test_availability_node.cjs
python scripts/check_notifications_browser.py
python scripts/check_tasks_browser.py
python scripts/check_front_coordination_browser.py
python scripts/check_intake_browser.py
```

真实框架入口仍是独立Compose验证；包括makemigrations --check、临时库迁移及全部tests。之后还需要v0.7带数据升级、真正恢复、真实浏览器E2E及worker停机/恢复。文件哈希与测试数量不是完整性/可靠性认证。

## 归档

完整/累计包重组及指纹另见交付JSON。本轮不是1.0正式版；之后的两个计划开发批次和集中验收门槛见docs/V1_SCOPE_AND_REMAINING.md。
