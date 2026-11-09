# ADC 口腔患者小程序

这是原生微信小程序项目，包含 28 个页面，与网站共用账号、患者授权、资源排班和预约数据。患者从主页、预约、就诊、我的进入相应业务。员工使用独立的网站工作台。

C6 从「就诊 → 办理与查询」及本人账单可进入资金流水，按门店查看已记账预收、有效抵扣、撤销与退款。 [资金口径与授权](../../docs/C6_PATIENT_ADVANCES.md)

P1新增门店详情、医师列表与详情，支持先选门店或先选医师后继续原预约、就诊人切换、改期与候补。[选诊试用](../../docs/P1_TRIAL_GUIDE.md) · [验证边界](../../docs/evidence_p1/README.md)。

## 本机运行

1. 确认本机合成后端的实际地址和应用版本。以下命令以端口 18000 为示例，演练时替换为指定的隔离后端地址。
2. 用微信开发者工具导入包含 `project.config.json` 的目录。游客 AppID `touristappid` 用于本机调试。
3. 使用私下分配的合成患者账号，从登录页展开账号密码入口。本人资料由前台核验后获得对应的办理权限。

导出一个独立、可导入的项目目录：

```sh
python3 scripts/prepare_wechat.py --output /tmp/ADC微信小程序 --api-base http://127.0.0.1:18000
```

本地关闭域名检查适用于开发工具模拟器。手机访问使用已核验的固定 HTTPS。统一入口和账号获取方式见[仓库首页](../../README.md)。

## 微信和短信能力

微信登录按后端实际配置启用。真实短信可用时才显示相应登录入口。平台联调使用实际 AppID、私有 AppSecret 和经过验收的 HTTPS，结果与游客编译及历史开发版联调分别记录。 [WorkBuddy 部署交接](../../docs/WORKBUDDY_MINIPROGRAM_HANDOFF.md)

有正式 AppID 和已批准的 HTTPS 后端后，可生成开启域名校验的体验版配置：

```sh
python3 scripts/prepare_wechat.py --mode experience --appid wx0123456789abcdef --api-base https://YOUR-APPROVED-HOST --output /tmp/adc-mini-experience
```

这条命令只生成项目，不上传微信、不配置平台，也不证明真机可运行。服务必须由授权主管配置资源并发布；小程序不会创建治疗事实、自动收款或越过前台身份核验。
