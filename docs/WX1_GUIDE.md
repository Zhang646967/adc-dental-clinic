# WX1 开发联调操作指南

本指南面向操作者。真实微信、真机扫码和实际短信的当前结果见[验收记录](evidence_wx1/README.md)。平台条件未完成时保留现有患者账号和独立员工入口。

## 私有配置

本机可见文件为“下载 / ADC系统试用 / WX1私有配置.env”。已保留用户填写的AppID，AppSecret在该文件私下填写。文件权限保持600，不上传GitHub、不放进小程序、不发送到聊天。项目提供无凭据示例`PATIENT_AUTH_ENV.example`。

```sh
python3 scripts/wx1_platform.py status --private-config '/Users/zhang/Downloads/ADC系统试用/WX1私有配置.env'
```

此命令仅检查配置存在性，不调用微信或短信、不读取余额、不证明平台验收。原本机安装可显式使用`apply-rc --project-root /Users/zhang/Projects/adc-dental-clinic`应用配置；会保留私有环境备份，检查后通过原部署流程重建Web/worker。它不会自行重启或修改账号和数据库。

小程序测试号的凭据在[微信官方测试号管理页](https://mp.weixin.qq.com/wxamp/sandbox?doc=1)由本人扫码查看；核对AppID与工程一致，再将AppSecret填写到`ADC_WECHAT_MINI_APP_SECRET=`右侧。CloudBase环境编号是短信配置，不是微信密钥。格式检查只确认输入存在；官方接口返回、真实换码和最终账号映射必须另行验证。

本机模拟器可以先连接`http://127.0.0.1:18000`完成真实微信换码，不以云服务器或固定域名为前提。RC配置校验接受微信及CloudBase配置，live模式拒绝演示短信和本地身份替身。仅Web服务接入额外的`auth-egress`出站网络；数据库、迁移、通知和监测仍在内部网络，Web不发布端口。独立G4模板原有Web出站网络保持不变。

应用前保留加密数据库与配置备份；使用已通过验证的相同应用镜像重建Web和运行处理服务，再重建网关以刷新Web地址。核对`/api/mini/v1/session/`中的`auth_mode=live`、`wechat_mini=true`、`sms_demo=false`。能力字段只证明配置已加载；还需实际执行`wx.login → code2Session → ADC会话`。未开通真实短信时使用`ADC_SMS_PROVIDER=disabled`，不显示或发送测试验证码。

真实真机联调使用独立合成教师HTTPS环境。由操作者把已核验的ADC认证配置应用到该环境的`private/runtime.env`与`private/maintenance.env`，保留原数据库owner/runtime分离、临床合成及教师环境标记；设置`ADC_PATIENT_AUTH_MODE=live`、`ADC_PATIENT_IDENTITY_PROVIDER=disabled`，短信未具备免费条件时设置`ADC_SMS_PROVIDER=disabled`。按原G4流程更新私有plan文件摘要、重新渲染并校验Compose后重建Web/worker。原18000数据库不通过隧道公开，原教师环境从空合成库建立的来源保持不变。

## 微信开发者工具

小程序代码在`clients/wechat`；本机可见导入目录为“下载 / ADC系统试用 / 微信小程序”。通过开发者工具的“导入项目”选择该完整文件夹。本人完成微信扫码登录；自动导入需本人在安全设置启用服务端口。AppSecret始终只在后端。

```sh
python3 scripts/prepare_wechat.py --mode development --appid '你的注册AppID' --api-base 'https://已核验的教师测试域名' --output '/一个尚不存在的导出目录'
```

`local`只用于回环HTTP模拟器；`development`要求真实AppID和HTTPS，可在明确的开发调试中关闭请求域名校验；`experience`启用域名校验，须配置合规请求域名。开发调试、离线编译、真机、上传与体验版分别验收。

配置真实身份后，小程序主动确认微信登录；新账号进入本人建档核验，原账号可以先用密码或短信登录，再在我的账号绑定微信。扫码登录进入`pages/web-login/index`，核对目标网站与期限，明确确认或拒绝。网站以小程序扫码为主，手机及密码为同页备选。

## 免费短信条件

只使用CloudBase上海环境的默认通道。本人先核验个人账号开通资格、发送规则及足够免费余额，再设置免费额度确认标记和两个约定测试号码。实际平台免费资格未确认，不能按旧宣传额度推定。最多10次联调发送预约，失败占用预算，不充值、不启用付费或自动续费。微信一键取手机号在个人主体下保持关闭。

真实页面不显示短信验证码；Enter执行核验，获取验证码独立操作。演示模式只收0开头合成号码、明确显示未发送短信，不能计入真实验收。

## 验收和恢复

两名真实微信用户分别完成首次、重复和退出后登录；手机扫描网站码确认同一账号，并验证拒绝、过期、刷新、重复及不同浏览器领取。解绑或停用后原票据不能登录。两个约定号码实际收到短信后，验证注册、绑定、换绑、错误、过期、重放和额度不足。逐项核对原预约、改期、候补、患者切换与七角色范围。

恢复流程先在独立空库核对备份所有表和历史，再执行：

```sh
python manage.py invalidate_auth_challenges
```

随后才启动Web/worker。它使未完成扫码、短信、本地凭证及会话内授权挑战失效，保留账号、密码、已消费历史及患者权限。G4恢复命令已接入该步骤。同版本迁移建库后恢复数据的已验证路径继续保留；任意等价DDL自动结构比较的原有限制不变。
