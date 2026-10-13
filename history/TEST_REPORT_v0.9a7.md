# v0.9.0-alpha.7 实际检查记录

记录时间（UTC）：2026-10-08T12:57:16.689036+00:00。父版是完整v0.9-alpha.6替代记录版本；其TEST_REPORT原文归档于history/TEST_REPORT_v0.9a6.md。

|层次|本轮实绩|证据边界|
|---|---|---|
|父版检查重跑|542个基础方法通过|parent_checks.log；不是数据库测试|
|本候选基础|578个方法通过，其中新增36个|basic_checks.log；纯规则/源码合同/原模拟编排|
|候补选时JS|18条断言通过|wait_window_node.log；非真实Web提交|
|出诊选时JS|16条断言通过|availability_node.log；非真实Web提交|
|新协调页|684条静态Chromium断言通过|14种合成状态，320/390/1440px，standard/comfortable|
|原出诊页回归|396条静态断言通过|新源码源模板及合成字段|
|原目录页回归|318条静态断言通过|新源码源模板及合成字段|
|原联络更正回归|120条静态断言通过|同上|
|原结果核对回归|249条静态断言通过|同上|
|原选时/账号回归|129条静态断言通过|同上|
|models与旧迁移|10份models.py与13份原迁移逐字节不变|validation_scope.json逐项指纹；不是数据库已迁移|
|原写命令|预约、邀约及出诊维护服务未改变|逐字节对比，不等于调用方集成已验证|
|Django/PostgreSQL|496个方法已编写（新增41个），**尚未执行**|继承455项定义，不用模拟ORM或SQLite冒充PG|
|用户实例/公网/恢复/Mac/真实AI|本轮未执行|无相关完成证明|

## 实际环境与尝试

本轮环境Python3.13.5/Linux。缺少Docker、Django、psycopg和PostgreSQL工具；Playwright/Chromium可用。
重新尝试按requirements下载依赖失败，pypi.org及files.pythonhosted.org的容器内DNS探测失败。另尝试下载实际Django wheel也失败，未安装任何替代版本。

`python scripts/verify_isolated.py`已实际调用，在寻找Docker阶段停止：executed=false、all_gates_passed=false，未启动数据库或业务检查；见isolated_attempt.log。缺Docker时不伪造cleanup=0，保持无实际清理状态。

## 对新增检查的解释

新增纯规则覆盖时间边界、已接受优先于原期限、临床保护、异常关联、当前页与总量区分、大小写/Unicode/URL混入来源ID及失败恢复说明。源码合同检查限制读取层不得调用业务写命令，但不是数据库副作用证明。

新增Django测试使用真实模型、原中间件及TransactionTestCase，没有用替身实现ORM。故障注入只用于查询失败/规则异常与同步时机。共享锁测试使用两条真实连接，并在数据库等待事件中核对写方等待；本环境没有执行它。

静态浏览器脚本将源模板转换后使用合成字段渲染；截图带STATIC FIXTURE及虚构日期，不能替代真实服务端渲染、会话或E2E。已目视核对混合承诺、临床保护、无阻断和异常页的代表性宽窄屏，规则文案与类别一致。没有发明真实患者或真通知记录。

基础计数、JavaScript断言及浏览器断言不能相加称为通过业务场景数，也不是需求覆盖率。现阶段不声明本候选达到生产或临床使用标准。

## 可复现入口

```text
python -m unittest discover -s checks -v
node checks/test_wait_window_node.cjs
node checks/test_availability_node.cjs
python scripts/check_front_coordination_browser.py
python scripts/check_availability_browser.py
python scripts/check_directory_browser.py
python scripts/check_contact_browser.py
python scripts/check_v09_browser.py
python scripts/check_v08_browser.py
```

Windows独立测试：`VERIFY_ISOLATED_WINDOWS.cmd`，在新目录运行，不复制旧.env，不复用旧卷。
真实门槛仍包含Django check、迁移差异、临时库迁移及`manage.py test tests --settings=config.settings.test`，以实际发现/执行输出为准。

## 最终文件重组

发布包需与原v0.7重组，核对目标文件、清单并重跑578项基础方法及18/16两组JS。结果单独保存于交付包校验JSON。该重组不连接真实数据库，不证明v0.7带数据已成功升级。
