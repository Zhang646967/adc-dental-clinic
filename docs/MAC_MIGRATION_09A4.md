# ADC：Windows → macOS 开发迁移准备与下一阶段计划

候选程序：**v0.9.0-alpha.4**。父版本：v0.9.0-alpha.3。报告仍为 R4.4。
最近确认的运行实例仍为 Windows 上的 v0.7。本文件没有把候选源码、隔离测试或备份生成等同于已经迁移成功。

## 1. 本轮决策：先建立可恢复的开发基线

目标不是把旧电脑原样复制成一台虚拟 Windows，也不是为 macOS 重写业务系统。
保留 Django/PostgreSQL 和现有业务规则，把主机差异限制在开发入口、路径、文件编码及运行依赖。
本轮新增跨平台工具、Mac 隔离验证入口及测试；没有更改业务模型、旧13份迁移、患者资料、预约、账单或授权规则。

下一步依次是：
1. Windows 只读盘点，保护实际运行源码和数据库。
2. 新候选在隔离环境跑真实数据库门槛，先修失败。
3. 以 v0.7 的真实本地数据库制作演练归档，在 Windows 或 Mac 的新临时库恢复比较。
4. Mac 上先核对旧版本的恢复实例，再在副本中升级新候选；把“换主机”和“改业务版本”分成两次检查。
5. 通过后择时停写、重新导出最终归档、正式交接。Windows 保留为回退副本，不双端继续录入。
6. 迁移基线稳定后，继续最小诊所／牙医／资格维护，再考虑出诊变更和业务交接；统一资源、通知与优化排程排在其后。

## 2. 迁移四类对象，而不是只搬文件夹

| 对象 | 应如何处理 | 不应做什么 |
|---|---|---|
| 实际运行源码及个人改动 | 保存私密完整副本；工具另导出版本清单声明的文件、实际字节指纹及未列入文件名单 | 不用新版干净 ZIP 覆盖仍未保存的本地改动 |
| PostgreSQL 数据 | `pg_dump` 自定义归档；新库 `pg_restore`；前后逐表及结构比较 | 不把源命名卷、PGDATA 或 Docker.raw 作为本次跨架构移植方法 |
| 配置与密钥 | 源 `.env` 私密离线保管；Mac 重新建立本地环境，优先使用新应用密钥和新数据库密码；AI 默认关闭/本地模式 | 不提交 Git，不发聊天，不复制浏览器会话，不把示例凭据当正式密钥 |
| 报告、模型、验收记录 | 单独完整归档，保留可读的 R4.4 与源码版本关系 | 不把报告版号当应用版本；不因为本轮迁移改动再次重排报告 |

另外保存 `.local_credentials*` 等账号交接材料（若存在），放在加密的私人位置。数据库里的应用密码哈希不同于数据库角色密码；恢复原数据并不意味着必须重置所有演示账号。更换应用密钥后需要重新登录，旧签名表单／旧会话不应继续使用。

**数据库归档不是无敏感信息的测试日志**：其中包含密码哈希、会话、地址和业务记录。工具生成的传输目录没有加密；目录权限只提供本机保护，在 Windows 上还需核对 ACL。用可信的私密加密介质/传输方式，不能上传聊天或公共仓库。文件名过滤也不能保证代码中没有硬编码密钥。

## 3. Mac 环境方案与未知项

你的 Mac 芯片类型和 macOS 版本尚未确认。本轮不假定 Intel，也不假定某一代 Apple Silicon。
Docker 官方分别提供 Intel 与 Apple Silicon 安装包；选择与你实际芯片匹配的版本。[O1]

应用仍在 Linux 容器内运行。Dockerfile 和 Compose 不固定 `linux/amd64`；在 ARM Mac 上优先拉取/构建原生 ARM 镜像，在 Intel Mac 上使用相应架构。仍需实际拉取、构建和运行验证依赖，不因为 Dockerfile 存在就认定两端均通过。[O2]

