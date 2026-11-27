# 项目文档导览

第一次接触 ADC，可以先走一遍患者、前台和医师的实际操作，再按兴趣读设计或代码。

| 阅读目的 | 入口 | 可以找到什么 |
| --- | --- | --- |
| 体验系统 | [三岗位试用指南](TEACHER_WALKTHROUGH.md) | 正常登录入口、各岗位的操作顺序和可观察的结果 |
| 了解整体设计 | [课程报告 PDF](../课程报告/课程报告_张加良_8210241102.pdf) · [报告说明](../课程报告/README.md) | 业务用例、岗位边界、系统模型与图表 |
| 查业务和技术实现 | [产品主计划](COMMERCIAL_V2_MASTER_PLAN.md) · [分项规格](../specs/) | 已实现的范围、岗位权限、失败分支和验收条件 |
| 看数据如何关联 | [数据库设计](database/README.md) · [系统图](diagrams/README.md) | 预约、病历、检查、结算和复诊之间的关系 |
| 验证或部署 | [macOS 安装](MACOS.md) · [统一部署包](C5_UNIFIED_DEPLOYMENT.md) · [测试目录](../tests/) | 本地合成库、安装升级、恢复和业务回归 |

## 顺着一次就诊读代码

1. 患者在[网页](../portal/)或[微信小程序](../clients/wechat/)选择服务与时段。[排班与预约](../scheduling/)核对资源，保留改期前后的关联。
2. [工作区](../workspaces/)确定当前角色和门店。[患者档案](../patients/)与[前台接待](../reception/)支持身份核对和到诊。
3. 医师从[临床记录](../clinical/)核对自述、检查、文书和版本。[实际处置](../care/)与[财务](../finance/)分别记录完成的业务与收退款。

历次验证以报告日期及所列环境为准。[版本记录](../RELEASE_CURRENT.md) · [早期仓库首页](https://github.com/Zhang646967/adc-dental-clinic/blob/f2fabe2cdcac6ee14db1d0b368613488c1b5249c/README.md) · [历次文档索引](https://github.com/Zhang646967/adc-dental-clinic/blob/f2fabe2cdcac6ee14db1d0b368613488c1b5249c/docs/README.md)
