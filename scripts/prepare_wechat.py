"""Prepare a separate importable native WeChat project without credentials."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def prepare(output, *, api_base, appid='touristappid', mode='local'):
    output = Path(output).expanduser().resolve()
    parsed = urlsplit(api_base)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('API base must contain only protocol, hostname and optional port.')
    if mode == 'local':
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost'):
            raise ValueError('Local packages use the developer-tool simulator and a loopback HTTP address.')
    elif mode in ('development','experience'):
        if parsed.scheme != 'https' or not parsed.hostname or not re.fullmatch(r'[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+', parsed.hostname):
            raise ValueError('Experience packages require an HTTPS DNS hostname and a valid certificate.')
        if not re.fullmatch(r'wx[a-fA-F0-9]{16}', appid):
            raise ValueError('Experience packages need the registered mini-program AppID.')
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            raise ValueError('Experience packages need a DNS hostname, not an IP address.')
    else:
        raise ValueError('Unknown package mode.')
    source = ROOT / 'clients' / 'wechat'
    if output == source or source in output.parents:
        raise ValueError('Prepare into a separate empty directory, outside the source project.')
    if output.exists():
        raise ValueError('Output must not exist; no existing project is replaced.')
    shutil.copytree(source, output, ignore=shutil.ignore_patterns('project.private.config.json'))
    config = json.loads((output / 'project.config.json').read_text())
    config['appid'] = appid
    config['setting']['urlCheck'] = mode == 'experience'
    (output / 'project.config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2)+'\n')
    (output / 'miniprogram/config.js').write_text('module.exports = '+json.dumps(dict(apiBase=api_base.rstrip('/'), mode=mode))+';\n')
    return dict(mode=mode, output=str(output), backend=api_base.rstrip('/'),
        uploaded=False, platform_verified=False,
        next_step='Import in WeChat developer tools; local simulator only.' if mode == 'local' else
        'Import with your registered AppID; development debugging may relax request-domain validation. Real WeChat login still requires server credentials.' if mode=='development' else
        'Configure the approved request domain, upload, assign experience members and verify on WeChat.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--api-base', default='http://127.0.0.1:18000')
    p.add_argument('--appid', default='touristappid')
    p.add_argument('--mode', choices=('local','development','experience'), default='local')
    args = p.parse_args()
    print(json.dumps(prepare(**vars(args)), ensure_ascii=False, indent=2))
