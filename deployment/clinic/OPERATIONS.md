# 门诊系统安装、升级与恢复

本手册供机构技术管理员使用。每家机构拥有独立的 HTTPS 地址、数据库、凭据和备份。首次建档完成后，管理员在员工入口设置本机构的岗位。恢复必须使用另一套空数据库。

## 1　准备主机与发布包

已通过安装演练的 Linux amd64 包在 GitHub 对应提交的「Clinic installation and recovery」运行页面底部，名称带有完整提交号，保留 14 天。下载并解开外层 ZIP，在私有目录执行 `sha256sum -c *.tar.sha256`，再将 tar 解包到仅所有者可访问的 `release/`。用 `sha256sum -c SHA256SUMS` 验证清单内的全部文件。`RELEASE.json` 记录完整 Git 提交、应用镜像、小程序、网页模板与静态资源、数据库迁移文件数和摘要，以及固定名称报告与可编辑图源的 SHA-256。清单同时列出本次恢复至前台登录的耗时和机构签收状态。

`BASE_IMAGES.json` 给出本次实际使用的数据库和网关镜像摘要。机构正式签收时，把核定版本、同一安装包及其摘要归档到该版本长期保存的 Release 资产或机构制品库。

正式环境使用 Linux amd64、Docker Engine 和 Compose V2、Python 3.13、OpenSSL、age；使用自动签发证书时还需 Certbot。Docker 必须指向本机 Unix socket。选定机构域名并将其解析到网关，公网开放 80 和 443，管理入口限制来源。数据库在私有容器网络，单独检查主机的磁盘加密、剩余空间、快照、日志权限及防火墙。

在有 Git 仓库的发布机设置完整提交号。以下命令分行执行，变量使用运维人员核定的值。

```sh
umask 077
export ADC_RELEASE="$(git rev-parse HEAD)"
export ADC_PACKAGE="$PWD/../adc-clinic-$ADC_RELEASE"
python3 scripts/clinic_release.py --context default build --source-commit "$ADC_RELEASE" --artifacts "$ADC_PACKAGE"
```

目录包含 `source.tar`、`application.tar`、`build.json`。前两项的 SHA-256 记录在第三项。记录完整提交、应用镜像 ID 和独立可信渠道提供的包摘要，再将安装包私下交给目标主机。镜像架构必须与主机一致。

在新主机创建只允许部署管理员访问的工作目录，先核对包的摘要再解包和载入镜像。下例假定发布包放在 `/srv/adc/release`，目录归部署用户所有。

```sh
umask 077
cd /srv/adc
mkdir -m 700 source state
python3 -c 'import hashlib,json,pathlib; d=pathlib.Path("release"); m=json.loads((d/"build.json").read_text()); assert all(hashlib.file_digest((d/f).open("rb"),"sha256").hexdigest()==m[k] for f,k in (("source.tar","source_sha256"),("application.tar","image_archive_sha256")))'
tar -xf release/source.tar -C source
python3 source/scripts/verify_update.py
docker --context default load -i release/application.tar
export ADC_RELEASE="$(python3 -c 'import json; print(json.load(open("release/build.json"))["source_commit"])')"
export ADC_APP="$(python3 -c 'import json; print(json.load(open("release/build.json"))["app_image"])')"
```

由机构批准 PostgreSQL 17 和 Nginx stable-alpine 的摘要，分别设置 `ADC_PG` 与 `ADC_NGINX`，格式为 `postgres:17@sha256:…`、`nginx:stable-alpine@sha256:…`。首次安装与异地恢复都沿用已核定的基础镜像；新标签可能指向不同内容。设置 `ADC_HOST` 为机构的实际 DNS 名称。

```sh
docker --context default pull "$ADC_PG"
docker --context default pull "$ADC_NGINX"
python3 source/scripts/clinic_release.py --context default --output state/.g4 prepare --host "$ADC_HOST" --bind-ip 0.0.0.0 --source-commit "$ADC_RELEASE" --app-image "$ADC_APP" --db-image "$ADC_PG" --nginx-image "$ADC_NGINX"
```

证书已有时，将匹配域名的完整证书链与私钥通过机构私密渠道分别保存为 `state/.g4/tls/fullchain.pem`、`state/.g4/tls/privkey.pem`，私钥权限为 600。若采用 HTTP-01 签发，在 DNS 生效后执行下行，将 `ADC_PUBLIC_IP` 设为实际公网地址。上线责任人安排续签与到期告警。

