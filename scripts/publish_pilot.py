"""Validate artifacts, package replay evidence, then optionally publish to HF."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import sys
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from decbench_dataset.elf import validate_debug_pair
from decbench_dataset.manifest import compute_build_id


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(corpus, destination):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import jsonschema

    rows = [json.loads(line) for line in (corpus / 'builds.jsonl').read_text().splitlines()]
    schema_path = Path(__file__).resolve().parents[1] / 'schemas/build-manifest.schema.json'
    schema = json.loads(schema_path.read_text())
    members = set()
    for row in rows:
        jsonschema.validate(row, schema)
        if compute_build_id(row) != row['build_id']:
            raise ValueError('Build identity mismatch')
        if row['status'] != 'success' or row['source']['license']['review_status'] != 'allowed':
            raise ValueError('Only successful, license-reviewed pilot records may be published')
        source = corpus / row['source']['snapshot_path']
        if sha(source) != row['source']['snapshot_sha256']:
            raise ValueError('Source snapshot hash mismatch')
        members.add(source)
        for item in row['artifacts']:
            p = corpus / item['path']
            if sha(p) != item['sha256'] or p.stat().st_size != item['size']:
                raise ValueError(f'Artifact mismatch: {p}')
        for rel in row['reproducibility']['replay_paths']:
            validate_debug_pair(corpus / rel)
            members.update(p for p in (corpus / rel).iterdir() if p.is_file())
        first, second = [corpus / rel for rel in row['reproducibility']['replay_paths']]
        for name, expected in row['reproducibility']['artifact_hash_equal'].items():
            if (sha(first / name) == sha(second / name)) != expected:
                raise ValueError('Replay equality changed: ' + name)
        members.add(corpus / 'builds' / row['project'] / row['profile']['id'] / 'manifest.json')
    destination.mkdir(parents=True, exist_ok=True)
    payload = destination / 'payloads/pilot-00000.tar'
    payload.parent.mkdir(exist_ok=True)
    index = []
    # Deterministic headers; include every replay, license-containing source snapshot and raw log.
    with tarfile.open(payload, 'w', format=tarfile.PAX_FORMAT) as tf:
        for path in sorted(members):
            name = path.relative_to(corpus).as_posix()
            data = path.read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))
            index.append({'member': name, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'shard': payload.relative_to(destination).as_posix()})
    (destination / 'artifact-index.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in index))
    (destination / 'builds.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in rows))
    data_dir = destination / 'data'
    data_dir.mkdir(exist_ok=True)
    metadata = [{
        'schema_version': row['schema_version'], 'build_id': row['build_id'], 'project': row['project'],
        'language': row['language'], 'compiler_family': row['toolchain']['family'],
        'compiler_version_raw': row['toolchain']['version_raw'], 'profile': row['profile']['id'],
        'os': row['target']['os'], 'arch': row['target']['arch'], 'abi': row['target']['abi'],
        'target_triple': row['target']['triple'], 'source_commit': row['source']['commit_sha'],
        'split_group': row['split_group'], 'status': row['status'], 'qualified': row['qualified'],
        'binary_reproducible': row['reproducibility']['binary_hash_equal'],
        'debug_reproducible': row['reproducibility']['debug_hash_equal'],
        'manifest_member': f"builds/{row['project']}/{row['profile']['id']}/manifest.json",
        'payload_shard': 'payloads/pilot-00000.tar',
        'manifest_json': json.dumps(row, sort_keys=True),
    } for row in rows]
    pq.write_table(pa.Table.from_pylist(metadata), data_dir / 'builds-00000.parquet', compression='zstd')
    card = '''---
license: other
license_name: upstream-per-project
license_link: LICENSE
task_categories:
- other
tags:
- binary-analysis
- decompilation
- reproducible-builds
configs:
- config_name: builds
  data_files:
  - split: raw
    path: data/*.parquet
---
# DecBench Multilang Corpus

Source snapshots, compiled binaries and provenance for a future multi-language
decompilation dataset. Planned languages: C, C++, Rust, Go, Zig, Swift, Fortran, D,
Nim. **This initial pilot contains C and C++ only.**

Two real upstream projects (cJSON and pugixml), four optimization profiles each,
two clean builds per profile. Artifacts are shared libraries built directly from
one translation unit per project, not complete upstream project builds.
Linux x86-64 ELF / System V AMD64 ABI only. Compiler/OS/tool versions, flags,
driver verbose logs, source licenses and raw ELF/DWARF are in each manifest/shard.
See `builds.jsonl` or the `builds` Parquet configuration for all records.

## Access

Read metadata using `load_dataset("sjkim1127/decbench-multilang-corpus", "builds", split="raw")`.
Payload member paths and SHA-256 values are in `artifact-index.jsonl`.
Fetch tar shards using `hf_hub_download(..., repo_type="dataset")`.
Both replay attempts are retained. Source archives retain upstream license files.

## Qualification and limitations

All records have `qualified=false` and no metric readiness. No generated program
was executed. No semantic test scores, normalized function mappings or machine
CFGs are claimed. Raw DWARF is evidence, not a validated function-level oracle.
All driver arguments are captured; GCC verbose output preserves child-command
evidence, but an execve trace and normalized child argv table are not collected.
CPU/ABI/OS declarations are build provenance, not proof of minimum runtime
compatibility. No train/test split is assigned; repository-family grouping is
retained for later deduplication and split assignment.

## Licenses

Upstream source and source-derived artifacts remain subject to each project's
MIT license. Exact copyright notices and permission terms are retained inside
each source snapshot. The corpus is not relicensed under a blanket license.
Only license-reviewed pilot translation units are included.
'''
    (destination / 'README.md').write_text(card)
    (destination / 'LICENSE').write_text('Per-project licenses apply. cJSON and pugixml pilot sources use MIT.\nExact upstream notices are retained in the source tar members of the payload shard.\n')
    root = Path(__file__).resolve().parents[1]
    for relative in ('configs/pilot.json', 'docs/COLLECTION_CONTRACT.md', 'schemas/build-manifest.schema.json',
                     'scripts/container_collect.py', 'scripts/collect_pilot.py', 'scripts/publish_pilot.py',
                     'src/decbench_dataset/manifest.py', 'src/decbench_dataset/elf.py',
                     'src/decbench_dataset/__init__.py', 'pyproject.toml'):
        target = destination / 'collection' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    inventory = [{'path': p.relative_to(destination).as_posix(), 'sha256': sha(p), 'size': p.stat().st_size}
                 for p in sorted(destination.rglob('*')) if p.is_file() and p.name != 'checksums.json']
    (destination / 'checksums.json').write_text(json.dumps(inventory, indent=2) + '\n')
    return rows, inventory


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--corpus', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--repo', default='sjkim1127/decbench-multilang-corpus')
    p.add_argument('--publish', action='store_true', help='Create/update the public dataset; otherwise only package locally')
    args = p.parse_args()
    rows, inventory = package(args.corpus.resolve(), args.output.resolve())
    print(json.dumps({'builds': len(rows), 'files': len(inventory), 'bytes': sum(x['size'] for x in inventory), 'publish': args.publish}))
    if args.publish:
        from huggingface_hub import HfApi
        api = HfApi()
        api.create_repo(args.repo, repo_type='dataset', private=False, exist_ok=True)
        # Never implicitly change the visibility of an existing repository.
        if api.repo_info(args.repo, repo_type='dataset').private:
            raise ValueError('Existing repository is private; resolve visibility explicitly')
        result = api.upload_folder(repo_id=args.repo, repo_type='dataset', folder_path=args.output,
                                   commit_message='Add reproducible C/C++ raw pilot with detailed build provenance')
        print(result)


if __name__ == '__main__':
    main()
