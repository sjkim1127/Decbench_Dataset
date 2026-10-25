"""Build a dry-run catalog, optionally publish metadata-only HF configs atomically."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from decbench_dataset.views import (config_specs, describe, metadata_file,
                                   normalize, update_card)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='sjkim1127/decbench-multilang-corpus')
    parser.add_argument('--revision')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    from huggingface_hub import HfApi, hf_hub_download, CommitOperationAdd
    import pyarrow as pa
    import pyarrow.parquet as pq
    api = HfApi()
    revision = api.repo_info(args.repo, repo_type='dataset', revision=args.revision).sha
    files = set(api.list_repo_files(args.repo, repo_type='dataset', revision=revision))
    def fetch(path):
        return Path(hf_hub_download(args.repo, path, repo_type='dataset', revision=revision))
    rows, inputs = [], []
    indexes = {}
    for path in sorted(p for p in files if metadata_file(p)):
        local = fetch(path)
        original = pq.read_table(local).to_pylist()
        inputs.append({'path': path, 'sha256': sha(local), 'records': len(original)})
        for number, row in enumerate(original):
            normalized = normalize(row, path, number, args.repo, revision)
            payload, index = normalized['payload_repo_path'], normalized['artifact_index_repo_path']
            if payload not in files or index not in files:
                raise ValueError('Missing payload/index for ' + path)
            if index not in indexes:
                index_file = fetch(index)
                indexes[index] = [json.loads(line) for line in index_file.read_text().splitlines()]
                inputs.append({'path': index, 'sha256': sha(index_file)})
            # All successful rows must retain primary binary evidence, not just a manifest.
            manifest = json.loads(normalized['manifest_json'])
            artifacts = manifest.get('artifacts', [])
            binary_artifacts = [a for a in artifacts if
                Path(a['path']).name in ('binary.unstripped', 'binary.unstripped.so', 'binary.so',
                                        'binary.dll', 'binary.dylib', 'tomlv', 'tomlv.exe')]
            if normalized['status'] == 'success' and not binary_artifacts:
                raise ValueError('No primary binary evidence: ' + path)
            expected = {(a['sha256'], a['size']) for a in binary_artifacts}
            actual = {(a['sha256'], a['size']) for a in indexes[index]
                      if a.get('shard', payload.split('/')[-1]) in
                      (row.get('payload_shard'), payload.split('/')[-1])}
            if not expected <= actual:
                raise ValueError('Binary hash missing from payload index: ' + path)
            rows.append(normalized)
    if not rows or len({r['record_id'] for r in rows}) != len(rows):
        raise ValueError('Empty or duplicate catalog')
    if any(not r['format'] or not r['os'] or not r['source_commit'] for r in rows):
        raise ValueError('Incomplete catalog dimensions/source identity')
    destination = args.output.resolve()
    if destination.exists():
        raise ValueError('Use a fresh output directory')
    destination.mkdir(parents=True)
    views = destination / 'views'
    views.mkdir()
    table = pa.Table.from_pylist(rows)
    partitions = defaultdict(list)
    for i, row in enumerate(rows):
        partitions[row['arch'], row['language']].append(i)
    for (arch, lang), indices in sorted(partitions.items()):
        path = views / 'data' / arch / (lang + '.parquet')
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table.take(pa.array(indices)), path, compression='zstd')
    # Verify full row retention and schema equality after physical partitioning.
    recovered = []
    for path in sorted((views / 'data').rglob('*.parquet')):
        part = pq.read_table(path)
        if part.schema != table.schema:
            raise ValueError('Partition schema drift')
        recovered += part.to_pylist()
    if {r['record_id']: r for r in rows} != {r['record_id']: r for r in recovered}:
        raise ValueError('Partition round-trip lost records')
    summary = {'repo': args.repo, 'source_revision': revision,
               'kind': 'revision-pinned-raw-metadata-views', **describe(rows), 'inputs': inputs}
    (views / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    specs = config_specs(rows)
    card = update_card(fetch('README.md').read_text(), specs, revision)
    (destination / 'README.md').write_text(card)
    (views / 'README.md').write_text('''# Architecture and language catalog

All configurations reference one shared set of Parquet partitions. Payload binaries
are not copied. This catalog is a frozen raw snapshot, not a qualified benchmark.

```python
from datasets import load_dataset
from huggingface_hub import hf_hub_download

ds = load_dataset("sjkim1127/decbench-multilang-corpus", "architecture_aarch64", split="raw")
rust_linux = ds.filter(lambda r: r["language"] == "rust" and r["os"] == "linux" and r["status"] == "success")
row = rust_linux[0]
tar_path = hf_hub_download(row["source_dataset_repo"], row["payload_repo_path"],
    repo_type="dataset", revision=row["source_dataset_revision"])
# Use the pinned artifact index to locate members and verify their SHA-256 values.
```

Alternatively choose `language_rust` and filter `arch`. Supported configs are in the
dataset card. Missing language/architecture combinations have no rows and are not
claimed as collected. `summary.json` gives actual counts. Metadata rows preserve
original build-vs-attempt granularity; do not report them as unique function/binary
counts. A pilot row represents two replay attempts. Failed attempts remain visible.
All original metadata and detailed manifests are retained as JSON columns.
''')
    (views / 'publish_views.py').write_bytes(Path(__file__).read_bytes())
    import decbench_dataset.views as module
    (views / 'views.py').write_bytes(Path(module.__file__).read_bytes())
    checks = [{'path': p.relative_to(destination).as_posix(), 'sha256': sha(p),
               'size': p.stat().st_size} for p in sorted(destination.rglob('*')) if p.is_file()]
    (views / 'checksums.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'inputs'}, indent=2), flush=True)
    if args.publish:
        # One commit keeps dataset-card configs and their data consistent; stale parent refuses overwrite.
        operations = [CommitOperationAdd(path_in_repo=p.relative_to(destination).as_posix(),
                                         path_or_fileobj=str(p))
                      for p in sorted(destination.rglob('*')) if p.is_file()]
        commit = api.create_commit(repo_id=args.repo, repo_type='dataset', operations=operations,
            parent_commit=revision, commit_message='Add architecture and language views over pinned raw corpus')
        print('PUBLISHED', commit.oid, flush=True)
        for check in checks:
            remote = Path(hf_hub_download(args.repo, check['path'], repo_type='dataset', revision=commit.oid))
            if sha(remote) != check['sha256']:
                raise ValueError('Remote verification mismatch: ' + check['path'])
        print('Remote checksums verified:', len(checks), flush=True)


if __name__ == '__main__':
    main()
