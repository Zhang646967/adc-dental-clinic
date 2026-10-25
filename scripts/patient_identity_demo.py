"""Issue a private local simulator credential against this prepared RC instance.

Host Python3 + local Docker only. Does not expose ports or print the credential.
"""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('purpose',choices=['login','phone'])
    parser.add_argument('--subject',help='Stable synthetic login identity, e.g. course-patient-1')
    parser.add_argument('--account',help='Exact ADC account name displayed in My Account')
    parser.add_argument('--phone',help='Eleven-digit synthetic phone starting with zero')
    args=parser.parse_args()
    if args.purpose=='login' and (not args.subject or args.account or args.phone):parser.error('login requires --subject only')
    if args.purpose=='phone' and (not args.account or not args.phone or args.subject):parser.error('phone requires --account and --phone')
    root=Path(__file__).resolve().parents[1];os.umask(0o077)
    if not (root/'.rc/READY').is_file():parser.error('Run from a prepared, synthetic RC installation.')
    project=(root/'.rc/project.txt').read_text().strip()
    if not project.startswith('adc_rc1_') or not all(c in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in project):parser.error('Invalid RC project identity.')
    docker=shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'
    base=[docker,'--context','desktop-linux']
    endpoint=subprocess.check_output(base+['context','inspect','--format','{{.Endpoints.docker.Host}}'],text=True).strip()
    if not endpoint.startswith('unix://'):parser.error('Use the local Docker Desktop context.')
    folder=root/'.course-private/patient-identity'/uuid4().hex;folder.mkdir(parents=True,mode=0o700)
    command=base+['compose','--env-file',str(root/'.rc/compose.env'),'--project-directory',str(root),'-p',project,'-f',str(root/'compose.rc.yaml'),
        'run','--rm','--no-deps','-T','--user','0:0','--volume',str(folder)+':/identity-output','web','python','manage.py','local_patient_code','--output','/identity-output/credential.json']
    command+=['--subject',args.subject] if args.purpose=='login' else ['--account',args.account,'--phone',args.phone]
    with (folder/'command-private.log').open('x') as log:
        result=subprocess.run(command,stdout=log,stderr=log)
    if result.returncode:
        print('Local credential was not issued. Check the private command log: '+str(folder/'command-private.log'),file=sys.stderr);return 1
    credential=folder/'credential.json';data=json.loads(credential.read_text());credential.chmod(0o600)
    print(json.dumps(dict(source=data['source'],purpose=data['purpose'],expires_at=data['expires_at'],private_file=str(credential)),ensure_ascii=False))
    return 0


if __name__=='__main__':sys.exit(main())