迁移时保持 PostgreSQL **17**，不同时升级到另一个主版本。保留现有 Python 3.13 容器基线及 requirements；宿主机不需要另装 Django、psycopg 或 PostgreSQL。

| 入口 | 宿主机依赖 |
|---|---|
| `VERIFY_ISOLATED_WINDOWS.cmd` | Docker Desktop；不需要宿主机 Python |
| `bash VERIFY_ISOLATED_MAC.sh` | Docker Desktop、系统 Bash；不需要宿主机 Python |
| `ADC_MIGRATION_WINDOWS.cmd ...` | 可正常执行的 Python 3.11+ 与 Docker |
| `bash ADC_MIGRATION_MAC.sh ...` | Python 3.11+ 与 Docker；其中 inspect 离线不需要 Docker |

没有 Python 时，先跑 Docker-only 的隔离验证；不要为了导出而绕过旧数据库的保护，也不要复制 Windows 的 `.venv` 到 Mac。

建议把开发目录放在本地 `~/Developer/adc` 等固定位置，而不是自动云同步文件夹。统一 UTF-8，脚本按 `.gitattributes` 管理：shell/Python 为 LF，CMD 为 CRLF。已有 Git 工作区先保存差异，再考虑规范换行，不能直接批量重写后丢掉真实修改。[O5]

`doctor` 记录宿主机与 Docker 引擎架构，但不读取账号密码。若宿主机显示 x86_64、Docker 显示 aarch64，需要核对终端是否在兼容转译模式，不能仅凭一项字符串认定芯片类型。

## 4. 现在在 Windows 做的事：只读预检

先将本次完整源码解压到**新目录**，不覆盖旧工程、不复制旧 `.env`。打开 Docker Desktop，在新目录 CMD 中运行：

```cmd
ADC_MIGRATION_WINDOWS.cmd doctor --out evidence\migration\windows-preflight.json
```

这只盘点环境，不连接数据库，不停止服务，不升级应用。如果提示宿主机 Python 不可用，不要重复使用原来损坏的 Python Launcher。可以先运行：

```cmd
VERIFY_ISOLATED_WINDOWS.cmd
```

其结果应对应本次新源码的 `gate-*.json`，不是之前版本的绿色记录。实际数据库测试在你本机运行前都处于待验证状态。

需要核对**实际旧源码**时，可从新目录调用：

```cmd
ADC_MIGRATION_WINDOWS.cmd doctor --source "D:\Users\Zhang\Desktop\ADC_engineering_v0.3" --out evidence\migration\windows-source-preflight.json
```

上面沿用之前的旧工程路径；若你已移动或重命名它，必须改为实际运行目录。工具支持原 v0.7 的 `CHECKSUMS.sha256` 格式，也支持新版 `UPDATE_MANIFEST.json` 中的文件清单，不要求先升级旧实例。

## 5. 演练归档：检查源数据库身份后再执行

以下是准备好了才执行的步骤，不与预检自动连跑。

在**原工程目录**查看：

```cmd
docker compose ps
docker compose ps -q db
```

确认这是你正在使用的 ADC 实例，将第二条得到的数据库容器 ID 用作 `--db`，不要猜测名称。工具只接受显式 ID，并核验本地 Docker context、db 服务标签、ADC 必需表和 PostgreSQL 17。

从新工具目录执行，替换尖括号占位符：

```cmd
ADC_MIGRATION_WINDOWS.cmd export --source "<原工程绝对路径>" --db <原数据库容器ID> --out "D:\ADC_Private_Transfer\rehearsal-001" --confirm-private-data
```

要求输出目录在源码目录之外、且尚不存在。失败保留 `INCOMPLETE` 标记和部分文件，不可以恢复或误当成功。

成功目录包含：

```text
rehearsal-001/
├─ database.dump         数据库自定义归档（私密，未加密）
├─ db_snapshot.json      同一快照的逐表行数、比较摘要及结构信息
├─ source.zip            清单声明的源码，保留这些文件的本地修改
├─ source_manifest.json  实际文件指纹、版本和未列入文件名单
└─ manifest.json         格式、来源、SHA-256、模式；不声称已经恢复
```

