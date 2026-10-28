"""Verify declared update files without touching settings, credentials or database.
Checksums detect partial/corrupt copies, not publisher authenticity.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import re
ROOT = Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',action='store_true',help='Also verify the complete checkout, including host-only historical evidence.')
    args=parser.parse_args()
    manifest=json.loads((ROOT/'UPDATE_MANIFEST.json').read_text(encoding='utf-8'))
    failures=[]
    declared=dict(manifest['files'])
    if args.archive:
        seen=set()
        for line in (ROOT/'CHECKSUMS.sha256').read_text(encoding='utf-8').splitlines():
            expected,name=line.split('  ',1)
            if name in seen or name in declared and declared[name]!=expected:
                failures.append('conflicting archive entry');continue
            seen.add(name);declared[name]=expected
    for name,expected in declared.items():
        rel=PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or not re.fullmatch('[0-9a-f]{64}',expected):
            failures.append('unsafe path');continue
        path=ROOT.joinpath(*rel.parts)
        if not path.is_file():failures.append(name+': missing');continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:failures.append(name+': differs')
    if failures:
        print('Update verification FAILED. Preserve local changes; do not force-overwrite them.')
        for name in failures:print(name)
        return 1
    print(f"Verified {len(manifest['files'])} declared files for {manifest['target']}.")
    if args.archive:print(f"Verified {len(declared)} complete archive entries, including retained host-only evidence.")
    print('This is file-integrity verification only, not a Django/database test or digital signature.')
    return 0
if __name__=='__main__':sys.exit(main())
