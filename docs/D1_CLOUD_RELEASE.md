# D1 独立云端上线与商用交付准备

完整课程资料 → 确定版本 → 独立HTTPS → 微信体验 → 可恢复交付。

本阶段采用商用工程要求建设课程上线版。业务数据为合成资料；真实微信身份与业务资料来源分别管理。预算为服务器及备份约100元/月，独立域名另计。真实诊所试运营、C3签署归档、C4处方及C5耗材按后续业务合同推进。

## 目标环境

腾讯云广州、Ubuntu24.04 amd64、2核4GB、约90GB SSD。以购买页实际价格、续费、流量及备案条件核对预算，不自动购买资源。独立域名实名与内地网站备案完成后开放，教师小程序使用备案和平台权限核验后的体验渠道。手机预览、体验版、公众正式发布分别记录。

应用继续使用Django、PostgreSQL17及既有通知/监测进程。数据库不开放公网；镜像按提交与摘要固定，维护owner和runtime账号分离。小规格配置给数据库768MiB、Web1536MiB、通知256MiB、监测及网关各128MiB上限；这是待目标服务器验证的运行配置，不是云端容量证明。

## 准备与首次发布

在私有目录创建新包，旧实例不被覆盖。所有占位符必须替换为已核对的实际值。

```sh
python3 scripts/g4_course.py --context desktop-linux build --artifacts /PRIVATE/build-amd64
python3 scripts/g4_prepare.py prepare --output /PRIVATE/cloud/.g4 \
  --mode direct_tls --access-mode course-writable --dataset course-20 \
  --bind-ip 0.0.0.0 --host YOUR_OWNED_HOSTNAME --architecture amd64 \
  --source-commit FULL_TESTED_COMMIT --app-image PINNED_APP_IMAGE \
  --db-image postgres:17@sha256:VERIFIED_AMD64_DIGEST \
  --nginx-image nginx:stable-alpine@sha256:VERIFIED_AMD64_DIGEST
python3 scripts/g4_remote.py --ssh-config /PRIVATE/ssh.json --output /PRIVATE/cloud/.g4 \
  publish --artifacts /PRIVATE/build-amd64 --recipient-file /PRIVATE/backup-key/recipient.txt
```

`course-20`显式启用八城二十店初始化：已有目录、医师本人资料及主管采用、前台排班、物理资源、四类基础服务、监护代约示例均通过既有业务命令准备。账号密码随机生成并仅重定向到私有交付文件；不复制联调库、不导入测试预约、不制造治疗或资金事实。成功后再次执行只返回原完成结果，既有密码不变。中断初始化保留已提交的审计和私有凭据，由操作人员核对后继续维护，不批量重置。

新部署的临床资料为合成，但认证模式为`live`：未提供AppSecret时，真实微信保持未配置，原账号登录可用，不在页面显示模拟验证码。微信、短信资料通过私有环境文件配置，不能放入镜像、小程序、Git或课程报告。沿用WX1免费额度核验与最多10条约定号码短信测试限制。

## 升级与回退

在同一个`.g4`和Docker项目中更新应用；数据库卷、主机名、密钥、账号、授权与历史保留。首版支持迁移文件完全一致的版本，不自动执行数据库降级。

```sh
python3 scripts/g4_remote.py --ssh-config /PRIVATE/ssh.json --output /PRIVATE/cloud/.g4 \
  upgrade --artifacts /PRIVATE/next-build --recipient-file /PRIVATE/backup-key/recipient.txt \
  --expected-current-commit CURRENT_FULL_COMMIT
python3 scripts/g4_remote.py --ssh-config /PRIVATE/ssh.json --output /PRIVATE/cloud/.g4 \
  rollback --to-source PREVIOUS_ACCEPTED_COMMIT --recipient-file /PRIVATE/backup-key/recipient.txt \
  --expected-current-commit CURRENT_FULL_COMMIT
```

