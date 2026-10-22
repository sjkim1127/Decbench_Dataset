# Automation Architecture

## Pipeline

```text
project registry
  -> source fetch/cache
  -> dependency acquisition/vendor phase
  -> immutable source snapshot
  -> matrix resolver (language/compiler version/profile/target)
  -> isolated native/cross build runner
  -> artifact collector
  -> format loader extractor (ELF / PE+CodeView / Mach-O)
  -> debug extractor (DWARF / PDB / dSYM)
  -> function normalizer
  -> versioned CFG extractors
  -> reproducibility replay
  -> validator
  -> metadata Parquet + payload shard packer
  -> HF dry-run plan
  -> explicit publish step
```

## Runner pools

### Linux

Default for ELF and cross-compilation where the project/toolchain supports it. Build execution should be network-disabled after dependency acquisition. Containers/images are pinned by digest.

### Windows

Required for representative MSVC builds and native PDB/CodeView fidelity. Use disposable workspaces/VMs or equivalent isolation. Store exact Visual C++ toolset/compiler version and linker version in every build manifest.

### macOS

Default for Apple-target Mach-O/dSYM builds. Store Xcode/clang build identity and target SDK identity. Do not package or redistribute Apple SDKs inside public dataset/toolchain payloads.

## Scheduling model

A build job is created only after four identities resolve:

1. immutable project source (`repo + commit + tree hash`),
2. exact toolchain version/build identity,
3. optimization profile,
4. target ID/triple.

The abstract matrix `variant_id` is useful for planning. The final `build_id` additionally includes source and exact toolchain identity; it is therefore content/provenance stable and does not depend on job timestamps.

## Compiler-version strategy

Do not use a single rolling `latest` compiler in published records. `configs/toolchains.json` will contain explicitly locked versions/images. The large corpus should intentionally sample historical compiler versions as well as current ones so that evaluation can measure decompiler robustness against code-generation drift.

Recommended selection strategy per compiler family:

- several historical major releases;
- dense coverage of recent majors/minors;
- exact patch/build string retained even when analysis groups by major/minor;
- old toolchains may be marked `legacy` and run only on compatible runner images.

The exact version list must be verified and committed separately; the foundation config intentionally leaves it unresolved rather than inventing version numbers.

## Optimization strategy

The dataset should exceed the legacy `O0/O2/O2-noinline` shape without exploding into a useless Cartesian product.

Use three layers:

- **anchors**: canonical optimization profiles for broad dataset coverage;
- **paired toggles**: no-inline, LTO, codegen-unit/panic variants, etc.;
- **stress/full-cross**: opt-in campaigns for a selected project/toolchain subset.

Record rejected/unsupported combinations as structured `skipped` results. Never silently map an unsupported flag to a different profile.

## Loader/debug extraction contract

### ELF

Persist loader structure, symbols/relocations summary and DWARF verification/extraction metadata. Split debug artifacts are linked by immutable hashes.

### PE/COFF

Persist PE loader structure and debug-directory CodeView records. Store the PDB as a separate artifact and extract low-level PDB/CodeView metadata with a pinned tool. The PE-to-PDB link (signature/GUID/age/path metadata where present) must be represented explicitly.

### Mach-O

Persist fat/universal container metadata and one normalized record per architecture slice. Preserve UUID/load commands/segments/sections/dylib and dyld metadata plus dSYM/DWARF relation. UUID consistency between binary and dSYM is a qualification check.

## CFG strategy

CFG is versioned derived data, not raw identity.

Machine CFG should support multiple extractors (for example Fission plus an independent baseline) and record extractor/version/configuration. Disagreements are data, not automatically errors. Compiler/source CFG is stored separately when an appropriate frontend/IR path exists.

This separation permits future DecBench metrics to compare recovered CFGs against a compiler/source-derived reference without contaminating the raw corpus.

## Sharding

Logical artifacts use content hashes; physical Hugging Face layout uses large shards. A shard index maps:

`artifact_sha256 -> shard_name + member_name + size + media_kind`

Metadata rows stay queryable as Parquet. This keeps Hub file counts bounded while retaining direct artifact lookup.

## Security boundary

- dependency acquisition and build execution are distinct phases;
- network off during build by default;
- no generated binary execution;
- resource/time/process limits per job;
- source repository scripts are untrusted;
- secrets/tokens are never mounted into build sandboxes;
- publish credentials exist only in the final uploader process, never builders.
