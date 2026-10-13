# v0.9.0-alpha.3 实际检查记录

记录时间（UTC）：2026-10-08T07:05:49.410149+00:00。这是候选源码的本轮记录；父版本记录保存在`history/TEST_REPORT_v0.9a2.md`，不是以旧记录冒充重跑。

|层次|本轮结果|边界|
|---|---|---|
|父版本基础|325方法实际通过|纯规则/结构/替身，不是真实业务集成|
|本候选基础|372方法实际通过，新增47方法|`unit_372.log`；包括字段、签名载荷格式、ABA、路由/服务结构和独立验证配置规则|
|既有选时JS|18断言实际通过|Node契约，不是真实表单提交|
|新增联络页面|120静态Chromium断言通过|320/390/1440宽度，两种字号，四种状态，溢出/显示/明确确认/转义|
|既有结果页回归|249静态Chromium断言通过|新源码模板及合成数据|
|选时与账号页回归|129静态Chromium断言通过|新源码模板及合成数据|
|Django/PostgreSQL|344方法已编写，**未运行**|其中33项为联络更正，包括真实事务/HTTP/两连接竞争|
|模型和迁移|所有原模型文件及13份迁移与alpha.2相同；13份迁移亦与v0.7相同|文件不变不等于真实数据库已迁移/验收|
|用户实例/公网/恢复|本轮**未操作、未验收**|仍须用户独立验证与之后的升级/恢复演练|

## 环境阻断已实际核对

当前Python 3.13.5；未安装Django、psycopg、PostgreSQL或Docker。依赖下载/DNS失败。运行独立验证主持脚本时在寻找Docker阶段即终止，记录`executed=false`和`all_gates_passed=false`，没有开始业务数据库测试。没有把模拟ORM、SQLite或AST检查算作PG测试。

## 可重现入口

- Windows CMD、只有Docker时：`VERIFY_ISOLATED_WINDOWS.cmd`（完整容器运行未在本环境执行）。
- 基础：`python -m unittest discover -s checks -v`。
- JS：`node checks/test_wait_window_node.cjs`。
- 静态页面：`python scripts/check_contact_browser.py`、`python scripts/check_v09_browser.py`、`python scripts/check_v08_browser.py`；需要Chromium、Playwright及Jinja2。
- 原框架门槛：`python scripts/integration_gate.py`；仅在独立配置下先运行，包含迁移写入及测试库创建销毁。

## 特别要检查的业务后置条件

预览不修改Patient/审计；确认只写五字段；旧页、撤权、跨店、患者停用拒绝；同次确认不重复记账；其他前台新值不被旧预览覆盖；A→B→A仍拒绝旧页；审计异常回滚；已发布Invoice头快照不跟随地址修改；只读模式不能保存。
这些结论当前是规约与待执行测试的预期，不能仅从代码/静态页面认定已经全部成立。

## 证据文件

`evidence_v09a3/validation_scope.json`包含版本、环境、检查数量及13份迁移指纹。
`evidence_v09a3/browser/`为新增页面合成检查；`result_browser/`和`interaction_browser/`为既有页面本轮回归。截图里的合成值、固定时间、注入测试字符串都不是患者数据/真实业务记录。

基础计数、断言数、方法数不能相加称为“通过业务场景数”，也不是需求覆盖率。正式发布还需要真实数据库、浏览器端到端、带数据副本升级、回滚恢复与目标环境测试。
