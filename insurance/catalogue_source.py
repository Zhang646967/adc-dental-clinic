"""Reviewed, server-held source package. Browser fields never supply policy rows."""
import hashlib
import json
from pathlib import Path
from adc_core.rules import RuleError

SOURCE_KEY = 'HN_ORAL_2026_12'
SOURCE_DIGEST = '70b9ecdb67296c737910190acfcbfd1901d7bc363b2b5124f96f8dd3ebe27f92'
NORMALIZED_DIGEST = '736b93b49c8ff00b78b9335f8c90484c41ad9b07b68e6a5b744d25a8c4b6f11b'
PACKAGE_DIGEST = 'a01f8e524d90710a627e3327dc5bb67750e4124ae08455b0a3bd9865994f4dd4'
PACKAGE = Path(__file__).with_name('policy_sources')


def load_source(key):
    if key != SOURCE_KEY:
        raise RuleError('请选择已核对来源的目录包。')
    raw = (PACKAGE / 'hunan-oral-2026.word.bin').read_bytes()
    package = (PACKAGE / 'hunan-oral-2026.json').read_bytes()
    if hashlib.sha256(package).hexdigest() != PACKAGE_DIGEST:
        raise RuleError('服务端目录包版本校验未通过，请核对已审阅来源。')
    data = json.loads(package)
    canonical = json.dumps(data['items'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(raw).hexdigest() != SOURCE_DIGEST or hashlib.sha256(canonical).hexdigest() != NORMALIZED_DIGEST:
        raise RuleError('服务端目录来源校验未通过，请维护人员核对原始文件。')
    if data['source_sha256'] != SOURCE_DIGEST or data['normalized_sha256'] != NORMALIZED_DIGEST:
        raise RuleError('目录包摘要不一致。')
    return raw, data
