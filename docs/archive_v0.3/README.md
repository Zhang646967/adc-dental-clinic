# ADC 工程候选版 v0.3

**逻辑链：v0.2 模型 → 物理字段与约束 → Django 源码 → 本地 PostgreSQL 验收 → 下一增量。**

> 本包是代码与迁移的候选交付，不是已验证运行的系统。生成环境没有 Django、PostgreSQL 或 Docker，依赖下载因网络/DNS失败；因此没有执行 Django 导入检查、数据库迁移、网页启动或真实并发测试。已执行的只有 `checks/` 中 46 项纯规则测试与 11 项静态检查。详见 `docs/TEST_REPORT.md`。

个人开发、质量优先、没有明确截止日期。沿用 v0.2 的 20 个逻辑对象和状态/历史版本设计；没有改成另一个项目，也没有把课程案例的未说明内容伪装成已确认政策。

## 1. 本轮交付到哪里

已经编写源代码：员工登录；前台权限范围内的患者列表、建档、档案页；跨店精确患者编号识别；主管新增出诊时段；预约创建、列表、详情、到诊、取消、核实爽约、保留历史的改期；必要审计事件；随机密码的本地虚构数据初始化。

已经编写模型和候选迁移：20 个逻辑对象对应的 Django 模型、6 份初始迁移、1 份 PostgreSQL 保护迁移。Django 的组、权限、会话等还会产生额外表，20 不是最终数据库总表数。

尚未开放业务入口：实际治疗录入与确认、过敏复核界面、治疗完成、无治疗关闭、结算展示、受控更正、季度成本确认、经营统计。这些对应模型不代表这些功能已经实现。

未完成：Django/PostgreSQL 运行验收、浏览器验收、性能测试、公网部署、恢复演练、全部需求验收。生产设置明确阻断当前候选版直接上线。

## 2. 文件阅读顺序

| 文件/目录 | 用途 |
|---|---|
| `START_HERE.html` | 本说明的离线阅读版；不是业务页面预览 |
| `docs/PHYSICAL_DESIGN.md` | 类型、约束位置、锁与事务、剩余缺口 |
| `docs/FIELD_CATALOG.md` | 20 个模型的逐字段定义，来自源码静态提取 |
| `docs/CHANGELOG_v0.3.md` | 本轮新增字段和工程限制，不暗中改变 v0.2 |
| `docs/TRACEABILITY.md` | 需求/用例 → 源码 → 待执行验收 |
| `docs/REPORT_SECTION.md` | 可用于课程报告的工程章节草稿，保留真实验证状态 |
| `docs/TEST_REPORT.md` | 已运行与未运行项目的明确分界 |
| `scripts/integration_gate.py` | 本地真实验收的顺序执行入口；任一步失败即停止 |
| `AGENTS.md` | 后续人工/AI 修改代码时的约束与检查要求 |

## 3. 技术基线

本地目标是 Python 3.13、Django 5.2.17、PostgreSQL 17、Psycopg 3.2.10。Web 使用服务端模板，不另开 React/Vue 工程。

`requirements.txt` 固定主要框架/驱动版本，但没有完整锁定传递依赖；`python:3.13-slim` 和 `postgres:17` 也是可变标签。这是**候选基线，不是已经复现的完整环境锁**。首次成功验收后，需要保存实际包版本、容器摘要和测试结果，再决定正式发布的锁定方式。

## 4. 首次本地运行：Windows + Docker Compose

以下是待在你的机器执行的步骤，不是本会话已经完成的步骤。先确认 Docker Desktop/Engine 正常运行，并有可用的 Compose；宿主机上的 Python 只用于生成随机配置。

### 第一步：解压并检查环境

把包解压到一个新目录，进入包含 `manage.py` 的工程根目录，打开 PowerShell：

```powershell
py --version
docker --version
docker compose version
```

如果只有 `python` 命令而没有 `py`，后面的宿主机 `py` 命令改用 `python`。不要因此改动容器中的 `python` 命令。建议宿主机 Python 3.11+；容器目标版本已在 Dockerfile 中声明。

### 第二步：生成配置，构建并启动数据库

逐条执行，前一条成功后再执行下一条：

```powershell
py scripts/init_local.py
docker compose build web
docker compose up -d db
```

