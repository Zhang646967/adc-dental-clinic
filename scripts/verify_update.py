"""Verify declared update files without touching settings, credentials or database.
Checksums detect partial/corrupt copies, not publisher authenticity.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
ROOT = Path(__file__).resolve().parents[1]
def main():
    manifest=json.loads((ROOT/'UPDATE_MANIFEST.json').read_text(encoding='utf-8'))
    failures=[]
    for name,expected in manifest['files'].items():
        rel=PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts:
            failures.append('unsafe path');continue
        path=ROOT.joinpath(*rel.parts)
        if not path.is_file():failures.append(name+': missing');continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:failures.append(name+': differs')
    if failures:
        print('Update verification FAILED. Preserve local changes; do not force-overwrite them.')
        for name in failures:print(name)
        return 1
    print(f"Verified {len(manifest['files'])} declared files for {manifest['target']}.")
    print('This is file-integrity verification only, not a Django/database test or digital signature.')
    return 0
if __name__=='__main__':sys.exit(main())
