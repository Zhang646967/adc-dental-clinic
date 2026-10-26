# WX1 微信登录与统一患者账号

小程序真实换码 → 独立网站扫码确认 → 平台短信核验 → 同一 ADC 账号 → 原本人／代约权限。

本轮采用个人小程序主体。网站复用 ADC 小程序确认登录，不申请微信开放平台网站应用。临床数据继续为课程合成资料；真实认证与临床资料来源分别配置。真实平台配置尚未补齐，微信、真机扫码及实际短信均待验收，整轮目标尚未全部通过。

| 业务要求 | 规则与失败响应 | 实现与验证 |
| --- | --- | --- |
| 首次微信登录 | 服务端 `code2Session`，一次性 code；首次只建立账号，不强制电话、密码或创建患者 | `accounts/auth_providers.py`、`accounts/patient_auth.py`；`tests/test_patient_live_auth.py`、`tests/test_wx1.py` |
| 关联原账号 | 核验原密码，或先经短信登录当前账号；其他归属拒绝，不合并病历 | `portal/auth_views.py`；原账号与微信绑定 HTTP 检查 |
| 网站扫码 | 随机票据180秒，原浏览器私有凭据；手机重新换取微信 code，明确确认目标网站 | `accounts/web_login.py`、`portal/web_login_views.py`；不同浏览器、过期、刷新、解绑、停用与并发 |
| 状态查询和领取分开 | 每2秒查询；查询不登录，POST重新核验并一次性消费 | `static/patient-auth.js`；真实 Chrome 与 PostgreSQL并发检查 |
| 手机验证 | CloudBase生成与核验验证码；ADC保存用途、账号、会话和平台挑战引用 | `accounts/patient_auth.py`；错误、过期、重放、其他会话、失败与额度测试 |
| 手机绑定与换绑 | 号码已有其他账号时拒绝；原SMS身份解除归属，保留事件 | AccountPhone与ExternalIdentity原有模型及追加事件；绑定、换绑与冲突测试 |
| 明确认证模式 | `live`禁用本地替身和演示短信；旧演示凭据不能登录已接入真实认证的账号 | `accounts/auth_config.py`、设置检查及回退拒绝测试 |
| 独立恢复 | 先核对完整备份事实，再过期所有未完成认证票据和会话内认证挑战 | `invalidate_auth_challenges`；`scripts/g4_course.py`；独立恢复与失效测试 |

保留61份旧迁移原字节，追加accounts0005。实际观察为62份应用迁移、131张SQL表、356条外键、103个业务触发器。患者、治疗和财务表不变。账号、微信身份、账号号码、患者档案、本人关联及代约权限继续分开。

扫码状态：`PENDING → APPROVED → CONSUMED`，拒绝与失效分别为`REJECTED`、`EXPIRED`。过期GET按期限投影状态，不写业务。确认和消费使用事务锁；微信解绑、账号停用、密码或手机会话变化使原批准不能消费。更换登录方式时取消未完成扫码请求，避免旧响应影响新会话。

免费短信联调须同时满足上海环境、默认通道可用、足够免费额度已核对和约定测试号码。最多10次平台发送预约，失败也计入整轮上限；另保留每号码冷却、每日及来源上限。不充值、不启用付费自动续费，未满足条件不调用平台。图片验证码由ADC代理官方接口并绑定当前会话，提供方令牌不作为ADC会话。

课程报告新增SU-97—101，补充微信、网站扫码、短信注册、原账号关联与号码换绑；数据库说明见[实际ER目录](database/README.md)。操作步骤见[联调指南](WX1_GUIDE.md)，运行与验收记录见[分项证据](evidence_wx1/README.md)。

官方协议：[微信登录](https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/login.html)、[小程序码](https://developers.weixin.qq.com/miniprogram/dev/server/API/qrcode-link/qr-code/api_getunlimitedqrcode.html)、[短信发送](https://docs.cloudbase.net/http-api/auth/auth-send-verification)、[短信核验](https://docs.cloudbase.net/http-api/auth/auth-verify-verification)、[CloudBase鉴权](https://docs.cloudbase.net/http-api/basic/access-token)。默认通道的账号权益仍以实际开通和免费额度为准。

思维导图：微信生态 → {小程序换码、网站独立确认、手机核验} → 统一账号 → {本人核验、家人授权、原预约业务} → {隔离验证、真实平台验收、恢复交付}。