```sh
python3 source/scripts/clinic_release.py --context default --output state/.g4 issue-tls --public-ip "$ADC_PUBLIC_IP"
```

## 2　空库建档与首位管理员

在私密目录创建仅所有者可读写的 UTF-8 JSON 文件。机构字段须使用机构确认的信息，`area_sqm` 是平方米数的十进制字符串。管理员使用指定人员的用户名，在自己的密码管理器生成至少 16 字符的独立密码。可在本机使用安装包内的交互命令逐项填写，密码输入时隐藏。

```sh
python3 source/scripts/clinic_institution.py state/institution.json
python3 source/scripts/clinic_release.py --context default --output state/.g4 install --institution-file state/institution.json
python3 source/scripts/clinic_release.py --context default --output state/.g4 status
```

首次安装将创建独立的 `adc_clinic` 库、首家门店、一位技术管理员及一条建档审计。管理员仅有技术管理岗位，其他员工、患者、预约和资金记录均需经正常业务建立。检查 `ORIGIN_READY`、HTTPS、应用提交和数据库迁移一致后，按照机构密码保管政策移走或销毁临时建档文件。在安装中断后可使用原目录、原数据库卷和同一文件重试。发现无建档状态记录的已有表时，安装器会停止。

管理员在 `/accounts/login/` 进入技术工作台，选择「账号与授权」建员工账号，再在该账号下授予岗位。前台、门店主管需选门店。再次输入管理员本人密码、确认授权范围、填写依据后保存。用该员工账号重新登录，核对岗位与门店。医师需先关联该人员的医师档案；机构对执业资质与专业职责另行核实。

## 3　备份与异地存放

在独立保管机上运行 `age-keygen -o identity.txt`，再用 `age-keygen -y identity.txt > recipient.txt` 导出公钥。服务器仅接收公钥文件，权限 600。解密私钥由恢复责任人独立托管。将备份频率、保留期限、恢复目标、责任人和恢复演练日期登记在值班记录中。

```sh
python3 source/scripts/clinic_release.py --context default --output state/.g4 backup --recipient-file state/recipient.txt
```

将输出指定的密文与其 `.json` 摘要发送到机构授权的异地存储，回读并比对 SHA-256。系统支持在 `state/.g4/private/offsite.json` 配置既有私有对象存储适配器。仅看到本机 `SERVER_BACKUP_CREATED` 时，尚需异地回读凭据。另行保管同版本安装包、域名证书及外部平台密钥。备份含机构私有数据与数据库配置，只在限定的加密存储和恢复主机间流转。

当前恢复校验处理每个库最多 256 张表、每表 100 万行、单份逻辑转储最大 512 MiB。接近上限时，应在扩容与全量恢复演练通过后再扩大部署。恢复演练次数及其时长不等于签约机构的 RTO/RPO 承诺。

## 4　恢复到另一空库

在恢复主机完成第 1 节，以备份时同一完整源提交、同一应用镜像，准备新项目和新卷。为演练指定独立域名和证书，隔离对外访问。跳过第 2 节建档；恢复程序会用迁移创建结构并复核快照后再导入数据。下载授权异地存储中的密文，在恢复机的私密目录校验摘要。从源机构单独保存的交接记录取安装实例号和密文 SHA-256，分别设为 `ADC_SOURCE_PROJECT` 和 `ADC_BACKUP_SHA256`。仅靠备份目录旁的摘要无法鉴别发送者。密文文件名保留原名，权限 600，解密私钥由保管人提供。

```sh
python3 source/scripts/clinic_release.py --context default --output state/.g4 restore --backup-file "$ADC_CIPHERTEXT" --identity-file "$ADC_PRIVATE_IDENTITY" --source-project "$ADC_SOURCE_PROJECT" --backup-sha256 "$ADC_BACKUP_SHA256"
```

保存 `INDEPENDENT_RESTORE_COMPLETED`、`business_comparison=PASSED`、表数、行数及 `elapsed_ms`。计时从替代数据库及其镜像就绪起，至运行服务启动止；值班人员另外记录从发现故障到用户登录恢复的总时长。用恢复的管理员和普通员工分别登录，核对已发生业务编号、岗位和授权范围。仅在机构批准后安排业务切换。恢复目标已有表、源目标同项目、镜像不符或行摘要不符时会停止。

## 5　版本升级、故障与回退

先在上节的新实例对安装包执行升级、岗位回查和金额对账。正式切换时记录当前完整提交与最近业务编号，通知受影响岗位；操作期间系统暂停网关及写入服务，在同一快照下保留检查点，再启动新镜像。所有正式业务经该网关进入；维护窗口同步停止机构额外的导入程序或其他写入通道。

