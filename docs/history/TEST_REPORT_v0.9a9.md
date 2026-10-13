# v0.9.0-alpha.9 实际开发检查记录

记录时间（UTC）：2026-10-08T14:24:58.512521+00:00。父版alpha.8检查先重跑635个方法通过，父版原检查说明留在`docs/history/TEST_REPORT_v0.9a8.md`。
用户本机验证继续留到v1.0候选；不要求当前安装。最后确认实例仍为Windows v0.7；Mac迁移暂停；R4.4报告冻结。

|层次|本轮实绩|验证边界|
|---|---|---|
|父版基础重跑|635个方法通过|纯规则、源码合同和原模拟编排，非真实数据库|
|本候选基础检查|708个方法通过，新增73个|`basic_checks.log`；不能当作708个业务场景或覆盖率|
|新协调任务页面|888条静态浏览器断言通过|18种合成状态、320/390/1440px、标准/大字；源模板转换|
|原前台协调回归|684条静态断言通过|本次修改后的原模板，含记录编号与任务链接|
|原出诊维护回归|396条静态断言通过|本次修改后的模板；非真实会话|
|原接收控制回归|498条静态断言通过|沿用原写服务，模板回归|
|原选时JavaScript|候补18条、出诊16条断言通过|Node契约；非Web提交|
|Python编译|当前Python文件compileall通过|语法检查，不证明Django导入或迁移有效|
|模型/迁移|父版14份迁移不变；10个models.py中9个不变；coordination追加CoordinationTask|新增15th迁移`coordination.0002_coordination_tasks`未在数据库执行|
|原业务写命令|6份关键服务字节不变|见`validation_scope.json`；调用方集成仍待真实检查|
|Django/PostgreSQL|620个测试方法已编写，其中新增66个；尚未执行|包括真实模型、HTTP、迁移和独立连接竞争；不用SQLite代替|
|用户实例/公网/恢复/Mac/真实AI|未执行|无对应完成证明|

原基础目录、患者联络、候补结果和通用账号静态浏览器组本轮未重跑，不以历史绿色结果冒充新增执行证据。全局样式/导航与真实会话还需v1.0集中回归。

## 本轮检查发现及处理

1. 插入任务导航时，两个旧详情模板的链接一度进入title块。源码复查发现后移回content块，补充反例检查，并重新跑前台协调、出诊维护和接收控制静态测试。
2. 新任务预览合成样例中的批准前状态、理由和重复“确认”文案已修正；临床意图优先于任务关键词分流，增加回归断言。
3. 一次批量浏览器命令超过工具的200秒调用上限，子进程被终止，日志保存为`regression_front_coordination_timeout.log`。之后将脚本分别运行，相关结果全绿；未吞掉该次中止记录。
4. 原接收字段迁移测试只恢复一个旧目标，在增加下游任务迁移后不充分；改为保存并恢复原全部迁移叶节点。它仍是待执行数据库测试，不宣称已实际迁移成功。

## 环境与依赖尝试

当前Python 3.13.5 / Linux x86_64。实际未找到Docker、Django、psycopg和PostgreSQL工具。按父版requirements获取依赖失败；pypi.org及files.pythonhosted.org的DNS探测返回临时解析失败。见`environment.json`和`dependency_attempt.log`。未运行数据库或真实HTTP测试，没有把模拟ORM/SQLite作为PG替身。

## 新增真实数据库测试定义

`tests/test_v09_tasks.py`共66个方法，累计tests目录620个方法，实际框架发现数量到运行时确认。
覆盖：主动发起与单一有效任务、无副作用预览、前台自领与owner限制、声明不清阻断、其他出诊引用拒绝、有效旧邀约保护、临床记录阻断、不同账号复核、暂停恢复导致旧摘要失效、已成功重放、不变更原业务、角色/诊所/CSRF/只读、审计失败回滚、任务历史触发器、空表迁移往返/有数据拒绝反向，以及两个独立数据库连接的同源建任务和同任务受理竞争。
这些是已编写的验收要求，不是已发生的通过事件。任务服务只更新任务和审计；实际事务和并发性质必须在PostgreSQL上验证。

## 图像和可重复入口

`docs/evidence_v09a9/browser`为新任务样例，页面带STATIC FIXTURE，使用2031年的虚构示例日期，不能作为用户实例运行截图。

```text
python -m unittest discover -s checks -v
node checks/test_wait_window_node.cjs
node checks/test_availability_node.cjs
python scripts/check_tasks_browser.py
python scripts/check_front_coordination_browser.py
python scripts/check_availability_browser.py
python scripts/check_intake_browser.py
```

原Windows隔离入口保留，用户到v1.0候选时再集中使用。升级脚本的显式确认、备份和验证门槛没有删除。本轮开发没有自行建立通知或外部API调用。

## 文件归档

最终完整包与原v0.7累计包另生成校验JSON；用原v0.7重新组合后再核对目标字节、文件清单和基础/JS检查。这些只证明源码组合一致，不代表带数据升级、恢复或旧版兼容写入通过。
