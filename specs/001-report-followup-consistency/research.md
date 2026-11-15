# Research — 报告、服务和就诊身份

18539 开发者工具回传确认同一服务编号的报告页与预约核对显示不同名称。报告读取内部服务名，预约核对读取已发布的患者标题。报告改用现有公开服务查询，目录退出时展示保留的指示服务名称。

有效预约代办访问提醒时，原接口将本人限定与授权失效归入同一提示。患者工作区已有授权校验。报告入口用同一校验区分本人限定，仍使用 HTTP 403。

采用 GitHub Spec Kit 1.4.0 的既有项目流程，将用户场景、接口和验收一起纳入版本。 [官方既有项目说明](https://github.github.com/spec-kit/how-to/existing-projects.html) · [版本](https://github.com/github/spec-kit/releases/tag/v1.4.0)
