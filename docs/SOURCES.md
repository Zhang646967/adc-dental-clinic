# 来源与界限

## 用户提供材料

- `ANDREW’S DENTAL CHAIN：数据建模`，Ivey案例W44694，2024-10-08版本，第1–2页：原始业务需求。原PDF及照片不随工程包传播。
- `note__2.pdf`，第4页：Incremental Model，先交付有用子集并考虑后续接口。
- `note__3.pdf`，第1、4、11页：需求与设计、可测试要求、模型/不变量/操作前后条件。
- `note__4.pdf`，第7、11、15–16页：功能与数据并行细化，显式模块联系，内聚/耦合。
- 本项目 `ADC_models_v0.2.zip` / `DATA_DICTIONARY_v0.2.md` / `schema_model.json`：直接逻辑模型基线。只把自己的schema元数据复制进reference目录，未复制源案例文本。

上述材料没有指定本工程的库版本、字段长度、锁协议或具体SQL代码；这些均是设计补充，见变更记录。

## 核对过的官方技术资料（2026-09-21）

- Django支持版本：https://www.djangoproject.com/download/ （官方表列5.2 LTS及其支持期。）
- Django 5.2.17版本元数据：https://pypi.org/pypi/Django/5.2.17/json （核实发布，不代表本环境已安装。）
- Django排斥约束：https://docs.djangoproject.com/en/5.2/ref/contrib/postgres/constraints/
- Django事务：https://docs.djangoproject.com/en/5.2/topics/db/transactions/
- Django迁移：https://docs.djangoproject.com/en/5.2/topics/migrations/
- Django查询集/行锁：https://docs.djangoproject.com/en/5.2/ref/models/querysets/
- Django部署检查：https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- PostgreSQL约束：https://www.postgresql.org/docs/17/ddl-constraints.html
- PostgreSQL触发器：https://www.postgresql.org/docs/17/sql-createtrigger.html
- Docker Compose：https://docs.docker.com/compose/gettingstarted/
- Psycopg 3.2.10版本元数据：https://pypi.org/pypi/psycopg/3.2.10/json

文档指出机制的用途，不是对本项目候选SQL和代码的运行认证。依赖版本选择、性能、安全与完整业务验收仍需要自己的测试。
