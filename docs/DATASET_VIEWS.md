# Architecture and language views

The public Hugging Face dataset offers both architecture and language configs over
one shared set of metadata partitions. Binaries/source/debug payloads retain their
existing paths; the views do not duplicate them.

```python
from datasets import load_dataset

arm64 = load_dataset("sjkim1127/decbench-multilang-corpus", "architecture_aarch64", split="raw")
rust = load_dataset("sjkim1127/decbench-multilang-corpus", "language_rust", split="raw")
rust_linux_arm64 = rust.filter(lambda r:
    r["arch"] == "aarch64" and r["os"] == "linux" and r["status"] == "success")
```

Configs:

- `all_records`
- `architecture_x86`, `architecture_x86_64`, `architecture_aarch64`,
  `architecture_armv7`, `architecture_riscv64`
- `language_c`, `language_cpp`, `language_rust`, `language_go`, `language_zig`,
  `language_swift`, `language_fortran`, `language_d`, `language_nim`
- `qualification_candidates_cjson`: source/DWARF/symbol evidence, all unqualified
- `windows_pdb_evidence`: PE/PDB GUID/age and `.text` comparison records

Filter intersections using `arch`, `language`, `os`, `format`, `abi`, `profile`,
`track`, and `status`. Canonical `aarch64` includes target names spelled `arm64`;
target architecture is independent of host/runner architecture. A missing ABI or
target triple stays null rather than being guessed from the OS.

Additional queryable fields include compiler family, version, target, linker,
`isa_mode` and `build_scope`. Unknown standard-library/libc values remain null.
The supplementary PDB and qualification configs have different row schemas;
they are evidence tables rather than build-attempt tables.

`project_id` is a SHA-256 identity of the canonical repository URL and
`revision_id` combines it with the exact source commit. `variant_group_id` and
`replay_group_id` retain the original collector's build identity. These do not
detect forks or shared upstream code: `family_id` is explicitly null/unreviewed
until family relationships are researched. No train/test split is assigned.

Debug-directory-free PE rows are labeled `row_grain=derived-binary`,
`track=pe-debug-directory-free`, and `physical_attempt_count=0`: they are
postprocessed inputs derived from existing builds, not additional compilations.
Their manifests point to the original binary, PDB, source and build metadata at
the immutable recorded dataset revision.

Every row retains its original metadata JSON and full manifest JSON, plus the
original metadata path/row and immutable dataset revision. Compiler versions,
ordered flags, OS/SDK/ABI evidence and licenses remain available there.

For payload downloads pass `revision=row["source_dataset_revision"]` and
`filename=row["payload_repo_path"]` to `hf_hub_download`. The matching
`artifact_index_repo_path` records tar member names and SHA-256 values. Verify
those hashes before consuming extracted files.

## 2026-10-28 snapshot

The current index draws from source revision
`9b1c68bd308ccf9473a069a446e77b04a92c6383`: 1,470 metadata rows representing
1,478 physical attempts (1,454 successful, 24 failed). Target architecture row
counts are AArch64 362, ARMv7 408, RISC-V64 204, x86 180 and x86-64 316. The
counts include both replay attempts and are not unique functions or binaries.
The index adds 396 PDB association evidence rows and 113 source-mapping pilot
rows in separate configurations. All mapping candidates remain unqualified.

## Initial 2026-10-25 snapshot

The first view snapshot uses original data revision
`ee7f517a7ca8aec523365f49e503a288da99502b`.
The published catalog/config commit is
`b851d6039b13c38d2499a9019549cfd5c76e2df9` (20 uploaded files verified against
their checksums; all-record, three architecture and Rust configs loaded remotely).

| Architecture | Metadata records | Success records | Failed records |
| --- | ---: | ---: | ---: |
| aarch64 | 226 | 218 | 8 |
| x86 | 48 | 40 | 8 |
| x86_64 | 184 | 176 | 8 |
| Total | 458 | 434 | 24 |

These are metadata rows, not unique binaries or functions. Initial pilot rows
contain two replay attempts per row; other rows represent one build attempt.
`row_grain`, `attempt`, and `physical_attempt_count` expose that distinction:
458 rows represent 466 physical attempts, including 24 failures. `build_id`
groups replay attempts within existing collector identities; it is not a universal
source-function deduplication key. Local and hosted campaigns both remain visible.

Only C/C++ initially had x86 records; x86-64 and AArch64 language coverage is
uneven. View availability does not imply a complete language/architecture/OS
matrix. All records retain `qualified=false`; no benchmark split or metric is
created by grouping metadata. Failed acquisition history outside primary campaign
Parquet tables remains in its original history files and is not silently promoted
into this catalog.

## Refresh and publish

```bash
.venv/bin/python scripts/publish_views.py \
  --revision <full-HF-commit> --output shards/catalog-review
# Inspect the partition files, summary and proposed card first.
.venv/bin/python scripts/publish_views.py \
  --revision <same-full-HF-commit> --output shards/catalog-publish --publish
```

Use fresh output directories. Default is dry-run. The publisher validates input
payload/index references and primary binary hashes against the published artifact
indexes, checks a lossless Parquet partition round-trip, then adds all configs and
files in one commit. `parent_commit` refuses publishing over a newer remote head.
Uploaded file checksums are verified by downloading at the new commit.

This is a frozen snapshot. Regenerate it after publishing new campaigns; original
campaign configs continue to work independently. The index generator deliberately
ignores previous `views/` files to avoid recursive duplication.
