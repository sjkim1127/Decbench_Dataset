"""Collect real pinned C/C++ projects with replay and raw ELF/DWARF evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from decbench_dataset.manifest import finalize_build_manifest
from decbench_dataset.elf import validate_debug_pair


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(argv, **kw):
    return subprocess.run(argv, check=True, timeout=1800, **kw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'corpus/pilot')
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/pilot.json')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if '@sha256:' not in config['image']:
        raise ValueError('An immutable image digest is mandatory')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    image = json.loads(command(['docker', 'image', 'inspect', config['image']], capture_output=True, text=True).stdout)[0]
    rows = []
    for project in config['projects']:
        source = output / 'sources' / project['id']
        source.parent.mkdir(exist_ok=True)
        if not source.exists():
            command(['git', 'clone', '--no-checkout', project['repository_url'], str(source)])
        command(['git', '-C', str(source), 'checkout', '--detach', project['commit_sha']])
        if command(['git', '-C', str(source), 'status', '--porcelain'], capture_output=True, text=True).stdout.strip():
            raise ValueError('Source checkout is dirty')
        commit = command(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        if commit != project['commit_sha']:
            raise ValueError('Source commit mismatch')
        tree = command(['git', '-C', str(source), 'rev-parse', 'HEAD^{tree}'], capture_output=True, text=True).stdout.strip()
        license_text = (source / project['license_file']).read_text()
        if 'Permission is hereby granted' not in license_text:
            raise ValueError('Pilot MIT license check failed; review source license')
        source_tar = output / 'sources' / (project['id'] + '.tar')
        command(['git', '-C', str(source), 'archive', '--format=tar', '--output=' + str(source_tar), 'HEAD'])
        for profile, flags in config['profiles'].items():
            reports = []
            attempt_dirs = []
            for attempt in (1, 2):
                dest = output / 'builds' / project['id'] / profile / str(attempt)
                dest.mkdir(parents=True, exist_ok=False)
                attempt_dirs.append(dest)
                recipe = dest / 'recipe.json'
                recipe.write_text(json.dumps({'project': project, 'flags': flags}, indent=2))
                argv = ['docker', 'run', '--rm', '--platform', config['platform'], '--network', 'none',
                        '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                        '--pids-limit=256', '--memory=2g', '--cpus=2', '--user', f'{os.getuid()}:{os.getgid()}',
                        '--tmpfs', '/tmp:rw,nosuid,nodev,size=512m',
                        '-e', 'LC_ALL=C', '-e', 'TZ=UTC', '-e', 'SOURCE_DATE_EPOCH=0',
                        '-v', f'{source}:/src:ro', '-v', f'{dest}:/out:rw',
                        '-v', f'{recipe}:/recipe.json:ro',
                        '-v', f'{ROOT / "scripts/container_collect.py"}:/collector.py:ro',
                        '--entrypoint', '/usr/bin/python3', config['image'], '/collector.py']
                # Build failures are evidence and do not erase successful prior jobs.
                p = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
                (dest / 'docker.stdout').write_text(p.stdout)
                (dest / 'docker.stderr').write_text(p.stderr)
                if not (dest / 'report.json').exists():
                    raise RuntimeError(f'Container infrastructure failure: {dest}: {p.stderr[-1000:]}')
                reports.append(json.loads((dest / 'report.json').read_text()))
            report = reports[0]
            validations = [validate_debug_pair(d) if r['status'] == 'success' else None
                           for d, r in zip(attempt_dirs, reports)]
            artifacts = []
            for path in sorted(attempt_dirs[0].iterdir()):
                artifacts.append({'kind': 'raw-evidence', 'path': str(path.relative_to(output)),
                                  'sha256': sha(path), 'size': path.stat().st_size})
            equal = {}
            for name in ('binary.unstripped.so', 'binary.stripped.so', 'binary.debug', 'unit.o'):
                a, b = [d / name for d in attempt_dirs]
                equal[name] = sha(a) == sha(b) if a.exists() and b.exists() else None
            compiler = report['tools'][project['compiler']]
            manifest = finalize_build_manifest({
                'schema_version': '0.2.0', 'project': project['id'], 'language': project['language'],
                'source': {'repository_url': project['repository_url'], 'commit_sha': commit,
                           'tree_hash': tree, 'snapshot_sha256': sha(source_tar),
                           'snapshot_path': str(source_tar.relative_to(output)),
                           'license': {'spdx': project['spdx'], 'review_status': 'allowed',
                                       'evidence_path': project['license_file'],
                                       'evidence_sha256': sha(source / project['license_file']),
                                       'scope': 'pilot-translation-unit-and-source-snapshot'}},
                'target': {'id': 'linux-x86_64-elf', 'os': 'linux', 'format': 'elf', 'arch': 'x86_64',
                           'bits': 64, 'endianness': 'little', 'triple': report['target_triple_observed'],
                           'cpu_baseline': 'x86-64', 'tune': 'generic',
                           'abi': 'sysv-amd64', 'libc': report['runner']['libc'],
                           'os_version': report['runner']['os_release'],
                           'minimum_runtime': {'status': 'not-qualified', 'evidence': 'elf.stdout'}},
                'toolchain': {'family': 'gcc', 'version_raw': compiler['version']['stdout'],
                              'executable': compiler['executable'], 'executable_sha256': compiler['executable_sha256'],
                              'container_image_digest': config['image'], 'tools': report['tools'],
                              'compiler_probes': report['compiler_probes']},
                'profile': {'id': profile, 'flags': flags, 'kind': 'shared-library-translation-unit'},
                'runner': {'os': 'linux', 'isolation': 'docker-readonly-network-none',
                           'network_during_build': False, 'platform': config['platform'],
                           'image_id': image['Id'], 'image_digest': config['image'],
                           'os_release': report['runner']['os_release'],
                           'kernel': report['runner']['kernel'], 'machine': report['runner']['machine'],
                           'cpu': report['runner']['cpu'],
                           'packages': report['runner']['packages']},
                'commands': [json.dumps(c['argv']) for c in report['commands']],
                'command_records': report['commands'], 'environment': report['environment'],
                'capture_policy': report['capture'], 'artifacts': artifacts,
                'artifact_validation': validations,
                'status': 'success' if all(r['status'] == 'success' for r in reports) else 'failed',
                'reproducibility': {'attempts': 2, 'binary_hash_equal': equal['binary.unstripped.so'],
                                    'debug_hash_equal': equal['binary.debug'], 'artifact_hash_equal': equal,
                                    'replay_paths': [str(d.relative_to(output)) for d in attempt_dirs]},
                'split_group': project['repository_url'], 'qualified': False, 'eval_ready': {},
                'readiness': {'source_mapping': 'raw-dwarf-only', 'cfg': 'not-collected',
                              'execution_tests': 'not-run', 'full_project_build': False},
            })
            (output / 'builds' / project['id'] / profile / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            rows.append(manifest)
            print(f"{project['id']} {profile}: {manifest['status']} replay={equal}", flush=True)
    (output / 'builds.jsonl').write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    return int(any(row['status'] != 'success' for row in rows))


if __name__ == '__main__':
    sys.exit(main())
