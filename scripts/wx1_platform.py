"""Inspect private WX1 configuration, or explicitly apply it to an existing RC install.

Never calls WeChat/SMS, prints credentials, purchases service, or restarts an app.
"""
import argparse,json,os,re,stat
from datetime import datetime,timezone
from pathlib import Path

KEYS=('PATIENT_AUTH_MODE','PATIENT_IDENTITY_PROVIDER','WECHAT_MINI_APP_ID','WECHAT_MINI_APP_SECRET','WECHAT_QR_ENV_VERSION',
    'CLOUDBASE_ENV_ID','CLOUDBASE_REGION','CLOUDBASE_PUBLISHABLE_KEY','SMS_FREE_QUOTA_CONFIRMED','SMS_ALLOWED_TEST_PHONES','SMS_LIVE_TEST_LIMIT')


def read_private(path):
    path=Path(path).expanduser()
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode)&0o077:raise ValueError('Private configuration must be a regular private file (chmod 600).')
    values={}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        key,separator,value=line.partition('=')
        if not separator:raise ValueError('Use KEY=value entries in the private configuration.')
        values[key.strip()]=value.strip().strip('"').strip("'")
    return values


def inspect(values):
    app=bool(re.fullmatch(r'wx[0-9a-fA-F]{16}',values.get('ADC_WECHAT_MINI_APP_ID','')))
    secret=bool(values.get('ADC_WECHAT_MINI_APP_SECRET'))
    phones=tuple(x.strip() for x in values.get('ADC_SMS_ALLOWED_TEST_PHONES','').split(',') if x.strip())
    sms=bool(values.get('ADC_CLOUDBASE_ENV_ID') and values.get('ADC_CLOUDBASE_PUBLISHABLE_KEY') and values.get('ADC_SMS_FREE_QUOTA_CONFIRMED')=='1' and
        values.get('ADC_CLOUDBASE_REGION','ap-shanghai')=='ap-shanghai' and phones and all(re.fullmatch(r'1[3-9][0-9]{9}',x) for x in phones))
    return dict(registered_appid_present=app,appsecret_present=secret,wechat_configuration_ready=app and secret,
        sms_configuration_ready=sms,authorized_test_phone_count=len(phones),free_quota_confirmed=values.get('ADC_SMS_FREE_QUOTA_CONFIRMED')=='1',
        wechat_platform_acceptance='NOT_RUN',sms_platform_acceptance='NOT_RUN',network_calls=0,chargeable_actions=0)


def apply_rc(values,root):
    facts=inspect(values)
    if not facts['wechat_configuration_ready']:raise ValueError('Registered AppID and matching AppSecret are still required; existing install unchanged.')
    if values.get('ADC_PATIENT_AUTH_MODE')!='live' or values.get('ADC_PATIENT_IDENTITY_PROVIDER')!='disabled':raise ValueError('Use live authentication and disable local credential substitutes.')
    if values.get('ADC_WECHAT_QR_ENV_VERSION','develop') not in ('develop','trial','release'):raise ValueError('Invalid QR environment version.')
    path=Path(root).expanduser()/'.rc/compose.env';read_private(path)
    source=path.read_text();updates={'RC_'+key:values.get('ADC_'+key,'') for key in KEYS}
    private=path.parent/'private';private.mkdir(mode=0o700,exist_ok=True)
    if private.is_symlink() or stat.S_IMODE(private.stat().st_mode)&0o077:
        raise ValueError('Protect .rc/private with mode700 before applying the WeChat secret.')
    directory=private/'wechat'
    if directory.is_symlink():raise ValueError('Use a regular private WeChat directory.')
    directory.mkdir(mode=0o755,exist_ok=True);directory.chmod(0o755)
    secret_file=directory/'mini-app-secret'
    if secret_file.is_symlink():raise ValueError('Use a regular private WeChat secret file.')
    # The host parent is0700. Only this dedicated0755 directory is mounted into
    # Web, read-only, so its unprivileged uid can read the0444 file. Compose
    # file-backed secrets cannot remap host uid/gid on every supported platform.
    if secret_file.exists():secret_file.chmod(0o600)
    with secret_file.open('w') as out:os.chmod(secret_file,0o600);out.write(values['ADC_WECHAT_MINI_APP_SECRET']+'\n')
    secret_file.chmod(0o444)
    updates['RC_WECHAT_MINI_APP_SECRET']=''
    updates['RC_WECHAT_MINI_APP_SECRET_FILE']='/run/adc-wechat/mini-app-secret'
    updates.update(RC_SMS_PROVIDER='cloudbase' if facts['sms_configuration_ready'] else 'disabled',RC_TEACHER_TEST_MODE='0')
    updates['RC_SMS_LIVE_TEST_LIMIT']=str(min(10,max(0,int(values.get('ADC_SMS_LIVE_TEST_LIMIT','10')))))
    updates['RC_WECHAT_QR_ENV_VERSION']=values.get('ADC_WECHAT_QR_ENV_VERSION','develop')
    updates['RC_CLOUDBASE_REGION']=values.get('ADC_CLOUDBASE_REGION','ap-shanghai')
    lines=[];seen=set()
    for line in source.splitlines():
        key=line.partition('=')[0]
        if key in updates:lines.append(key+'='+updates[key]);seen.add(key)
        else:lines.append(line)
    lines.extend(key+'='+value for key,value in updates.items() if key not in seen)
    backup=path.with_name('wx1-before-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.env')
    with backup.open('x') as out:os.chmod(backup,0o600);out.write(source)
    with path.open('w') as out:os.chmod(path,0o600);out.write('\n'.join(lines)+'\n')
    return dict(**facts,configuration_applied=True,restart_required=True,backup_file=str(backup),secret_storage='WEB_READ_ONLY_FILE',accounts_and_database_modified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['status','apply-rc']);parser.add_argument('--private-config',required=True);parser.add_argument('--project-root')
    args=parser.parse_args()
    try:
        values=read_private(args.private_config)
        if args.action=='apply-rc' and not args.project_root:raise ValueError('--project-root is required for apply-rc.')
        result=inspect(values) if args.action=='status' else apply_rc(values,args.project_root)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError):
        parser.exit(2,'WX1 configuration is incomplete or invalid; check the private file and guide. No platform acceptance was executed.\n')


if __name__=='__main__':main()
