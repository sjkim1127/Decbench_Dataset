"""Lossless, revision-pinned catalog views over published raw metadata."""
from collections import Counter
import hashlib
import json
from pathlib import PurePosixPath

ARCH_ALIASES = {'amd64': 'x86_64', 'x64': 'x86_64', 'arm64': 'aarch64',
                'i386': 'x86', 'i686': 'x86'}
LANGUAGES = {'c', 'cpp', 'rust', 'go', 'zig', 'swift', 'fortran', 'd', 'nim'}
ARCHITECTURES = {'x86', 'x86_64', 'aarch64'}


def metadata_file(path):
    """Select original campaign tables, never a previously derived view."""
    return path.endswith('.parquet') and (
        path.startswith('data/') or path.startswith('native/') and '/data/' in path
        or path.startswith('rust/') and '/data/' in path
        or path.startswith('opensource/') and '/data/' in path
        or path.startswith('obfuscated/'))


def campaign_prefix(path):
    if path.startswith('data/'):
        return ''
    return path.split('/data/')[0] if '/data/' in path else str(PurePosixPath(path).parent)


def repository_path(prefix, path):
    parts = PurePosixPath(path).parts
    if not parts or path.startswith('/') or '..' in parts or '\\' in path:
        raise ValueError('Expected repository-relative path: ' + path)
    return '/'.join(x for x in (prefix, path) if x)


def normalize(row, metadata_path, row_number, repo, revision):
    manifest = json.loads(row['manifest_json'])
    target = manifest.get('target', {})
    observed = manifest.get('observed_binary', {})
    source = manifest.get('source', {})
    arch = row.get('arch') or target.get('arch')
    arch = ARCH_ALIASES.get(arch, arch)
    language = row['language'].lower()
    if arch not in ARCHITECTURES or language not in LANGUAGES:
        raise ValueError(f'Unreviewed target/language: {arch}/{language}')
    if row.get('qualified') is not False:
        raise ValueError('This view requires explicit raw/unqualified records')
    status = row['status']
    if status not in ('success', 'failed'):
        raise ValueError('Unreviewed build status: ' + status)
    prefix = campaign_prefix(metadata_path)
    is_pilot = metadata_path.startswith('data/')
    replay_paths = manifest.get('reproducibility', {}).get('replay_paths', [])
    if is_pilot and not replay_paths:
        raise ValueError('Pilot build missing replay membership')
    location = f'{metadata_path}#{row_number}'
    profile = row.get('profile')
    if isinstance(profile, dict):
        profile = profile.get('id')
    return {
        'catalog_schema_version': '1.0.0',
        'record_id': hashlib.sha256(f'{repo}@{revision}:{location}'.encode()).hexdigest(),
        'build_id': row['build_id'], 'project': row.get('project') or manifest['project'],
        'language': language, 'arch': arch, 'os': row.get('os') or target.get('os'),
        'format': row.get('format') or target.get('format') or observed.get('format'),
        'abi': row.get('abi') or target.get('abi'),
        'target_triple': row.get('target_triple') or target.get('triple'),
        'profile': profile, 'track': row.get('track'), 'status': status,
        'qualified': False, 'row_grain': 'build-with-replays' if is_pilot else 'build-attempt',
        'attempt': row.get('attempt'), 'physical_attempt_count': len(replay_paths) if is_pilot else 1,
        'source_repository': row.get('source_repository') or source.get('repository_url')
                             or manifest.get('repository_url') or row.get('split_group'),
        'source_commit': row.get('source_commit') or source.get('commit_sha') or manifest.get('commit_sha'),
        'source_dataset_repo': repo, 'source_dataset_revision': revision,
        'source_metadata_path': metadata_path, 'source_metadata_row': row_number,
        'campaign': prefix or 'pilot',
        'payload_repo_path': repository_path(prefix, row.get('payload_shard') or 'payload.tar'),
        'artifact_index_repo_path': repository_path(prefix, 'artifact-index.jsonl'),
        'manifest_member': row.get('manifest_member'),
        'manifest_json': row['manifest_json'],
        'original_metadata_json': json.dumps(row, sort_keys=True, separators=(',', ':')),
    }


def describe(rows):
    def counts(selected):
        return {'records': len(selected),
                'physical_attempts': sum(r['physical_attempt_count'] for r in selected),
                'successful_records': sum(r['status'] == 'success' for r in selected),
                'failed_records': sum(r['status'] == 'failed' for r in selected),
                'build_ids': len({r['build_id'] for r in selected}),
                'qualified': 0}
    result = counts(rows)
    for key in ('arch', 'language'):
        result[key] = {value: counts([r for r in rows if r[key] == value])
                       for value in sorted({r[key] for r in rows})}
    result['language_arch_records'] = dict(sorted(Counter(
        r['language'] + '/' + r['arch'] for r in rows).items()))
    return result


def config_specs(rows):
    return [('all_records', 'views/data/*/*.parquet')] + [
        ('architecture_' + arch, f'views/data/{arch}/*.parquet')
        for arch in sorted({r['arch'] for r in rows})] + [
        ('language_' + lang, f'views/data/*/{lang}.parquet')
        for lang in sorted({r['language'] for r in rows})]


def update_card(card, specs, revision):
    parts = card.split('---', 2)
    if len(parts) != 3 or parts[0].strip() or 'configs:' not in parts[1]:
        raise ValueError('Unexpected dataset card front matter')
    import re
    header = re.sub(r'- config_name: (?:all_records|architecture_\w+|language_\w+)\n'
                    r'.*?(?=- config_name:|\Z)', '', parts[1], flags=re.S)
    for name, pattern in specs:
        header = header.rstrip() + f'\n- config_name: {name}\n  data_files:\n  - split: raw\n    path: {pattern}\n'
    body = re.sub(r'\n## Architecture and language views\n.*?(?=\n## |\Z)', '', parts[2], flags=re.S)
    body += f'''
## Architecture and language views

Choose `all_records`, `architecture_x86_64`, `architecture_x86`,
`architecture_aarch64`, or a `language_` config (`c`, `cpp`, `rust`, `go`,
`zig`, `swift`, `fortran`, `d`, `nim`). Every config uses split `raw`.
For example: `load_dataset("sjkim1127/decbench-multilang-corpus", "architecture_aarch64", split="raw")`.
Filter columns `language`, `arch`, `os`, `format`, `abi`, `profile`, `status`
to select intersections. `aarch64` is the canonical ARM64 spelling.

These views reference existing payloads without duplicating binaries. Original
metadata is pinned to dataset revision `{revision}`. Use
`source_dataset_revision` when downloading `payload_repo_path` and
`artifact_index_repo_path`; tar member hashes are in that artifact index.
Full compiler/options/environment evidence remains in `manifest_json` and
`original_metadata_json`. Missing ABI/triple values remain null.

Rows preserve original granularity: initial pilot rows contain two replays;
other rows are individual attempts. Read `row_grain`, `attempt`, and
`physical_attempt_count`; row totals are neither unique binaries nor functions.
Failed build attempts stay visible; filter `status == "success"` for available
products. All records remain raw/unqualified. See `views/summary.json` for
counts and `views/README.md` for download/filter examples. Views are a frozen
snapshot and must be regenerated when new campaigns are published.
'''
    return '---' + header + '---' + body
