# ADC 1.0.0-rc.1：Windows集中验收与数据副本启动

状态：候选功能冻结，开始真实环境验证。不是正式上线或医疗软件认证。
本轮代码从完整alpha.10重建；上次中断只留下图像，未把这些图像认作已保存代码。
旧运行实例仍最后确认为v0.7；Mac迁移暂停。

## 0. 三个入口，绝不混用

|入口|数据库与影响|凭据|
|---|---|---|
|`RC_WINDOWS.cmd verify`|临时独立PG库，全部框架与回归检查，测试后清理本次项目|固定合成测试值，仅在临时配置|
|`RC_WINDOWS.cmd new-demo --synthetic-empty-only`|随机RC项目的新持久库；第一次初始化合成演示|随机生成，保存在`.rc/private/demo-credentials.txt`|
|`RC_WINDOWS.cmd import-copy --trusted-synthetic-copy`|只将可信合成备份恢复到全新RC库，再应用迁移；不连接旧实例|保留原应用密码哈希，应用签名密钥换新；旧会话失效|

不直接覆盖旧v0.7。源码累计包只能应用到**另建的源码副本**。本包历史原地升级CMD入口已改为拒绝执行，原文归档在docs/history/legacy_scripts。
新的RC脚本不提供删除卷、覆盖数据库、自动降级、重置所有密码或操作旧实例的命令。

## 1. 先运行G1

将完整包解压到新目录；不复制旧`.env`、账号文件和数据库卷。启动Docker Desktop本地Linux引擎，在新目录CMD执行：

```cmd
RC_WINDOWS.cmd verify
```

这个入口使用独立`compose.verify.yaml`、临时数据库、无数据库端口和旧数据卷；宿主机不需要Python。验证镜像安装与演示相同的requirements-production.txt声明。网络下载、Docker构建、依赖解析仍须在实际主机发生。

必须核对本次`evidence/verification/gate-*.json`、对应log以及清理结果。步骤包括源码清单、基础检查、实际安装版本记录、Django check、迁移差异、临时库迁移及全部tests。`all_gates_passed=true`只适用于这些检查，不含公网、完整浏览器操作和备份恢复。

发生任何失败：保存首个错误，不跳过权限/事务断言，不使用SQLite，不删除旧卷。只发送合成日志；不要发送`.env`、`.rc`、密码、归档或患者资料。

## 2. 新建演示（与导入二选一）

```cmd
RC_WINDOWS.cmd prepare
RC_WINDOWS.cmd new-demo --synthetic-empty-only
RC_WINDOWS.cmd start
RC_WINDOWS.cmd status
```

`prepare`只在新解压目录创建`.rc/compose.env`及随机项目名；不覆盖已有配置。默认入口`http://127.0.0.1:18000`，不同于旧实例8000。需要改端口时，在首次start前本地修改`.rc/compose.env`的RC_WEB_PORT。

`new-demo`先拒绝已有RC数据卷，再执行模式准备和显式合成初始化。账号密码只在私密本地文件中。初始化回执不明确时，不重新创建账号或重置密码；先核查RC项目数据和私密文件。

初始化包括原seed_demo、seed_portal_demo和seed_workspace_demo三个已有命令，但不在每次启动运行。导入旧数据的路径绝不运行它们。

## 3. 可信v0.7副本导入（与新建演示二选一）

先另行保护旧源码、配置和账号交接资料。对**准确确认的原项目**保存可信的PostgreSQL自定义归档。旧v0.7代码不认识暂停、任务和通知模型；正式切换时必须停止所有原写入端，包括可能单独启动的worker或脚本。

以下源端动作需要人工确认项目，RC脚本不会替你执行：

```cmd
rem 在原工程目录确认项目及所有运行服务
 docker compose ps
rem 演练可选静态快照；最终交接必须停止所有写入端后重新导出
 docker compose stop
 docker compose up -d db
rem 选择一个全新文件名；不要覆盖已有备份
 docker compose exec -T db sh -c "pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc" > D:\ADC_Private\v07-final-unique.dump
```