工具会持有 PostgreSQL 的只读可重复读事务，导出快照，使数据比较清单和 `pg_dump --snapshot` 使用同一快照。不是先查一份行数、过一会儿再独立备份。[O3]

逻辑归档不包含整个集群的数据库角色；恢复演练使用新的临时所有者，并不复制生产权限。正式环境的运行账号／迁移账号需要分别建立和核验。

这仍消耗数据库连接、读取锁、CPU和磁盘，运行时不要同时改变表结构。在线演练归档只反映快照时点，**不包含导出后 Windows 新增的数据**。序列计数器不属于 MVCC 快照比较；正式交接前必须停写并重导，之后还需核对新建记录的序号行为。

源码包不复制 `.env`、Git 历史、媒体及未列入版本清单的文件。未列入文件会登记供人工处理。另行保留完整私密工作副本；不要把 source.zip 当作已经备份了整个电脑或全部项目资产。

## 6. Mac 就绪后：先验证工具与归档

将新源码和私密传输目录放在各自独立位置，确认 Docker Desktop 安装包匹配芯片。新源码目录执行：

```bash
bash VERIFY_ISOLATED_MAC.sh
bash ADC_MIGRATION_MAC.sh doctor --out evidence/migration/mac-preflight.json
```

Mac 验证脚本在启动项目服务前，先用无网络、无 Docker socket 的辅助容器核对配置和源码清单。随后只运行随机命名的临时验证项目，不使用旧应用 `.env`，不挂载旧数据库卷，不开放网络端口。

再核验私人归档（此操作只检查文件，不启动数据库）：

```bash
bash ADC_MIGRATION_MAC.sh inspect --bundle "/Users/你的账户/PrivateTransfer/rehearsal-001"
```

`checksums_and_structure_passed=true` 不代表数据库恢复通过。备份和 manifest 都被一同修改时，SHA-256 不能证明发送者身份；不要从不可信来源取归档。[O4]

## 7. 真正的恢复演练：只在全新临时库内进行

```bash
bash ADC_MIGRATION_MAC.sh rehearse \
  --bundle "/Users/你的账户/PrivateTransfer/rehearsal-001" \
  --out evidence/migration/mac-restore-001.json \
  --confirm-trusted-backup
```

工具只创建一个带随机名称和拥有者标签的 PostgreSQL 17 容器：不连接任何网络、不开放端口、不挂载旧数据、数据放临时文件系统。只从可信归档恢复，使用单事务和遇错停止；对比逐表行数、行内容摘要、列定义、约束、索引、触发器、自定义函数和扩展。最后只清理自己创建且标签吻合的容器。[O4]

比较摘要用于发现恢复差异，不是隐私匿名化，也不是对恶意数据库内容的证明。工具不支持分区表、外部表、物化视图、非public业务表或大对象；遇到这些情况明确停止，需重新评审，不默默漏掉。

`all_rehearsal_checks_passed=true` 仅表示本次归档恢复、所列比较和清理均成功。JSON绑定归档指纹和源／目标架构。
**它不表示已建立长期使用的 Mac 应用数据库，不运行 Web 页面，也不会留下供开发使用的这座临时库。**新持久开发实例的创建、权限配置及正式切换将在下一步单独执行。

## 8. 正式切换的放行清单

全部满足才停用 Windows 日常录入：

