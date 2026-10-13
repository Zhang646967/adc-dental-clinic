# v0.9.0-alpha.5 实际检查记录

记录时间（UTC）：2026-10-08T11:05:59.365116+00:00。父版：alpha.4；R4.4未修改；Mac迁移暂停。

|层次|本轮实际结果|边界|
|---|---|---|
|父版基础重跑|425方法通过|本轮重跑父版，不是框架测试|
|当前基础|485方法通过，新增60方法|纯规则、源结构及已有模拟编排；不是485个真实业务场景|
|原候补选时|18条Node断言通过|不是完整HTTP表单|
|新目录页面|318条Chromium静态断言通过|9种页面状态，320/390/1440宽度及两种字号；合成表单/数据|
|联络更正回归|120静态断言通过|本轮重新执行新源码模板|
|候补结果页回归|249静态断言通过|本轮重新执行新源码模板|
|原选时/账号回归|129静态断言通过|本轮重新执行新源码模板|
|Python语法|新代码、测试及全源码AST检查通过|不能替代Django模板解析/ORM运行|
|Django/PostgreSQL|399个test_方法定义已编写，其中新增55个；未执行|包含事务、权限、HTTP、两连接竞争和账单历史保护；不是框架已经发现/通过399个|
|原模型/迁移|10份models.py与13份迁移与alpha.4字节一致|新表、字段、数据库迁移均未增加|
|迁移与隔离入口|8份列示文件保持原字节|保留不等于重新运行恢复/迁移|
|本机升级/公网/恢复|没有执行|你原Windows实例不受本轮操作影响|

## 检查中实际发现并修正的问题

首次基础检查失败1项：旧`test_guide_routes_declared_without_model_urls`只扫描四个历史urls文件，无法识别新登记路由及既有账号治理路由。改为递归读取当前config.urls的实际include()声明，仍逐一检查所有指南路由，没有删除断言或把缺失路径白名单化。修正后485方法通过。初次失败日志和最终日志均保留。

## 环境阻断

当前Python 3.13.5 / Linux；没有Docker、Django、psycopg或PostgreSQL命令。按原requirements尝试下载依赖失败；pypi.org和files.pythonhosted.org域名解析分别返回临时失败。没有静默降级依赖或用SQLite替代PG。
独立验证主持脚本在寻找Docker时停止，`executed=false`和`all_gates_passed=false`。没有开始业务数据库测试，也没有创建/删除原实例的数据。

## 可重现入口

- 基础：`python -m unittest discover -s checks -v`。
- Node：`node checks/test_wait_window_node.cjs`。
- 目录静态：`python scripts/check_directory_browser.py`，需要Playwright、Jinja2、Chromium。
- 既有静态：`ADC_BROWSER_EVIDENCE_DIR=<新证据目录>`可分别给check_contact_browser.py、check_v09_browser.py、check_v08_browser.py指定输出，避免覆盖历史证据。
- Windows Docker-only真实门槛：完整包新目录执行`VERIFY_ISOLATED_WINDOWS.cmd`。真实输出决定实际发现数量和结果。

## 证据与注意事项

`docs/evidence_v09a5/validation_scope.json`列示版本、环境、分层实绩和原文件指纹。browser及regression目录下截图是源模板加合成字段，包含转义测试文本和极端长地址，不能当作真实使用者验收截图。
真实验收仍须核对：预览零业务写入、目录与审计原子性、当前角色与上下文、同码/同关联竞争、重复确认、关联ABA、恢复保留原编号/备注、只读拒绝、历史账单和现有业务无副作用。
测试方法数与浏览器断言数不能相加当作场景数，也不是需求覆盖率或安全认证。
