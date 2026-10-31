最新回传（2026-10-30）：**P4官方开发者工具接受／拒绝／真实到期三项PASS，旧BLOCKED已解除。** [WorkBuddy回传](workbuddy_p4_return.json)与[只读账本核对](workbuddy_p4_facts.json)对应；旧记录保留为历史时点。P3本机整改由Codex执行并[复核](p3_recheck.json)，WorkBuddy未参与密钥验证，不将其写为本机未完成。下文保留上轮实施与交付证据。

# WorkBuddy反馈审核、候补发布与密钥文件化交付

岗位回传 → 直接发布入口 → 原职责与真实业务 → 密钥文件及恢复 → 保护更新 → C3.2任务。

应用`64ddf8100933ef8c9439e91bdccdd30f61d6ebcd`通过[完整CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/41156516935)；从该提交冻结构建的arm64镜像`sha256:cda0c64396f7e8ac3829dc7aff69b4fa418df30335efb802d72e46ae4ed37393`完成本地浏览器、HTTP及恢复验证，已更新原18000及独立18315。原生源码继续为`f4020475277daa5d0d7eaac45594d85bcacb62ea`，未改小程序业务代码或WorkBuddy部署副本。[机器状态](release.json)。

## 审核结论与修复

- **P4发布功能原已存在**：真实新Chrome会话核对前台当前广州越秀时为200，主管403。确切入口`/scheduling/plans/`，生成后在`/scheduling/plans/<方案>/`明确发布。旧交接及报告的“主管发布”表述错误，已修正为本店前台。新增工作台、导航、出诊详情和清单的直观入口，不扩大权限。[原入口核对](existing_entry_probe.json)、[WorkBuddy操作单](../WORKBUDDY_P4_PUBLISHING.md)。
- **P1按工具回传归档PASS**：[六项错误密码反馈和同页正确重试](workbuddy_tool_return.json)。这是用户转交的WorkBuddy官方工具结果，不是本批Codex手机或第二真实身份验收。
- **P3已完成本机整改**：Web专用只读文件、非root读取、环境中无非空AppSecret；通知、监测和迁移不取得文件。原AppID、密钥值和绑定保留。[实际微信凭据预检](secret-rehearsal.json)、[安装核对](final-install.json)、[配置恢复](final-backup.json)。Docker管理员仍属管理员权限，云端需在实际目标另验。[配置与恢复规则](../WECHAT_SECRET_FILES.md)。

## 执行证据

1. 完整CI：1,164源码规则、2,139PostgreSQL案例；另有131专项在挂载工作树中先行通过。新增七项PG/HTTP发布测试和六项文件配置测试。小程序原生检查沿用现有客户端，不据此新增真实平台结论。
2. [真实浏览器前台表单与原生HTTP传输](p4-live.json)：接受、重放只生成预约#9一条，之后正常取消；拒绝不形成预约；临近开诊按开诊时点提前到期；邀约#4等待真实完整十五分钟后，期限前新取得的接受预览被409拒绝。随后由前台正常回收、患者正常退出。未改系统时钟、期限字段或SQL业务状态。WorkBuddy#7/#8/#2保留，[原记录核对](workbuddy_records.json)。新增候补#3—#6、方案#1—#4和邀约#1—#4独立列在证据中，不冒称WorkBuddy实际操作结果。
3. [独立环境七角色、窄屏／放大和键盘](fixture-browser.json)及[原安装检查](installed-browser.json)分别28项。均使用真实Chrome及Django后端；小程序工具P4三场景仍交WorkBuddy复测。
4. [更新前备份的空库恢复](recovery.json)及[更新后备份的空库恢复](after-recovery.json)均比较143组原始业务、密码、图片、版本和资金事实以及完整实际结构。解密配置能重建由uid10001读取的同一密钥文件。恢复后才使未完成认证挑战失效。沿用同版本迁移建库路径，保留通用等价DDL比较限制。
5. [原系统保护更新](final-install.json)保留数据库容器／卷、密码、绑定和RC标签；旧运行观察已加密保存，新六项观察均健康。只清理本项目已停止且仍含旧明文环境的应用容器，不删除数据库卷。原安装不新增临床或财务事实，[最终核对](final-backup.json)。独立教师旧实例未更新。
6. [结构核对](schema.json)：65份迁移字节全部保留，146表／402SQL外键／114业务触发器／33实际ER不变。没有新增业务API、表或授权。
7. [课程报告核对](report.json)：固定名Word/PDF，240页、120业务用例加SF-01、139表、70图、96目录项；545个既有合同字段保留。[版式](report_visual_review.json)复用238页像素相同的已审结果，两页变化已逐页复核。

初次本地PG启动未就绪、浏览器脚本把公开首页当员工工作台，以及近期开诊造成的不足十五分钟测试窗口，均保留原失败记录；通过等待就绪、使用`/frontdesk/`及次日真实时段纠正测试条件，没有放宽产品规则或修改业务事实。安装核对同时识别Docker Desktop的`/host_mnt`源路径映射，继续检查准确目录、bind类型及只读属性。

本补丁未重复历史容量，不能把旧二十店负载改标为本次新结果。第二真实微信、正向关联、固定HTTPS、平台资格和教师体验仍待条件；手机由用户延期验收。历史UNKNOWN／UNDETERMINED及Windows恢复UNRESOLVED保留。

## 下一阶段

[C3.2任务单](../NEXT_STAGE_C32_TASKS.md)：具体治疗告知、适格签署人、准确决定、开治核对及变化处理。当前仅安排任务，尚未实现C3.2、可靠电子签名或归档。WorkBuddy继续只部署与工具回归；新业务接口和页面由Codex开发。

思维导图：回传 → {前台发布、患者决定、密钥文件} → {PG／浏览器、真实到期、加密恢复} → {原系统保护、报告一致、WorkBuddy复测} → C3.2。