流程为关闭网关并停止业务进程、加密备份及保留独立升级检查点、核对相同迁移、切换镜像、采集两次新的健康观察、验证HTTPS并恢复网关。旧观察和故障历史随备份及版本切换归档。失败只回退镜像及版本配置，绝不恢复旧数据库或重跑初始化。新写入仍保留。回退保留当前私有认证配置，不把已更新的AppSecret改回旧值。

相同版本重复确认不产生第二次备份或重启；并发操作互斥，旧期望版本停止办理。升级检查点位于私有`release-checkpoints`，与7份日常备份分开保留；待对应版本退出使用后再按运维记录清理。中断升级若停留在维护状态，先检查私有`release-operation.json`及备份，保持数据库不变；不要以清空目录、重建卷或重新初始化处理。

## 自动异地备份与恢复

每日服务器加密备份保留7个日副本。可选COS仅上传密文和必要清单，完整回读SHA256校验后才登记可用恢复点；按项目隔离，保留最新30个日副本。上传失败保留本地密文和此前已验证恢复点，并显示失败；不因重复上传把旧备份时间改新。超过24小时的副本显示过期。

安装可选主机适配器，不把云SDK加入Web或通知进程：

```sh
python3 scripts/g4_remote.py --ssh-config /PRIVATE/ssh.json --output /PRIVATE/cloud/.g4 \
  install-offsite --config-file /PRIVATE/offsite.json
```

私有JSON字段为`region`、`bucket`、`project`、`prefix`、`secret_id`、`secret_key`，可选`token`。默认广州地域，权限限于专用项目备份前缀的上传、下载、列举和保留期清理。账号密钥只保存在服务器/操作端私有配置；age解密私钥不上传服务器。SDK版本见`requirements-operations.txt`，[官方Python接口](https://cloud.tencent.com/document/product/436/65818)。首次发布也可指定`--offsite-config`，在首次备份前安装。

独立恢复先在受控操作端下载并验证密文及内部清单：

```sh
python3 scripts/g4_offsite.py --config /PRIVATE/offsite.json download \
  --backup-name ACCEPTED_BACKUP_NAME --destination /PRIVATE/downloaded \
  --identity-file /PRIVATE/backup-key/identity.txt
```

再使用匹配镜像、同版本迁移建库路径及原`restore`命令恢复到另一个空数据库；完整事实/结构比较后使未完成认证票据失效。下载校验不等于恢复通过。已知等价DDL摘要自动比较限制继续保留；不得放宽比较器来获得通过结果。本机每小时下载为额外副本，旧版本备份必须属于明确保留的发布历史。

## 状态、验收与交付

`g4_remote.py status`显示声明版本、实际容器镜像及源版本是否一致、迁移数量/摘要、合成门店数量、通知/积压/观察状态、服务器备份及异地恢复点。配置或监测缺失显示未配置/未知，不合并为“上线通过”。

另修复实际观察到的时钟间断：同一来源的合法旧记录发生正向墙上时间/单调时钟间断时，归档原观察及事故记录，从UNKNOWN重新取得两次正常样本；不同来源、坏校验及倒退时间不自动修复。此规则不修改业务，也不改变旧UNKNOWN及UNDETERMINED历史结论。

验收包括完整回归、独立空库初始化与重复调用、同卷升级及回退、真实HTTPS/七角色/跨店权限、加密恢复及故障演练。实际服务器执行二十账号三十分钟9000请求、80:20读写，p95小于5秒、无异常失败/重复效果/OOM；记录整机内存及带宽。还需本机离线、服务器/worker重启、证书续期、至少24小时观察，以及两个真实微信账号和实际手机流程。

源码、独立演练、真实COS、服务器、微信和手机结果分别归档。服务器/域名/AppSecret或体验权限未提供时，仅交付已完成的准备与演练，不宣称云端或微信验收通过。

思维导图：课程上线 → {完整资料、固定版本、HTTPS与微信} → {升级回退、通知监测、异地密文} → {容量、恢复、手机、持续运行} → 可核对的教师交付。
