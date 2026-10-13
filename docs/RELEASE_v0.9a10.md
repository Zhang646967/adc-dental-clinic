# v0.9.0-alpha.10：协调任务站内消息与可靠派发

父版为完整alpha.9。用户本机最后确认为Windows v0.7；集中部署和验收到v1.0候选完成后进行；Mac迁移暂停，R4.4报告不改动。本轮不访问用户实例，不要求下载或运行中间版本。

## 1. 已实现的范围

- 前台/主管导航新增“站内消息”，只显示本人、当前激活身份、当前诊所、原始收件授权且目前仍有效的消息。
- 主管在“协调任务”或站内消息中进入“通知派发状态”，核对本店待派发、失败、无符合条件收件人及最早等待时点。
- 任务成功变化时，在原事务内同时写任务、审计、NotificationOutbox。不存在“先发消息再提交任务”的路径。新事件只从本版新操作产生，不为旧任务历史批量补发。
- 独立worker只将已提交事件转换成InboxMessage；不调用任务、预约、接收控制、邀约、治疗或财务的写命令。不发短信/邮件/系统推送，不调用AI。
- 阅读列表和打开任务不自动标记已读；由本人明确POST“标记已读”。重复标记保留首次时间。只读模式仍能查询，但禁止已读标记、重试和worker写入。
- 标记已读不等于真实阅读、接受任务、患者同意或业务完成；消息中的事件状态与当前查询到的任务状态并列。

## 2. 谁收到哪些事件

|任务事件|原始收件角色（该诊所）|
|---|---|
|发起任务|前台|
|受理、办理声明、提交复核|主管|
|退回队列、主管退回、复核通过、撤销|前台及主管|

收件集合在事件写入时从有效账号和RoleAssignment中快照，最多500个授权，不静默截断。若超过上限，任务与事件一起拒绝保存。零收件人允许保存，worker将明确记为NO_RECIPIENTS；任务列表始终可查询。

worker再次核验原授权、角色、账号及诊所。后来新授予的另一绑定不追溯补发旧事件。消息显示时再次核验当前权限；撤权后已有消息也不可见。若原同一RoleAssignment日后重新启用，原已投递历史可能再次可见，这是本版的历史可见策略；不声称永久抹除。派发前已跳过的收件人不会因重新授权自动补发。

快照仅保存user_id、grant_id、role，不复制患者编号、姓名、电话、主诉、声明目标编号或自由文本。标题由有限动作目录生成；任务链接由内部路由形成，每个目标仍独立授权。

## 3. 派发/故障合同

每次使用PostgreSQL SELECT FOR UPDATE SKIP LOCKED取得一个可尝试事件。一个事件的所有InboxMessage插入和完成状态在同一短事务中提交；不保存PROCESSING租约。进程在提交前中断，该次事务回滚，事件仍可被后续worker处理。去重键为(event_id,grant_id)。

已处理故障先回滚内层保存点，再保存有限错误代码与重试计划。每轮最多5次；第1到第4次失败后分别等待15/60/300/900秒，第5次失败进入FAILED。结构/关联不符直接进入FAILED。连接中断导致失败记录本身无法提交时，整次回滚，命令不能宣称已处理成功。

主管可核对FAILED事件后明确重排原通知。重试轮次用于拒绝旧表单；只重置通知处理，不重放原任务。重试与相应审计同事务。错误记录不保存原始SQL、异常内容、凭据或收件明细。

多worker可能让后产生事件先投递；列表按原事件时间和编号排列，不按到达顺序推断任务状态。没有严格FIFO、外部 exactly-once、必达或读懂保证。DELIVERED仅表示站内消息行已保存，不表示网页弹出或人已查看。部分原授权失效时记录跳过数。

后台未运行时事件会留在PENDING；旧任务功能仍可通过任务列表办理。派发概况不是worker健康心跳。无收件人项不能简单“扩大收件范围重试”，需要通过授权治理和业务任务队列处理。

## 4. 运行入口（供v1.0集中配置，不是现在的用户任务）

- `python manage.py dispatch_notifications --batch-size 25`：单轮。
- `python manage.py dispatch_notifications --watch --interval 5`：持续轮询；进程停止后需重新启动。
- `compose.notifications.yaml`：可选本地worker叠加配置，无端口/数据卷，不合并到隔离验证配置，不默认开启。
- worker要求通知迁移已应用、PostgreSQL和可写实例；只读模式立即停止。默认compose和用户旧服务不改变。

生产supervision、目标主机worker启动检查与告警安排属于v1.0整合/部署验收，不能因为文件存在就认定已上线。没有引入Redis、Celery或外部托管服务作为强制依赖。

## 5. 数据模型与不变量

新增notifications应用、NotificationOutbox、InboxMessage及`notifications.0001_initial`。保留父版15份迁移原字节，共16份；原10个models.py保持不变。任务服务只增加保存审计后调用enqueue_task_notice这一事务内接口。

数据库约束包括源事件唯一、原事件和目标不可改写、收件人/授权/角色/诊所与原快照一致、事件+授权去重、已读时间不早于消息生成且不可改写首次标记。使用通知后，反向删除表被保护拒绝。

数据库检查和触发器均尚未在本环境运行，不据此声称整个约束已验证。旧应用不知道通知模型，也不会为新操作写Outbox，不得在启用后混跑旧写入版本；未来升级必须统一代码、模式和worker。

## 6. 实现分层

|层|文件|
|---|---|
|业务变化的通知接口|notifications/enqueue.py；coordination/task_services.py的一处事务内调用|
|纯规则|notifications/rules.py|
|后台转换|notifications/dispatcher.py；management/commands/dispatch_notifications.py|
|个人查询/标记与主管重试|notifications/services.py、views.py、urls.py|
|显示|templates/notifications；static/notifications.css|
|数据约束|notifications/models.py、migrations/0001_initial.py|
|有限任务指南|guidance/catalog.py：task-notices，NAV-09A10.1|

## 7. 测试边界

实际检查以docs/TEST_REPORT.md为准。纯规则、静态浏览器、文件重组与真实PG/HTTP各自取证，不互相替代；本輪没有用户实例、外部AI或公网操作。

## 官方机制依据（不等于本应用验证通过）

1. AWS Prescriptive Guidance, Transactional outbox pattern，2026-10-08核读：https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
2. Django 5.2, Database transactions，2026-10-08核读：https://docs.djangoproject.com/en/5.2/topics/db/transactions/
3. Django 5.2, QuerySet API(select_for_update)，2026-10-08核读：https://docs.djangoproject.com/en/5.2/ref/models/querysets/
4. PostgreSQL 17, SELECT(SKIP LOCKED)，2026-10-08核读：https://www.postgresql.org/docs/17/sql-select.html

本实现是同一数据库中延迟建立站内收件记录的有界应用，未采用AWS消息服务、分布式事务或事件溯源框架。收件角色、500上限、重试间隔和5次限制都是项目设计决定。
