# ADC 患者微信小程序

本地导入 → 课程账号 → 查询与确认 → 网站共用数据 → 微信体验版另验收。

这是原生小程序，使用 WXML、WXSS 和 JavaScript，不是网页套壳。课程患者可以登录、选择诊所／服务／日期／医师、预约、查看当前及历史安排、普通时段改期和取消。椅位及设备由服务端统一安排；改期前身与后继可互查。无合适时段时联系前台，候补邀约在线办理暂保留在网站。

## 教师本地试用

1. 启动项目网站，确认 `http://127.0.0.1:18000/health/` 可访问。
2. 从[微信官方下载页](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)安装微信开发者工具，导入本目录。项目默认 `touristappid`；按工具提示选择测试号／游客模式。工具本身的登录要求以实际版本为准。
3. 本地设置使用“不校验合法域名、TLS版本及HTTPS证书”，只在开发者工具模拟器连接本机 HTTP 服务。本设置不作为体验版部署方式。
4. 使用私下分配的课程患者账号和密码登录。测试先查询有已发布排班的日期；没有时段时由前台发布出诊，并由主管完成资源配置。
5. 演示“预约→查看→改期→原新互查→取消→历史”，在网站核对同一记录。取消后的时段可重新被选择，预约不会产生治疗或收费。

仓库没有附带密码。现有本机实例的账号文件保存在 `.rc/private/demo-credentials.txt`，仅在本机查看。数据库、网站及小程序均只使用课程合成资料。

**手机的127.0.0.1是手机自身。** 默认地址仅供开发者工具在这台电脑使用，不能直接用于手机扫码。真机及体验版要使用已验证的后端地址。

可生成独立导入包，保留源目录配置：

```sh
python scripts/prepare_wechat.py --output /tmp/adc-mini-local --api-base http://127.0.0.1:18000
```

## 后续微信体验版

需要注册小程序、取得 AppID、给开发者授权，并把教师加入体验成员。前端仅用 AppID，不需要 AppSecret；当前采用课程账号登录，不调用微信身份或手机号接口。

云端后端需要固定 HTTPS 请求域名、有效证书及微信后台接受的服务器域名。微信官方网络文档要求域名经过 ICP 备案，因此不能直接假定免费 DuckDNS 子域名适用。优先核查学校可提供的已有备案域名。纯网页教师演示可单独准备免费子域名，微信平台接入另行完成。

```sh
python scripts/prepare_wechat.py --mode experience --appid wx0123456789abcdef --api-base https://YOUR-APPROVED-HOST --output /tmp/adc-mini-experience
```

上例 AppID 和域名必须替换为实际值。生成器强制开启域名校验，但不会代替微信后台授权、备案检查、代码上传、体验成员配置或真机验证。未注册和未取得服务器期间不宣称微信已上线。

## 验证范围

`node scripts/verify_wechat.cjs`检查原生源文件、事件绑定、北京时间及会话传输；Django真实PostgreSQL测试检查API、CSRF、权限和资源竞争。客户端与真实后端联调证据另见[本阶段记录](../../docs/evidence_b15/README.md)。这些检查不等同于微信开发者工具编译、手机实际运行或体验版扫码验收。

官方依据：[网络与域名](https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html)、[成员与版本发布](https://developers.weixin.qq.com/miniprogram/dev/framework/quickstart/release.html)。
