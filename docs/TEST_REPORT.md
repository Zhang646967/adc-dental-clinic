# Historical RC1 test report 历史测试报告

Current local application acceptance: [R2.1 diagnosis/logging, 2026-10-18](evidence_r21/README.md).
Previous acceptance: [R1 financial evidence, 2026-10-15](evidence_financial_evidence/README.md).
Current report and future work: [Word/PDF/Markdown report](report-source/README.md)
and [R2 plan](R2_OPERATIONAL_ASSURANCE_PLAN.md), updated 2026-10-18.
The RC1 record below remains historical: its unexecuted Mac/PostgreSQL statements
describe that original environment, not the current R1 delivery.

## 1.0.0-rc.1：批次A／B实际开发检查记录

父版：完整0.9.0-alpha.10。本轮从已取得的源码重建；上次中断目录的图像未被当作已保存代码。
候选编码与文档冻结，不等于正式发布。Windows运行实例最后确认为v0.7；未被访问。Mac迁移暂停。
日期与工具版本以 evidence_rc1/environment.json 为准。

## 本轮实际执行

|层次|结果|证据与边界|
|---|---|---|
|父版基础检查|767个方法通过|parent_checks.log；不是数据库业务测试|
|当前基础检查|799个方法通过，新增32个|basic_checks.log；新增12个独立核算与20个发布合同检查|
|全角色基础UI|672条静态浏览器断言通过|7角色、3宽度、标准/大字、只读/可写；真实base模板转换、合成DOM、实际release-ui.js|
|通知页面回归|756条静态断言通过|notifications/results.json；不是实际HTTP会话|
|协调任务页面回归|888条静态断言通过|tasks/results.json；合成状态|
|候补选时JavaScript|18条断言通过|wait_node.log|
|出诊选时JavaScript|16条断言通过|availability_node.log|
|Python编译|通过|compileall.log；不等于Django导入和迁移验证|
|模型和迁移|11份原模型文件及16份迁移与alpha.10字节一致|schema_comparison.json；本轮没有新增数据库模式|
|规约／模型／源码引用|SU-01—38引用路径存在；19个模型、38份用户目标规约和1份共享规约|release_report/traceability.json；路径存在不是语义正确性的全部证明|
|课程报告|63个物理页完成逐页检查，中文字体已嵌入|report_qa.json；两幅v0.7截图仅是历史观察|
|Django／PostgreSQL|680个测试方法已编写，新增7个；**未执行**|tests/test_release_chains.py：原服务财务与协调链、边界及反例|
|WindowsCMD／真实Docker／Web+worker／升级恢复／公网|**本轮未执行**|RC入口是待目标主机验收的候选，不伪造启动成功|

新增32个基础方法不能等同32个业务场景或完整覆盖率。未重新运行全部旧页面分组；父版证据保持历史身份。

## 批次A如何核对

固定数据 tests/data/release_oracles.json 保存独立预期常量；checks/test_release_oracles.py 使用整数分/千分数量的独立参考计算核对，并将固定预期与原纯规则比较。覆盖逐行舍入、成本缺失/已确认零、无收入牙医成本、修订金额、季度边界和取消率分母。数据库查询、真实更正流程的比较在 tests/test_release_chains.py 中，尚未运行。不是以同一生产函数生成自己的预期输出。

两条业务链已有框架测试定义及 docs/DEMO_ROUTES_RC1.md 人工路线；不是已录制的真实浏览器演示。
release-ui改善字段错误定位、明确只读提示和帮助入口命名；不静默修正输入、不自动提交。键盘焦点与尺寸检查不构成完整WCAG认证。

## 批次B的安全边界

RC_WINDOWS.cmd 将隔离verify、新建空演示库、可信v0.7副本恢复分开。旧就地升级入口改为停止提示，原文归档；新脚本没有删除旧卷、连接旧实例或覆盖旧库的命令。schema成功是Web与通知worker启动的前置依赖；只读worker不派发。loopback课程配置不是公网生产配置。

导入副本前后比较八类旧业务表的选定字段摘要，仅检查该范围的保留，不是全库逻辑等价、来源认证或真实恢复证明。数据库归档、凭据与摘要均私密；累计文件差异只能应用到独立源码副本。

requirements声明从alpha.10保留，增加record_runtime.py供G1记录实际安装版本。当前未解析/安装完整依赖，因此不是带哈希的跨平台可复现锁文件。固定容器版本与实际主机支持在G1核验。

## 环境阻断实际记录

Linux/Python3.13.5，无Docker、Django、psycopg或PostgreSQL工具。依赖下载和域名解析尝试失败，见 dependency_attempt.log 及 environment.json。本轮未用SQLite或模拟ORM冒充真实数据库测试。

## 本轮发现与修正

1. 中断目录只有图像，没有完整代码；以完整alpha.10为父版重建，避免错用未保存成果。
2. 旧就地升级脚本可能遗漏通知worker停写；RC中全部改为拒绝直接执行，统一新目录/副本路径。
3. 新UML内嵌图继承正文固定行距而被裁切；改为图段单倍行距并重新检查全部63页。D02端点与SU-19旧范围说明亦修正。
4. 新附录与旧报告同一编号体系校核；38个SU、1个SF与源码位置对齐，规划功能不写成实现。
5. 源清单排除Docker构建时不会复制的运行证据和日志；整包CHECKSUMS另行覆盖归档文件。验证不会因为有意排除的日志而误报源码缺失。
6. 独立验证镜像与演示使用同一production requirements；验证容器仅为输出宿主证据以root运行，不把它说成非root生产运行验收。

## 尚需执行的集中门槛

G1：真实依赖安装、check、模式/迁移与680项框架定义的实际发现执行、事务及并发。
G2：v0.7合成数据副本升级、旧编号/金额/授权核对、真实备份恢复。
G3：真实HTTP/浏览器两条主链、全角色、跨店、旧页、只读、大字/键盘、worker停止失败恢复。
G4：目标域名/HTTPS、数据库隔离、运行与迁移角色、后台监督、日志、备份等公网验收。

完成A/B编码和交付整理后进入RC；四门槛不因版本号而自动通过。验收缺陷在冻结范围内修复，不以新增功能代替。

## 可复现入口

```text
python -m unittest discover -s checks -v
node checks/test_wait_window_node.cjs
node checks/test_availability_node.cjs
python scripts/check_release_ui.py
python scripts/check_notifications_browser.py
python scripts/check_tasks_browser.py
RC_WINDOWS.cmd verify
```

最终源包与原v0.7重组检查另见交付JSON。源码哈希和文件匹配不是数字签名、应用安全认证或数据库升级成功证明。
