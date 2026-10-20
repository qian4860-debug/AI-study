"""Verify the unchanged source snapshot and original history in the monorepo."""
from pathlib import Path
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
manifest = json.loads((HERE / 'source_snapshot.json').read_text(encoding='utf-8'))


def git(*args):
    return subprocess.check_output(['git', '-C', str(PROJECT), *args], text=True).strip()


for name, expected in manifest['source_file_sha256'].items():
    assert hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() == expected, name
for commit in manifest['original_history']:
    subprocess.run(['git', '-C', str(PROJECT), 'merge-base', '--is-ancestor', commit['commit'], 'HEAD'], check=True)
for tag in manifest['milestones']:
    assert git('rev-parse', tag['namespaced'] + '^{commit}') == tag['commit'], tag['namespaced']
print('PASS import: unchanged files=', manifest['source_file_count'],
      'original commits=', len(manifest['original_history']), 'milestones=', len(manifest['milestones']))
