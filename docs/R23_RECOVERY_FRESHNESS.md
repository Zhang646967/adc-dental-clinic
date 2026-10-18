# R2.3 恢复点新鲜度

原始备份时点 → 生成凭据 → 下载及解密验证 → 独立恢复比对 → 可用恢复点。本轮是 **R2.3 第一批运维工具**；完整 R2.3 仍在进行。没有新增业务模型、权限、通知、公共指标接口或自动桌面任务。

## 已实现的第一批

| 业务问题 | 工具行为与失败响应 | 验证 |
|---|---|---|
| 昨日备份今天又下载，看起来像新数据 | 分开保存原始 `created_at` 和本次 `verified_at`，26小时后告警；重新验证不刷新恢复点 | 固定时钟、旧包再次下载、真实 age 演练 |
| 后一个文件失败，前一个记录已推进 | 全批次先暂存、检查外层摘要、用当前密钥认证解密、核对内部摘要及来源，全部通过才安装/更新记录并保留30个UTC日 | 后项损坏、传输中断、错误密钥；失败不清理旧备份 |
| 外层记录改了时间或应用版本 | 备份时点与加密包内清单绑定；检查同诊所实例、提交和镜像。原始恢复点不能靠修改外层JSON刷新 | 伪造时间、错误实例/提交/镜像、同一时点冲突 |
| 本机有旧监测记录，误认为服务器仍有新备份 | Mac上的服务器观察超过90秒为UNKNOWN；下载验证和服务器观察分别展示 | 失效时间边界和损坏记录 |
| 替换密钥后，缓存文件仍显示可恢复 | 每次同步重新用当前密钥解密所有本次清单文件；状态读取核对当时密钥摘要与当前私有文件 | 缓存、换钥匙、损坏密文的真实认证拒绝 |
| 恢复没有执行，却显示成功 | 第三个 `restored` 状态保留UNKNOWN；本轮不接受恢复成功凭据 | 强制拒绝伪造恢复记录，整体返回退出码3 |

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

以上为格式示例，不是当前Mac实例或云端验收记录。退出码0/1/2/3分别代表HEALTHY/WARNING/CRITICAL/UNKNOWN；当前独立恢复尚未集成，整体码正常为3，必须逐项读取。原R2.2六项服务监测独立运行，不因该保留门槛改变。

## 下一批与完成门槛

R2.3第二批将把独立空数据库恢复和全业务事实比对接入正式恢复命令：绑定源密文、提交/镜像、原始时点、目标身份及耗时；比对账号、授权、金额、凭据版本、CSV原字节和匹配历史，成功后才能产生恢复凭据。还需验证恢复8天阈值、较新下载未恢复、更新后的私有观测备份及恢复。保留已有30分钟目标、7个服务器UTC日/30个Mac UTC日规则。

本轮未重复R2.2业务浏览器演练、30分钟容量或24小时观察；未在云端执行SSH和异地保护。服务器尚未购买，Windows原始数据恢复仍未解决。Mac睡眠或离线时，异地恢复点仍只能取最后一次验证通过的下载。

[第一批执行证据](evidence_r23/README.md) · [需求至测试](evidence_r23/requirement_trace.json) · [R2完整计划](R2_OPERATIONAL_ASSURANCE_PLAN.md) · [课程报告](../课程报告/README.md)
