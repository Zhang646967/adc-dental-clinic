# ADC 1.0.0-rc.1 — 课程发布候选

**功能范围冻结，开始集中验收；不是已经验证通过的正式版。** 父版本alpha.10，合并批次A/B。最后确认的用户运行实例仍为Windows v0.7；没有操作它。Mac迁移暂停。

## 从这里开始

1. 完整包解压到新目录，不复制旧`.env`、账号文件或数据库卷。
2. 启动Docker Desktop的本地Linux引擎，在新目录CMD运行 **`RC_WINDOWS.cmd verify`**。
3. 保存本次`evidence/verification/gate-*.json`与日志，检查全部步骤及清理结果。失败先修，不直接进入升级。
4. G1通过后阅读 `docs/RC_WINDOWS_ACCEPTANCE.md`，选择全新合成演示或旧合成数据副本导入；两个入口都不覆盖原v0.7。

入口：`RC_WINDOWS.cmd prepare`、`new-demo --synthetic-empty-only`、`import-copy --trusted-synthetic-copy`、`start`、`stop`、`status`。
新演示完成后先本地查看`.rc/private/demo-credentials.txt`。不要发送该文件、`.rc/compose.env`或数据库备份。默认网关仅绑定127.0.0.1:18000；不是公网HTTPS配置。

## 批次A

- `tests/data/release_oracles.json`：固定合成输入与独立预期；逐行舍入、成本和收入粒度、缺失/零、当前账单版本、取消率分母及UTC+8季度边界。
- `checks/test_release_oracles.py`：独立整数参考核算及生产纯规则比较。
- `tests/test_release_chains.py`：两条跨模块真实PostgreSQL服务链的7个测试定义，尚未执行。
- `docs/DEMO_ROUTES_RC1.md`：对应浏览器手动演示路线；不是浏览器自动化通过记录。
- `static/release-ui.*`：全角色错误摘要、焦点定位、只读提示和帮助入口名称。

## 批次B

`compose.rc.yaml`为独立RC配置，不合并旧compose。DB健康→schema迁移/静态文件准备成功→Web和worker→本地网关。Web/worker使用非root镜像；临时验证容器特例以root导出合成证据，不代表非root运行已实机验收。

旧就地升级CMD入口已改为停止提示，原脚本留存`docs/history/legacy_scripts`。累计差异ZIP仅供源码归档/副本重组，不能解压覆盖运行中工程后直接当作完成升级。

## 冻结材料

- `RELEASE_CURRENT.md`：交付范围与当前限制。
- `docs/TEST_REPORT.md`、`docs/evidence_rc1`：本轮真实执行的开发检查。
- `docs/RC_ACCEPTANCE_RECORD.json`：G1—G4未运行记录模板。
- `docs/release_report/`：完整R5课程报告、38份用例的索引、19幅模型及源文件。
- `docs/RC_AB_DELIVERY.md`：A/B逐项对应文件。

原16份迁移和11份模型文件保持alpha.10原字节。本轮无新数据库模式，但从v0.7升级仍需要中间累计迁移，不能混跑旧写入端。固定requirements尚未实际解析安装，不宣称完整依赖锁；G1运行时记录实际安装版本。
