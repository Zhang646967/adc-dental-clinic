# ADC 口腔门诊系统

**[进入门诊系统](https://lijiahao.duckdns.org/)　｜　[阅读验收报告（PDF）](课程报告/课程报告_张加良_8210241102.pdf)**

患者在门诊首页查找门店、预约和回查就诊。前台与医师从「员工登录」进入各自工作台。同一笔就诊的编号贯穿到诊、检查、病历及费用核对。

## 按岗位办理

| 岗位 | 从哪里开始 | 办完核对什么 |
| --- | --- | --- |
| 患者 | 患者登录 → 我的预约 | 改期前后的门店与时间、当前预约状态 |
| 前台 | 员工登录 → 选择门店 → 患者档案 | 同名患者的完整编号、对应预约与到诊状态 |
| 医师 | 员工登录 → 检查记录工作台 | 本人负责的就诊、待确认草稿和当前确认版 |

持岗位邀请者可在邀请入口选择已获准的身份，再登录。其他已开通的护理、药房、财务及管理岗位使用分配的个人账号。验收环境采用虚构人物与业务记录，凭据随私有邀请交付。[岗位办理指南](docs/TEACHER_WALKTHROUGH.md)

<details><summary>安装、数据设计与源代码</summary>

- [Linux 安装与恢复](deployment/clinic/OPERATIONS.md) · [部署包说明](docs/C5_UNIFIED_DEPLOYMENT.md) · [本机安装](docs/MACOS.md)
- [数据库结构](docs/database/README.md) · [项目文档索引](docs/README.md)
- [预约与排班](scheduling/) · [病历与诊疗](clinical/) · [患者服务](portal/) · [微信小程序](clients/wechat/)
- [系统验证记录](https://github.com/Zhang646967/adc-dental-clinic/actions) · [历次版本](https://github.com/Zhang646967/adc-dental-clinic/tags)

</details>
