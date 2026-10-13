# v0.9.0-alpha.2 修订清单

## 已写入源码
1. E02：ReadOnlyDemoMiddleware按Django解析的view_name及固定操作能力表检查；SU-24受限POST查询可用，其余写入默认拒绝。CSRF、角色、对象及旧上下文继续检查。
2. E03：增加security_suspend普通账号安全封禁；不受pending_work阻挡；停用、使原密码不可用、清上下文及审计同事务。角色绑定和业务历史不被取消/转移。原disable仍要求业务处理。恢复先reset_password再enable。自操作与技术/超级目标仍受保护。
3. E01（部分）：替换生产设置保护桩为失败关闭的输入校验配置，增加Dockerfile.production、Gunicorn、Nginx示例及只读运行账号权限检查。默认local Compose不变。生产部署、依赖安装、授权配置与恢复验收未完成。
4. 增加compose.verify.yaml独立验证入口；无端口暴露、无原数据库卷、合成凭据。新增311项中的21项真实回归规格，待在PostgreSQL运行。
5. 中期报告R4.0采用正式版式，完整25份规约；与本候选状态分开记录。

## 不在本轮完成范围
多资源预约、CP-SAT、Outbox/后台通知、通用GuideRun、完整主数据生命周期、业务自动交接、真实生产部署。本轮不改用户本地v0.7。

## 无法从测试推断的结论
纯策略测试不证明真实HTTP/数据库；静态表单不证明登录和数据联动；set_unusable_password会使旧凭据与会话认证hash失效，但并发中已完成事务不会被撤销。生产环境必须限制仅可信代理可到应用端口，准备运行/迁移账户并执行恢复验证。
