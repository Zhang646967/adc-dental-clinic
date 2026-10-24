# R2.4.1 主机事件与故障处置

明确实例 → 有限主机事件 → 故障认领 → 人工处置 → 新采样验证 → 保留关闭记录。

## 采集契约

`scripts/host_events.py` 在主机运行，只读取显式本地 Unix Docker context 中
指定 Compose project 的 db、web、gateway、notification-worker、operations。
应用容器的 `ADC_SOURCE_COMMIT` 必须与注册版本一致。维护和一次性容器不作为运行服务。
采集器不挂载 Docker socket 到应用、不读容器日志、完整环境变量、患者或资金明细，
不执行重启、业务重放或数据库写入。Docker 操作权限仍属于主机运维人员。

保留的字段是容器 ID、服务、镜像 ID、运行状态、退出码、OOM 标记、重启次数、
启动时间和健康检查状态；没有独立健康检查时记录 none，应用就绪仍由 R2.2 判断。
事件只保留停止、退出、启动、重启、OOM、移除、暂停、恢复的固定代码与时间。
同一容器启动时间、ID 或重启次数变化也能产生重启/重建提示。

| 情况 | 当前判断与后续动作 |
|---|---|
| 服务退出、不健康或暂停 | CRITICAL；检查相应依赖，只由人工处理目标服务 |
| 服务缺失或同名运行服务重复 | UNKNOWN；确认实例和部署状态 |
| OOM | CRITICAL；保留明确 OOM 原因，人工检查内存限额与负载 |
| 启停、重启或重建事件 | WARNING；新采样确认现状，人工确认变更原因 |
| Docker 不可达、版本不符或读取失败 | 采集条件 UNKNOWN；保留最后成功采样与原事件 |
| 读取时最后成功采样超过 90 秒或时钟矛盾 | 独立状态读取为 UNKNOWN，不刷新采样时间 |
| 采样间隔超过 90 秒或事件结果达 256 条 | 保留 COLLECTION_GAP，不能证明遗漏期间完整 |
| 已配置实例的加密备份失败 | 单独 BACKUP_FAILED；不覆盖最近已验证恢复点 |

Docker 只保留有限事件历史。因此采用 30 秒轮询、重叠查询与事件去重；间断和
饱和明确留痕，不能宣称无遗漏或 24 小时持续运行。
[Docker 官方事件说明](https://docs.docker.com/reference/cli/docker/system/events/)。

## 私有命令与处置流程

在项目目录使用 Python 3，仅需标准库。目录采用 0700、文件 0600、原子替换和
现有校验封装；文件校验用于识别损坏，不抵御拥有该目录的主机管理员。

```sh
python3 scripts/host_events.py --directory /private/path/host-events init \
  --project adc_explicit_instance --source FULL_APPLICATION_COMMIT \
  --context desktop-linux --docker /absolute/path/to/docker
python3 scripts/host_events.py --directory /private/path/host-events collect
python3 scripts/host_events.py --directory /private/path/host-events watch
python3 scripts/host_events.py --directory /private/path/host-events status
python3 scripts/host_events.py --directory /private/path/host-events history
```

`watch` 是显式前台进程，不自动安装开机任务；Mac 睡眠或进程停止后，独立状态
命令会发现过期。采集器单写锁避免两个进程重复采样。status 不依赖 Docker、数据库
或采集进程；返回 HEALTHY 0、WARNING 1、CRITICAL 2、UNKNOWN 3。

1. 查看 status 和 history，并结合原 `./RC_MACOS.sh operations` 六项应用状态定位影响。
2. 用私有操作员代号认领事件，不填姓名、联系方式、患者或业务内容。
3. 在原运维流程中处理目标服务，再记录固定处置代码；本工具不代为执行这些动作。
4. 至少两个新的健康主机采样后关闭。备份故障需要一次实际完成的加密备份。
   关闭时采集器自身也必须新鲜正常。认领、处置均不能刷新采样或解除故障。
5. 关闭后继续保留原原因、发生/认领/处置/关闭时间、责任代号；未关闭事件仍影响总状态。

```sh
python3 scripts/host_events.py --directory /private/path/host-events ack INCIDENT_ID --operator-code course_operator
python3 scripts/host_events.py --directory /private/path/host-events action INCIDENT_ID \
  --operator-code course_operator --action inspect_dependencies
python3 scripts/host_events.py --directory /private/path/host-events action INCIDENT_ID \
  --operator-code course_operator --action verify_health
python3 scripts/host_events.py --directory /private/path/host-events close INCIDENT_ID --operator-code course_operator
```

处置代码包括检查依赖、重启目标服务、审查内存限额、修复采集、重试备份、核对业务事实、
验证健康和确认观察缺口。事件发生时通知或资金请求的结果仍需核对原业务事实；不因
请求中断就重新收款、退款或重放任务。不清空观察文件来隐藏故障。

单文件最多保留 192 条事件、64 个事件单及每单有限处置代码；只裁剪已关闭事件单，
显示裁剪计数。这是运维记录，不是不可篡改的财务审计。旧记录先加密归档，再为新版本
建立独立目录；不覆盖旧目标身份。主机记录保存在私有目录，受控交付时另行加密备份。

## 与备份衔接及范围

独立 G4 实例可将目录配置为 `BUNDLE/private/host-events`；原有 `Course.backup`
在加密备份实际成功或失败后记录有限结果，未配置则保持原行为。记录失败会在成功
返回中标记 host_event=UNAVAILABLE，不能丢弃已完成备份。状态与 R2.3 的创建、下载、
独立恢复凭据分别保留；BACKUP_COMPLETED 不表示异地下载或独立恢复已完成。

本轮不增加数据库迁移、业务角色、公开监测页面或外部通知。R2.4.2 的真实业务依赖演练、
R2.4.3 的等效容量复测、R2.4.4 的连续 24 小时与安全评估，以及云端验收仍分别执行。
[本轮执行证据](evidence_r241/README.md)。
## 2026-10-24 safe collection diagnostics

New collection failures retain a fixed stage (`context`, `ps`, `inspect`,
`events` or `projection`) and category (`TIMEOUT`, `EXIT_FAILURE`,
`COMMAND_UNAVAILABLE`, `OUTPUT_BOUND` or `INVALID_PROJECTION`). No command
arguments, stdout, stderr, environment values or clinical data enter the journal.
`last_collection_failure` is historical and carries its own timestamp; it is not
a current failure flag. A recovered sample leaves the original UNKNOWN incident
open until attributed disposition and two fresh healthy samples permit closure.
Changed failure categories remain visible; repeated identical polling failures
do not flood the retained event ring. Older journals without this field remain
readable, and missing old diagnostics must not be reconstructed as a known cause.

The C1.2 post-update gap was retained and disposed after independent dependency
checks and two fresh healthy samples. Its root cause remains undetermined.
The diagnostic improvement does not retrospectively explain that event or
establish continuous operation. See [executed evidence](evidence_c12/release.json)
for the application release and separate diagnostic installation status.
