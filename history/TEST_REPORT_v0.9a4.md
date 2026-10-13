# v0.9.0-alpha.4 实际检查记录

记录时间（UTC）：2026-10-08T07:40:52.663434+00:00。父版记录存于 history/TEST_REPORT_v0.9a3.md。

|层次|本轮结果|边界|
|---|---|---|
|父版回归|372个基础方法通过|本轮重新执行父版源码，不是数据库测试|
|当前基础|425个方法通过，其中新增53个|纯规则、文件、结构与模拟Docker/psql编排|
|既有选时JS|18条断言通过|无真实Web提交|
|Mac入口|Bash语法检查通过；缺Docker时正确停止|Linux的Bash检查，不是macOS原生运行|
|源包兼容|原v0.7的379文件清单可读取并按原字节打包|没有访问Windows运行实例|
|模型／迁移|10份模型文件及13份迁移与alpha.3逐字节一致|只有ADC_VERSION改为alpha.4|
|Django／PostgreSQL|344个既有测试方法已编写，未运行|没有用SQLite替代|
|真实导出／恢复／Mac ARM／正式交接|本轮未执行|工具是待目标环境验收的候选实现|

## 环境核对

Python 3.13.5 / Linux x86_64。未安装Docker、Django或psycopg；本轮尝试获取指定依赖失败，另外的域名解析检查对pypi.org和files.pythonhosted.org返回临时解析失败。doctor准确记录local_engine_available=false，没有进入数据库操作。

## 测试覆盖的风险

源ID／服务／连接URL错误、远程context、未停写的正式交接、路径穿越、大小写和Unicode碰撞、符号链接、私密文件排除、源文件修改保留、旧v0.7清单、文件丢失／损坏、失败标记、恢复失败、错误拥有者标签阻止清理。恢复编排使用替身，不证明SQL已执行。

## 可复现入口

- `python -m unittest discover -s checks -v`
- `node checks/test_wait_window_node.cjs`
- `bash -n VERIFY_ISOLATED_MAC.sh`
- Windows Docker-only：`VERIFY_ISOLATED_WINDOWS.cmd`
- Mac Docker-only：`bash VERIFY_ISOLATED_MAC.sh`
- 环境盘点：`python scripts/migration_tool.py doctor --source <实际工程> --out <新结果文件>`

新功能不改变业务模板，因此本轮没有重新宣称旧静态浏览器断言为新执行结果。完整业务、数据库、恢复与实际迁移各自取证。

## 打包

最终交付另外生成整包/累计包SHA-256与v0.7重组核对记录；这些属于文件完整性，不是数字签名或升级成功证明。