确认没有在其他Compose文件、项目或终端运行的写入程序。数据库卷不删除。旧配置和归档都私密保存，不能上传聊天或公共仓库。停止源端是最终单端交接措施；演练副本与源端之间不会自动同步。

在**新的RC目录**运行prepare，将归档手动复制为`.rc/private/source.dump`，然后：

```cmd
RC_WINDOWS.cmd import-copy --trusted-synthetic-copy
RC_WINDOWS.cmd start
```

导入只能进入从未存在过的随机RC数据卷，先验证public模式无业务表；使用`pg_restore --single-transaction --exit-on-error --no-owner --no-privileges`。不执行旧owner角色DDL，不连接源库。只恢复你自己可信的合成演示归档；SQL归档可能包含可执行数据库定义，哈希不是来源认证。

恢复后、迁移前后各生成legacy summary并逐字节比较。范围包括账号标识/密码哈希、患者、预约、逻辑账单、版本金额、候补/邀约和审计；这些摘要仍属于私密数据。比较使用固定UTC/日期格式，MD5仅用于此处已可信输入的逐行差异检测，不作为密码安全或来源保证。

这不是跨库全字段完整性证明。G2还应人工核对资格、诊所与牙医目录、成本清单、账号权限，并使用已有migration_tool的完整恢复比较工具按原说明在隔离环境演练。列举归档目录不等于恢复成功。

若restore/schema/比较失败，脚本停止，不创建READY标志、不启动Web/worker；保留新RC项目和所有记录。不能将一次失败重试到同一已写入数据库。本轮不提供自动销毁/回滚；需诊断或换一个全新的RC目录与随机项目重做。

## 4. Web与worker启动顺序

`db健康 → schema一次性migrate/collectstatic/check成功 → Gunicorn Web/通知worker → 本地Nginx入口`。
`compose.rc.yaml`采用JSON兼容的YAML，方便标准库检查配置，不引入PyYAML运行依赖。
数据库无宿主机映射端口；Web无直接宿主机端口；Nginx仅映射本机回环地址。网络internal，默认无外部AI请求。模型字段和旧应用迁移从alpha.10保持原字节。

```cmd
RC_WINDOWS.cmd stop
RC_WINDOWS.cmd start
RC_WINDOWS.cmd status
```

start不会初始化账号，也不恢复备份。worker最多按on-failure重启3次；超过后会停止，需要检查。派发状态不是进程健康证明。

只读检查：先stop，在本地`.rc/compose.env`设`RC_READ_ONLY=1`，再start。Web可读，业务写拒绝，worker入口正常退出而不派发。恢复可写同样先stop再明确改为0。配置值不是数据隔离或权限测试的替代。

## 5. G3与回退

执行DEMO_ROUTES_RC1.md两条主链以及手机/大字/键盘、撤权、跨店、旧标签与重复提交。真实验收填写RC_ACCEPTANCE_RECORD.json；其初始值均为NOT_RUN。

正式切换前保留原项目及私密备份。若新RC尚未产生需要保留的数据，可停止RC后恢复原实例；若RC已新增数据，必须先保存并处理差异，不允许直接丢弃后回旧快照。不得让旧应用写入新的RC数据库。

本RC本地配置使用数据库owner方便课程验证，不是最小权限生产配置。公网另用生产配置、独立运行/迁移角色、真实域名/HTTPS、备份和后台监控验收；不得把18000端口转发到公网代替G4。

## 技术机制依据

Docker Compose启动依赖：https://docs.docker.com/compose/how-tos/startup-order/
Django迁移与事务测试：https://docs.djangoproject.com/en/5.2/topics/testing/tools/
PostgreSQL归档恢复：https://www.postgresql.org/docs/17/app-pgrestore.html
机制支持设计选择，不证明本应用已运行。查阅2026-10-09。
