"""Retain bounded operational history, never replay it as a current heartbeat."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat

NAMES = ('monitor/monitor.json', 'monitor/previous-1.json', 'monitor/previous-2.json',
         'monitor/previous-3.json', 'worker/heartbeat.json')
MAX_BYTES = 4 * 1024 * 1024


def validate(value):
    if (not isinstance(value, dict) or set(value) != {'v', 'purpose', 'files'} or
            type(value['v']) is not int or value['v'] != 1 or
            value['purpose'] != 'HISTORICAL_ONLY_NOT_CURRENT_HEALTH' or
            not isinstance(value['files'], dict) or set(value['files']) != set(NAMES)):
        raise ValueError('Operational recovery history format differs.')
    for item in value['files'].values():
        if item is None:  # Missing observations are retained as missing.
            continue
        if not isinstance(item, dict) or set(item) != {'base64', 'sha256', 'size'}:
            raise ValueError('Operational recovery file fields differ.')
        data = base64.b64decode(item['base64'], validate=True)
        if (type(item['size']) is not int or item['size'] != len(data) or len(data) > 512 * 1024 or
                hashlib.sha256(data).hexdigest() != item['sha256']):
            raise ValueError('Operational recovery file differs.')
    return value


def collect(root='/snapshot'):
    result = {'v': 1, 'purpose': 'HISTORICAL_ONLY_NOT_CURRENT_HEALTH', 'files': {}}
    for name in NAMES:
        try:
            fd = os.open(Path(root) / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            result['files'][name] = None
            continue
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or
                    info.st_uid != os.geteuid() or info.st_nlink != 1):
                raise ValueError('Unsafe operational source file.')
            data = stream.read(512 * 1024 + 1)
        result['files'][name] = {'base64': base64.b64encode(data).decode('ascii'),
                                 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
    return validate(result)


if __name__ == '__main__':
    print(json.dumps(collect(), separators=(',', ':')))
