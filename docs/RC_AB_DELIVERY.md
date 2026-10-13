# A/B交付核对 — 1.0.0-rc.1

**编码/文档整合完成并冻结；G1—G4仍待真实验收。** 这是本次实际文件对应表，不以旧工作中断记录冒充完成。

|工作|已落地文件|状态/验收限制|
|---|---|---|
|A1独立核算|tests/data/release_oracles.json；checks/test_release_oracles.py|12个纯检查执行通过；数据库比较仍待执行|
|A2两条完整链|tests/test_release_chains.py；docs/DEMO_ROUTES_RC1.md|7个真实服务链测试定义；手动浏览器路线，不是浏览器端到端通过|
|A3全局交互|static/release-ui.js/.css；templates/release/read_only.html；scripts/check_release_ui.py|7角色静态672断言，真实表单/键盘/无障碍仍待G3|
|B1源码与依赖|config/settings/base.py；UPDATE_MANIFEST.json；scripts/record_runtime.py|源码统一；依赖声明沿用，实际安装到G1记录|
|B2运行顺序|compose.rc.yaml；config/settings/course_demo.py；deployment/nginx.course.conf；scripts/rc_worker.py|独立本地实例；真实Docker启动待验收|
|B3副本升级与恢复|RC_WINDOWS.cmd；scripts/rc_config.py；rc_database_guard.py；rc_legacy_snapshot.sql；RC_WINDOWS_ACCEPTANCE.md|新副本/空库保护、部分旧记录比较；不操作原v0.7；真实恢复待G2|
|B4课程交付|docs/release_report/Report_R5_RC1.docx/.pdf、models、traceability.json|报告63页；38 SU+SF；19模型；逐页审查|

## 与先前原始需求的对应
老师要求的愿景、业务用例图、现状业务序列图、改进业务序列图、系统用例图、用例规约仍是主体。Docker和部署作为设计/验证材料，不取代分析主线。项目职责、字段和异常规则来自已有源码/增量规约；新修订在报告中说明。

## RC之后
G1空库依赖/迁移/框架回归 → G2旧合成数据副本升级与真正恢复 → G3两条真实角色路径和通知故障恢复 → G4目标公网。发现阻断缺陷留在冻结范围修正，不继续横向堆功能。