- 新候选真实数据库验证和浏览器主流程通过，失败先处理。
- 在 Mac 上恢复旧版本副本，核对患者、账号绑定、预约历史、已发布账单、中文、金额与北京时间。
- 新增候选在恢复副本中升级并验证；R4.4及SU-26未验证标记不得仅凭启动成功删除。
- 保留旧源码、旧 `.env`、账号交接材料和完整数据库归档。未完成任何恢复时不要删 Windows 数据。
- 正式停写时人工停止原 web 及其他写入进程，禁止直接数据库改写；选一个交接时点。
- 用新的输出目录进行 `export ... --cutover --confirm-writers-stopped --confirm-private-data`。工具会额外拒绝同一项目还有其他运行服务的情况，但无法证明没有另开的数据库客户端，所以仍需要人工管理冻结。
- 最终归档再次校验和恢复，建立新的独立持久数据库／本地配置；不复用演练临时库，不在导入数据后执行 seed_demo 重建演示用户。
- 建立 Mac 固定 Compose 项目名（例如 `adc_mac_dev`）并始终显式使用；目录改名不应让你意外连接另一座空库。[O6]
- 不允许 Windows 与 Mac 同时继续录入同一业务。Mac已产生新记录后若要回退，须先停写、备份Mac新数据并处理差异，不能直接恢复旧Windows快照丢掉新记录。

重新生成应用密钥会使旧会话和签名表单失效；需要重新登录，这是迁移后的预期。不要为了让旧页面还能提交而复制会话或改安全校验。

随着真实时间流逝，旧候补窗口或邀约可能已经过期。**不能篡改历史时间来制造“迁移成功”的演示效果**；另外新建未来时段测试办理能力。

## 9. 验证层次和本轮边界

本轮在 Linux x86_64 执行纯规则、文件打包、模拟 Docker 编排和脚本语法检查。没有实际 Windows 或 Mac Docker引擎，没有真正导出／恢复你的数据库，也没有完成 ARM 原生构建。

425项基础测试方法通过，其中53项是迁移工具的纯规则／模拟编排检查。其输入包括不合法路径、大小写／Unicode冲突、旧v0.7清单、原目录修改、被损坏归档、错误容器身份、未停写切换、恢复失败和错误清理标签。计数不是业务覆盖率。

真实数据库测试仍为既有344项、待执行。本轮不新增业务表，不变更13份原迁移，不把未执行测试改成通过。

## 10. 与课程知识的对应

课件将业务建模、需求、分析和设计分层。Mac是本轮的开发环境／设计约束变化，不应被强行画成新增业务执行者；患者预约、治疗和结算的业务目标不因此改变。参见《系统分析与设计-精简2026-9》第5、19、143—144页。

note__5第4、7—10页强调关注点分离、隐藏易变决定及机器依赖。这个增量的做法是把操作系统差异限制在入口脚本，把迁移规则放在独立工具内，不把操作系统分支写进预约、结算或权限判断。

测试讲义强调有效／无效输入、正确结果和不应出现的副作用。因而“生成dump”“恢复可读”“数据与结构相符”“应用业务通过”“完成切换”分别取证，不把某个文件存在当作后续全部通过。

```text
迁移准备
├─ 不变：业务规则、历史、账号关系、北京时间
├─ 可变：主机、CPU架构、Shell、路径、本地凭据
├─ 工具：doctor → export → inspect → rehearse
├─ 验证：文件／数据库／应用／实际切换分别取证
└─ 放行：单端写入、可恢复、可回退，再继续业务开发
```

## 官方技术依据（与课程材料区分）

- [O1] Docker Desktop for Mac：Intel／Apple silicon安装入口。https://docs.docker.com/desktop/setup/install/mac-install/
- [O2] Docker Multi-platform builds：平台变体、原生与仿真。https://docs.docker.com/build/building/multi-platform/
- [O3] PostgreSQL 17 pg_dump及快照同步函数：逻辑归档、跨架构及导出快照。https://www.postgresql.org/docs/17/app-pgdump.html ；https://www.postgresql.org/docs/17/functions-admin.html
- [O4] PostgreSQL 17 pg_restore：可信归档、退出策略和单事务。https://www.postgresql.org/docs/17/app-pgrestore.html
- [O5] Git gitattributes：文本文件换行约定。https://git-scm.com/docs/gitattributes
- [O6] Docker Compose project name：隔离及名称优先级。https://docs.docker.com/compose/how-tos/project-name/

本轮查阅日期：2026-10-08。官方文档支持技术机制，不证明ADC实现已在目标Mac上通过。