`init_local.py` 只在 `.env` 不存在时生成随机本地密钥，不覆盖已有配置、不改密码、不清空数据库。不要提交 `.env`，不要把其内容发到聊天中。

镜像/依赖下载失败属于环境问题；先保存错误输出，不要删除迁移、改用 SQLite 或关闭约束来绕过它。

### 第三步：执行真实验收门槛

```powershell
docker compose run --rm web python scripts/integration_gate.py
```

脚本顺序执行：Django 系统检查 → 模型与迁移一致性检查 → 实际迁移 → 30 项集成/并发测试。它在第一处失败时退出，不能把后续未执行的项目记为通过。

初始迁移是本轮编写的候选源码，**没有用 Django 的迁移探测器验证过**。`makemigrations --check --dry-run` 若发现差异，需要检查差异后修正迁移/模型；不要跳过检查直接宣称模型一致。

测试只应运行在本包独立的合成数据开发数据库上。Django 会建立和删除独立的 `test_...` 数据库，不能把这些命令指向有真实业务数据的数据库。

### 第四步：通过门槛后再初始化和打开页面

```powershell
docker compose run --rm web python manage.py seed_demo
docker compose up -d web
```

浏览器打开：

```text
http://127.0.0.1:8000/
```

`seed_demo` 为首次创建的账号随机生成密码，在事务成功后显示。密码不是公开通用的 admin/admin。重复初始化不会重置已有密码；只有显式传入 `--reset-passwords` 才会重置指定演示账号。

| 演示账号 | 职责 | 当前可验证范围 |
|---|---|---|
| `front_a` / `front_b` | 两家店的前台 | 各自店的患者与预约；不能互借角色权限 |
| `doctor_a` | 本人接诊 | 有本人的预约以后才有相应可见记录 |
| `manager_a` | 第一家店主管 | 新增出诊安排、运营元数据；不读患者临床详情 |
| `hq_demo` | 总部 | 跨店预约元数据；不默认开放临床详情 |
| `finance_demo` | 财务 | 本轮只有身份/角色，财务页面尚未实现 |
| `tech_demo` | 技术管理 | 本轮无账号管理网页；不默认拥有业务数据权限 |

前台创建一个患者后，可从档案页直接进入预约；初始化包含未来7天的虚构出诊时段。到诊以后会停在“已到诊”，不是已经可以治疗并开单。未来的预约不能直接认定爽约。所有日期表单按 Asia/Shanghai 解释。

## 5. 不使用 Docker 时

需要自行准备 PostgreSQL 17 和具有本地建库/安装 `btree_gist` 权限的开发账号，然后设置 `.env` 的连接参数。不要使用共享生产数据库。

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
py scripts/init_local.py
# 编辑本地 .env：填写你自己创建的开发数据库信息；不要公开。
.\.venv\Scripts\python.exe scripts/integration_gate.py
# 仅在门槛通过后继续：
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Python 3.13 未安装时不要照抄版本选择命令；先核实实际 Python 版本。Compose 路径通常能减少宿主机依赖差异，本轮不要求两条路径同时使用。

## 6. 数据与发布边界

Compose 只将 Web 和数据库端口绑定到宿主机 `127.0.0.1`，用于本地开发。数据库卷持久化保存数据，不能随意使用删除卷的命令。

本包没有购买服务器、绑定域名、上传 GitHub、创建云数据库或公网服务；没有原案例 PDF、原照片、字体文件、真实患者数据或预置固定密码。不要上传真实医疗资料来试用。

`config/settings/production.py` 当前有明确的发布阻断。将来要单独完成生产 Web 服务、HTTPS、登录节流、最小数据库权限、依赖锁定、备份恢复及各项验收后才能替换它；不能简单删除阻断就把本包称为生产版本。

## 7. 笔记总结

```text
工程 v0.3
├─ 模型：保留20个对象，落地字段与关系
├─ 约束：唯一 / 检查 / 排斥 / 跨表保护
├─ 代码：页面入口 → 权限 → 业务服务 → ORM → PostgreSQL
├─ 增量：先建档、预约和到诊，后治疗、结算和分析
├─ 已检查：46项纯规则 + 11项静态检查
└─ 下一道门槛：Django检查、迁移、30项真实集成/并发测试
```
