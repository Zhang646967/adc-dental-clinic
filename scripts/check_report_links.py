"""Static IDs and source-path correspondence; not a formal UML or runtime proof."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/submission_R1'
ucs=json.loads((DOC/'use_cases.json').read_text(encoding='utf-8'))
expected={f'SU-{i:02d}' for i in range(1,26)}
assert {u['id'] for u in ucs}==expected
seen=[]
for file in sorted((DOC/'models').glob('S*.json')):
 m=json.loads(file.read_text(encoding='utf-8'))
 for label in m['cases'].values():seen.append(re.search(r'SU-\d\d',label).group())
 for actor,case in m['links']:assert actor in m['actors'] and case in m['cases']
assert len(seen)==25 and set(seen)==expected
for u in ucs:
 assert u['accept']=='AC-'+u['id'][3:]
 for k in ('actor','pre','trigger','main','alternatives','post','failure','criterion'):assert u[k]
 for path in re.findall(r'[a-z_]+/[a-z_]+\.(?:py|js|css)',u['implementation']):assert (ROOT/path).is_file(),path
print('PASS: 25 use cases, model membership, 25 acceptance IDs and named source paths.')
print('This does not prove runtime behavior, complete authorization or UML semantics.')
