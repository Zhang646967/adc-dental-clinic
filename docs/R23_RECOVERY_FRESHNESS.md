# R2.3 恢复点新鲜度

原始备份时点 → 生成凭据 → 下载及解密验证 → 独立恢复比对 → 可用恢复点。第二批接入正式恢复命令；R2.4长时运行及公网验收分别取证。没有新增业务模型、权限、通知、公共指标接口或自动桌面任务。

## 已实现的第一批

| 业务问题 | 工具行为与失败响应 | 验证 |
|---|---|---|
| 昨日备份今天又下载，看起来像新数据 | 分开保存原始 `created_at` 和本次 `verified_at`，26小时后告警；重新验证不刷新恢复点 | 固定时钟、旧包再次下载、真实 age 演练 |
| 后一个文件失败，前一个记录已推进 | 全批次先暂存、检查外层摘要、用当前密钥认证解密、核对内部摘要及来源，全部通过才安装/更新记录并保留30个UTC日 | 后项损坏、传输中断、错误密钥；失败不清理旧备份 |
| 外层记录改了时间或应用版本 | 备份时点与加密包内清单绑定；检查同诊所实例、提交和镜像。原始恢复点不能靠修改外层JSON刷新 | 伪造时间、错误实例/提交/镜像、同一时点冲突 |
| 本机有旧监测记录，误认为服务器仍有新备份 | Mac上的服务器观察超过90秒为UNKNOWN；下载验证和服务器观察分别展示 | 失效时间边界和损坏记录 |
| 替换密钥后，缓存文件仍显示可恢复 | 每次同步重新用当前密钥解密所有本次清单文件；状态读取核对当时密钥摘要与当前私有文件 | 缓存、换钥匙、损坏密文的真实认证拒绝 |
| 恢复没有执行，却显示成功 | 第一批将 `restored` 保留UNKNOWN；第二批只有认证解密、独立空库恢复及全事实比对后才记录 | 缺失比对、错误目标、超时及异常恢复拒绝；无记录仍为UNKNOWN |

`scripts/recovery_receipts.py` 使用私有0700目录、0600文件、原子替换与独占锁；复用R2.2的有界存储。每个实例保留三种最新状态及最多96条观察历史，裁剪数量明确记录。校验摘要检测损坏，不提供对私有主机拥有者的防伪证明。密钥摘要只在私有记录中保存，密钥内容不进入记录或仓库。

新备份在开始导出前记录UTC时点。实际数据库快照稍后形成，因此这个时点给出保守的数据年龄；不声称它是精确的数据库快照时间。历史包仍可解密、查看和按原规则恢复；缺少此时点约定的历史清单不会被补造为已验证的新恢复点。原始密文和业务事实不改写。

## 私有操作

独立HTTPS课程部署继续使用已有 `g4_course.py backup` 和 `g4_remote.py sync` 命令，成功后分别生成凭据。新增状态入口：

```sh
python scripts/g4_course.py --output /private/course/.g4 --context default recovery-status
python scripts/g4_remote.py --output /private/course/.g4 --ssh-config /private/ssh.json recovery-status --destination /private/mac-backups --identity-file /private/identity.txt
```

也可脱离Docker和SSH读取已配置的私有记录：

```sh
python scripts/recovery_receipts.py --directory /private/mac-backups/recovery --archives /private/mac-backups --instance adc_g4_012345abcdef --source 0123456789abcdef0123456789abcdef01234567 --image sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef --mode mac --identity-file /private/identity.txt
```

以上为格式示例，不是当前Mac实例或云端验收记录。退出码0/1/2/3分别代表HEALTHY/WARNING/CRITICAL/UNKNOWN；必须逐项读取。服务器只能证明生成，Mac分别记录下载与恢复，未配置的原RC演示继续UNKNOWN。原R2.2六项服务监测独立运行。

## 第二批恢复合同

新归档为格式2，旧格式1仍可读取/恢复，缺少快照事实的旧包不补造已验证凭据。`recovery_facts.py` 在只读、可重复读事务中保护表定义、逐表生成行数、内容和结构摘要，并保持导出的快照存活；`pg_dump --snapshot` 使用同一快照。因此并发提交不会使导出与清单看到不同业务事实。[PostgreSQL快照合同](https://www.postgresql.org/docs/17/functions-admin.html#FUNCTIONS-SNAPSHOT-SYNCHRONIZATION)、[pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html)。

解密后只接受未压缩tar、最多14个平面常规文件；读取目录项时即执行数量上限，拒绝压缩封装、重复名称、链接及越界路径，不先加载不受限的完整目录列表。

比对覆盖所有public业务表、Django关联表、迁移记录及会话；账号、诊所授权、金额、凭据版本、CSV原字节、标准化流水和匹配历史均参与内容摘要。bytea按数据库真实字节编码进入摘要，重复行也影响结果，不使用Python对象地址。表结构包含列、缺省值、约束和索引；出现不支持的业务schema、分区/外部表或超出256表/单表100万行边界时拒绝部分验收。此边界是课程工具保护限制，不是大型系统容量证明。

恢复同时验证匹配的应用提交/镜像、PG17、显式本地Unix Docker端点、目标容器/卷的项目标签。源与目标必须是不同实例和不同卷；目标已有表或任一应用进程运行即拒绝。单事务导入后运行维护检查，再用同一版本的读器比对；通过前不启动网站、worker或监测进程。环境就绪后的恢复、比对和启动计时须在30分钟内。

只有持有Mac当前密钥并认证源密文的 `restore` 或经固定SSH主机传输的Mac恢复流程，才能记录源实例的恢复凭据。凭据保存在原下载目录的 `recovery/`，绑定密文摘要、原始时点、来源应用、密钥摘要、目标容器/卷身份、全表事实摘要和耗时。`restore-verified-dump` 单独执行只返回比对材料，不会替Mac证明解密或生成凭据；没有人工盖章接口。

```sh
python scripts/g4_course.py --output /private/new-target/.g4 --context default restore --backup-file /private/mac-backups/backup-ORIGINAL-NAME.tar.age --identity-file /private/identity.txt --trusted-synthetic-copy
```

路径须对应按原文件名保存的真实备份和全新、匹配应用版本的目标bundle；示例中的占位文件名不能直接执行。云端恢复仍由既有 `g4_remote.py publish --restore-backup ...` 进行，私钥不上传。

恢复新鲜度按**已恢复包的原始数据时点**计算，超过8天为WARNING；较新下载尚未恢复时为WARNING，不能用旧演练声称覆盖新数据。版本、当前密钥或密文不符为UNKNOWN。重复演练和重新下载都不刷新原时点。保留7个服务器UTC日、30个Mac UTC日和96条私有观察历史规则。

格式2还加密保留五个有界私有监测历史文件（缺失明确记录）。恢复到目标的 `private/recovered-observations.json`，核对字节摘要，作为历史材料；不覆盖新目标的实时卷。监测文件独立于数据库快照采集，不能据此声称跨文件/数据库同一时刻。新环境必须产生自身身份、时钟与新样本，才能判断实时健康。

本轮不重启原Mac业务服务。未重复R2.2业务浏览器演练、30分钟容量或24小时观察；未在云端执行SSH和异地保护。服务器尚未购买，Windows原始数据恢复仍未解决。Mac睡眠或离线时，异地恢复点仍只能取最后一次验证通过的下载。

[第一批执行证据](evidence_r23/README.md) · [需求至测试](evidence_r23/requirement_trace.json) · [R2完整计划](R2_OPERATIONAL_ASSURANCE_PLAN.md) · [课程报告](../课程报告/README.md)
