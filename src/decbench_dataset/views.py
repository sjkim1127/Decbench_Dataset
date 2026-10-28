"""Lossless, revision-pinned catalog views over published raw metadata."""
from collections import Counter
import hashlib
import json
import re
from pathlib import PurePosixPath

ARCH_ALIASES = {'amd64': 'x86_64', 'x64': 'x86_64', 'arm64': 'aarch64',
                'i386': 'x86', 'i686': 'x86', 'armhf': 'armv7'}
LANGUAGES = {'c', 'cpp', 'rust', 'go', 'zig', 'swift', 'fortran', 'd', 'nim'}
ARCHITECTURES = {'x86', 'x86_64', 'aarch64', 'armv7', 'riscv64'}


def tool_dimensions(row, manifest):
    """Promote explicit tool evidence; absent facts stay null."""
    toolchain = manifest.get('toolchain') or {}
    report = manifest.get('report') or {}
    tools = manifest.get('tools') or report.get('tools') or report.get('compiler') or {}
    family = row.get('compiler_family') or toolchain.get('family')
    version = row.get('compiler_version_raw')
    driver = toolchain.get('driver')
    if isinstance(driver, dict):
        version = version or driver.get('stdout') or driver.get('stderr')
        driver = driver.get('requested_executable') or driver.get('path')
    elif isinstance(toolchain.get('version'), dict):
        info = toolchain['version']
        version = version or info.get('stdout') or info.get('stderr')
    if not family and driver:
        name = driver.replace('\\', '/').rsplit('/', 1)[-1].lower()
        if name in ('cl', 'cl.exe'): family = 'msvc'
        elif 'clang-cl' in name: family = 'clang-cl'
        elif 'clang' in name: family = 'clang'
        elif 'gcc' in name or 'g++' in name: family = 'gcc'
    if not family:
        choices = {'rust':'rustc','go':'go','zig':'zig','swift':'swiftc',
                   'fortran':'gfortran','d':'ldc2','nim':'nim'}
        key = choices.get(row.get('language'))
        item = tools.get(key) if key else None
        if not item and key == 'go':
            item = manifest.get('go')
        if item:
            family = key
            info = item.get('version') or {}
            version = info if isinstance(info, str) else info.get('stdout') or info.get('stderr')
    version = version.strip() if isinstance(version, str) and version.strip() else None
    match = re.search(r'\b(\d+\.\d+(?:\.\d+){0,2})\b', version or '')
    linker = toolchain.get('linker') or {}
    linker_version = (linker.get('stdout') if linker.get('returncode') == 0 else None) if isinstance(linker, dict) else None
    if not linker_version:
        correction = manifest.get('toolchain_version_correction') or {}
        linker_version = correction.get('stdout') if correction.get('returncode') == 0 else None
    linker_path = linker.get('requested_executable') or linker.get('path') if isinstance(linker, dict) else None
    linker_family = 'lld' if linker_path and 'lld' in linker_path else ('gnu-ld' if linker_path and linker_path.endswith('-ld') else None)
    if not linker_family:
        companion = (toolchain.get('companions') or {}).get('link') or tools.get('ld') or {}
        info = companion.get('version') or {}
        if isinstance(info, dict):
            observed = (info.get('stdout') or info.get('stderr') or '').strip()
            if 'Microsoft' in observed and 'Linker' in observed:
                linker_family, linker_version = 'msvc-link', observed.splitlines()[0]
            elif 'GNU ld' in observed:
                linker_family, linker_version = 'gnu-ld', observed.splitlines()[0]
    return {'compiler_family':family, 'compiler_version':match.group(1) if match else None,
            'compiler_version_raw':version, 'compiler_target':row.get('compiler_target'),
            'linker_family':row.get('linker_family') or linker_family,
            'linker_version':row.get('linker_version') or (linker_version.strip() if linker_version else None),
            'stdlib_family':row.get('stdlib_family'), 'stdlib_version':row.get('stdlib_version'),
            'libc_family':row.get('libc_family')}


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
    scope = manifest.get('build_scope')
    if scope is None and isinstance(manifest.get('profile'), dict):
        if manifest['profile'].get('kind') == 'shared-library-translation-unit':
            scope = 'single-translation-unit'
    if scope is None and source.get('source_file') and row['schema_version'].startswith(('native-', 'cross-isa-')):
        scope = 'single-translation-unit'
    dimensions = tool_dimensions(row, manifest)
    explicit_targets = [arg.split('=',1)[1] for command in manifest.get('commands', [])
                        for arg in command.get('argv', []) if isinstance(arg,str) and arg.startswith('--target=')]
    dimensions['compiler_target'] = (dimensions['compiler_target'] or target.get('triple') or
                                     row.get('target_triple') or (explicit_targets[0] if explicit_targets else None))
    return {
        'catalog_schema_version': '1.0.0',
        'record_id': hashlib.sha256(f'{repo}@{revision}:{location}'.encode()).hexdigest(),
        'build_id': row['build_id'], 'project': row.get('project') or manifest['project'],
        'language': language, 'arch': arch, 'os': row.get('os') or target.get('os'),
        'format': row.get('format') or target.get('format') or observed.get('format'),
        'abi': row.get('abi') or target.get('abi'),
        'target_triple': row.get('target_triple') or target.get('triple'),
        'profile': profile, 'track': row.get('track'), 'status': status,
        'isa_mode':target.get('isa_mode'), 'build_scope':scope, **dimensions,
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
    body = re.sub(r'\n## ARMv7 and RISC-V64 raw campaign\n.*?(?=\n## |\Z)', '', body, flags=re.S)
    body = body.replace(
        'Source snapshots, compiled binaries and provenance for a future multi-language\n'
        'decompilation dataset. Planned languages: C, C++, Rust, Go, Zig, Swift, Fortran, D,\n'
        'Nim. **This initial pilot contains C and C++ only.**',
        'The following section describes the original C/C++ pilot.\n\n## Initial C/C++ pilot\n\n'
        'That pilot contains C and C++ only; later campaigns cover all nine listed languages.')
    body = body.replace(
        "Upstream source and source-derived artifacts remain subject to each project's\n"
        'MIT license. Exact copyright notices and permission terms are retained inside\n'
        'each source snapshot. The corpus is not relicensed under a blanket license.\n'
        'Only license-reviewed pilot translation units are included.',
        'Each upstream source and derived artifact retains its own project license.\n'
        'The initial cJSON/pugixml pilot uses MIT licenses; later campaigns include\n'
        'MIT, BSD, zlib and other reviewed upstream licenses. Exact notices are kept\n'
        'with source snapshots. There is no blanket relicensing of the corpus.')
    architectures = ', '.join(f'`{name}`' for name, _ in specs if name.startswith('architecture_'))
    body += f'''
## Architecture and language views

Choose `all_records`, an architecture config ({architectures}), or a `language_` config (`c`, `cpp`, `rust`, `go`,
`zig`, `swift`, `fortran`, `d`, `nim`). Every config uses split `raw`.
For example: `load_dataset("sjkim1127/decbench-multilang-corpus", "architecture_aarch64", split="raw")`.
Filter columns `language`, `arch`, `isa_mode`, `os`, `format`, `abi`, `profile`, `build_scope`, `status`, `compiler_family`, `compiler_version`, `compiler_target`, `linker_family`
to select intersections. `aarch64` is the canonical ARM64 spelling.

These views reference existing payloads without duplicating binaries. Original
metadata is pinned to dataset revision `{revision}`. Use
`source_dataset_revision` when downloading `payload_repo_path` and
`artifact_index_repo_path`; tar member hashes are in that artifact index.
Full compiler/options/environment evidence remains in `manifest_json` and
`original_metadata_json`. Missing tool, ABI, or triple values remain null;
compiler/linker columns only report evidence actually captured.

Rows preserve original granularity: initial pilot rows contain two replays;
other rows are individual attempts. Read `row_grain`, `attempt`, and
`physical_attempt_count`; row totals are neither unique binaries nor functions.
Failed build attempts stay visible; filter `status == "success"` for available
products. All records remain raw/unqualified. See `views/summary.json` for
counts and `views/README.md` for download/filter examples. Views are a frozen
snapshot and must be regenerated when new campaigns are published.
'''
    if any(name == 'architecture_armv7' for name, _ in specs):
        body += '''
## ARMv7 and RISC-V64 raw campaign

Six pinned upstream C/C++ projects were compiled for ARMv7 ARM and Thumb modes
and RISC-V64 with GCC and Clang. O0/O1/O2/O3/Os/Oz, O2-noinline, O2-LTO and
Clang O2-ThinLTO are retained; inspect the campaign summary for actual counts.
Each attempt includes original/stripped ELF, external debug, raw execve traces,
normalized observed child argv, flags, toolchain/image identity and logs. GNU
debuglink CRC and stripped `.text` equality are checked; none proves semantics.
See `native/cross-isa-2026-10-28/summary.json`. Its qualification pilot contains
source/DWARF/symbol candidates with zero qualified functions.
'''
    return '---' + header + '---' + body