```sh
python3 source/scripts/clinic_release.py --context default --output state/.g4 upgrade --expected-current-commit "$ADC_PREVIOUS" --artifacts "$ADC_NEXT_PACKAGE" --recipient-file state/recipient.txt
```

看到迁移差异时，核对新增迁移名称、既有文件及回退策略，先在独立库演练，通过后对同一条命令增加 `--allow-additive-migrations`。同结构的新版本若健康检查失败，控制器尝试恢复旧镜像并保留当前数据库。恢复后核对故障前、切换期间和恢复后的业务编号。出现 `FAILED_MAINTENANCE_REQUIRED` 时保留现场与停写状态，核对私有日志和恢复检查点，交值班负责人决定前滚修复或独立恢复。已提交的新迁移须前滚修复；使用旧快照覆盖业务库会丢失检查点之后的写入。

同结构版本需主动回退时，选已登记在该部署历史的源提交。回退同样生成检查点，并使用现有数据库。

```sh
python3 source/scripts/clinic_release.py --context default --output state/.g4 rollback --expected-current-commit "$ADC_CURRENT" --to-source "$ADC_PREVIOUS" --recipient-file state/recipient.txt
```

切换后从固定 HTTPS 入口检查门店、岗位登录、近期业务和审计记录；确认同一笔业务仅有一次有效写入，并将业务发生时间、检查点、恢复回执与对账记录一并留存。

### 开通本店检查报告及复诊

在可写的正式机构实例完成迁移。核对本店服务编号、负责医师的记录授权、执行医师的记录授权、独立审核医师的读取授权和本店审核委任。开通命令由持有主机管理权限的人员执行，经办技术账号须具备有效技术管理职责。每个服务分别开通，安装后默认无已开通的机构项目。

```sh
python manage.py configure_site_examination --operator "$OPERATOR" --service "$SERVICE_ID" --code "$PROJECT_CODE" provision --name "$PROJECT_NAME" --examiner "$EXAMINER" --reviewer "$REVIEWER"
python manage.py configure_site_examination --operator "$OPERATOR" --service "$SERVICE_ID" --code "$PROJECT_CODE" revoke --user "$EXAMINER" --duty EXECUTE
python manage.py configure_site_examination --operator "$OPERATOR" --service "$SERVICE_ID" --code "$PROJECT_CODE" suspend
```

第二、三条分别用于撤销个人职责和暂停整个项目。暂停立即停止该项目的报告办理和患者报告入口，原已成立的复诊预约可从预约记录回查。恢复时重行第一条核对人员与职责。机构须自行核验人员资质，保留院内业务交接安排。患者在系统内查看报告提醒；微信站外通知须另行开通。

## 公开岗位体验实例

网页的岗位选择仅在使用独立虚构资料的实例启用。患者从患者登录进入，其他业务岗位从员工登录进入。选择岗位后仍须提交普通登录表单，实际权限由当前账号、工作区及门店决定。正式门诊使用个人账号。

使用独立的数据库、数据库用户、应用密钥及会话 Cookie。库名以 `adc_public_trial_` 开头，设置 `ADC_RC_SYNTHETIC=1`。为实际开通的岗位各建一个单岗位普通业务账号，账号名为 `trial_<岗位键>` 或带专用后缀。使用独立随机密码。患者本人需绑定虚构就诊档案；技术管理员、超级用户及多岗位账号均不列入选择器。

在应用可读的私有目录内配置 `ADC_PUBLIC_TRIAL_ROLE_FILE`，指向单独的 UTF-8 JSON 名单。文件包含 `purpose`（固定为 `public-role-trial-v1`）、`database`（该实例实际库名）、`expires_at`（带时区的截止时间）和 `roles`。每个岗位键映射独立的 `username`、`password`。常用键为 `owner`、`front`、`dentist`、`nurse`、`pharmacist`、`finance`、`manager` 和 `hq`。确认文件访问权限后原子替换。上线及轮换密码后从新的浏览器分别检查患者登录与员工登录。文件过期后会停止提供自动填充；停用账号可同时停止普通密码登录。岗位密码、私有邀请与会话均保存在仓库外。

微信患者体验包使用相同实例的 HTTPS 地址，在导入副本设置 `mode: 'experience'` 与 `publicTrialRoles: true`，打开域名校验。小程序只列出该实例已开通的患者身份。员工使用网页工作台。
