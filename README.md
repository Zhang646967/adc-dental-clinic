# ADC 口腔门诊系统

**[进入门诊系统](https://lijiahao.duckdns.org/experience/)　｜　[阅读验收报告（PDF）](课程报告/课程报告_张加良_8210241102.pdf)**

首次来访，从门诊首页点「患者登录」或「员工登录」。选择想体验的岗位后，系统会填好账号和密码，点击登录即可。已有岗位账号也可以手工输入。网页体验使用虚构资料，请勿录入真实个人信息。

## 按岗位办理

| 岗位 | 从哪里开始 | 办完核对什么 |
| --- | --- | --- |
| 患者 | 患者登录 → 我的预约 | 改期前后的门店与时间、当前预约状态 |
| 前台 | 员工登录 → 选择门店 → 患者档案 | 同名患者的完整编号、对应预约与到诊状态 |
| 医师 | 员工登录 → 检查记录工作台 | 本人负责的就诊、待确认草稿和当前确认版 |

建议先以患者身份打开一笔就诊，记下编号，再退出并以前台或医师身份核对同一笔记录。报告第五章给出了改期、同名患者核对和病历版本的核对方法。[岗位办理指南](docs/TEACHER_WALKTHROUGH.md)

<details><summary>安装、数据设计与源代码</summary>

- [Linux 安装与恢复](deployment/clinic/OPERATIONS.md) · [部署包说明](docs/C5_UNIFIED_DEPLOYMENT.md) · [本机安装](docs/MACOS.md)
- [数据库结构](docs/database/README.md) · [项目文档索引](docs/README.md)
- [预约与排班](scheduling/) · [病历与诊疗](clinical/) · [患者服务](portal/) · [微信小程序](clients/wechat/)
- [系统验证记录](https://github.com/Zhang646967/adc-dental-clinic/actions) · [历次版本](https://github.com/Zhang646967/adc-dental-clinic/tags)

</details>
