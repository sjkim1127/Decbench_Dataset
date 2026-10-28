"""Freeze reviewed upstream Git archives for network-isolated cross compilation."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import sys

ROOT = Path(__file__).resolve().parents[1]
DEST = Path(sys.argv[1]).resolve()
if DEST.exists():
    raise SystemExit('Use a fresh input directory')
DEST.mkdir(parents=True)
(DEST / 'sources').mkdir()
(DEST / 'archives').mkdir()
cfg = json.loads((ROOT / 'configs/native-projects.json').read_text())
entries = []
for project in cfg['projects']:
    source = ROOT / 'corpus/native-local-macos-aarch64/sources' / project['id']
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args])
    commit = git('rev-parse', 'HEAD').decode().strip()
    if commit != project['commit_sha'] or git('status', '--porcelain').strip():
        raise ValueError('Source checkout changed: ' + project['id'])
    blob = git('show', commit + ':' + project['license_file'])
    if hashlib.sha256(blob).hexdigest() != project['license_sha256']:
        raise ValueError('Upstream license differs from reviewed config')
    archive = DEST / 'archives' / (project['id'] + '.tar')
    subprocess.run(['git', '-C', str(source), 'archive', '--format=tar',
                    '--output=' + str(archive), commit], check=True)
    root = DEST / 'sources' / project['id']
    root.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(root, filter='data')
    entries.append({**project, 'tree_hash': git('rev-parse', 'HEAD^{tree}').decode().strip(),
                    'snapshot_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                    'snapshot_path': 'sources/' + project['id'] + '.tar',
                    'source_origin': 'upstream-open-source',
                    'dataset_authored_program_source': False, 'collector_supplied_harness': False})
(DEST / 'sources.json').write_text(json.dumps(entries, indent=2) + '\n')
shutil.copyfile(ROOT / 'configs/native-projects.json', DEST / 'reviewed-projects.json')
print('Prepared', len(entries), 'clean pinned upstream archives at', DEST)
