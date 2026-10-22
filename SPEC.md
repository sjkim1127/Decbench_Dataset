# Dataset Specification (v0)

Status: **foundation draft**. Every externally sourced claim in this document must eventually carry a `[verified]` marker and source; design choices are marked `[design]`.

## 1. Purpose

[design] Build a large, reproducible corpus of compiled binaries and ground-truth build/debug artifacts for C, C++, Rust, Go and Zig. The corpus is intended for future DecBench language expansion and internal Fission development. v0 stores corpus material and provenance only; it does not define decompiler scores.

## 2. Corpus lifecycle

Each record moves independently through:

- `raw`: build completed and artifact manifest exists.
- `qualified`: source/debug/function identity has passed a language-specific qualification pipeline.
- `eval_ready`: a named metric/version declares the record eligible for evaluation.

`qualified` and `eval_ready` default to false. Unknown or ambiguous mappings must abstain rather than guess.

## 3. Canonical identity

### 3.1 Binary

`binary_sha256` is the content identity for an exact binary artifact.

### 3.2 Machine function

[design] The cross-format machine-function key is not hard-coded to DWARF `low_pc` because Windows PDB/CodeView and stripped artifacts require a more general representation.

Canonical tuple:

`(binary_sha256, address_kind, start_address)`

where `address_kind` is one of `rva`, `va`, or `file_offset`. Prefer `rva`/image-relative virtual address whenever a loader can define it unambiguously. Debug identities are provenance fields, not replacements for the machine address:

- DWARF: DIE offset, `DW_AT_low_pc`, ranges, linkage name.
- PDB/CodeView: module/compiland, section+offset and resolved RVA, symbol/type record identifiers.
- Mach-O+dSYM: UUID, DIE offset, low_pc/ranges.

If multiple source entities fold to one address (ICF or equivalent), the machine function remains one function and source mappings are represented as aliases/many-to-one provenance.

## 4. Required source and build provenance

Every included project/build must preserve:

- repository URL and immutable commit SHA;
- source snapshot reference and source tree hash;
- detected SPDX license plus license-review status;
- lockfiles/vendor metadata where applicable;
- exact build commands and environment variables relevant to compilation;
- toolchain family, exact version string, parsed major/minor/patch when possible, target triple and executable path/hash where available;
- runner OS/image identity and container image digest where containers are used;
- deterministic build ID generated from normalized inputs.

A compiler version is a first-class dataset axis. Aggregation may bucket by major/minor, but the raw record always retains the exact version/build string.

## 5. Required binary artifacts

For each successful build variant retain, when the platform/toolchain supports them:

1. unstripped binary;
2. stripped derivative;
3. external debug artifact (`.debug`/`.dwo`/`.dwp`, PDB, or `.dSYM`);
4. loader metadata manifest;
5. normalized symbol/function table;
6. versioned CFG extraction output(s);
7. build manifest and hashes for every artifact.

Produced binaries are data and MUST NOT be executed as part of corpus generation.

## 6. Object formats and loader metadata

### ELF

Capture ELF class, endianness, machine, type, preferred/load-bias model, program headers, sections, build-id, dynamic dependencies, relocations summary and debug linkage information.

### PE/COFF

Capture machine type, image base, sections, data directories, imports/exports, relocations summary, PE debug directory, CodeView record (`RSDS`/equivalent), PDB path identifier metadata and resolved PDB artifact relation.

PDB and CodeView are both preserved: CodeView records in the PE/object data are provenance linking the image to PDB information; the PDB is stored as a distinct debug artifact.

### Mach-O

Capture architecture/fat-slice identity, UUID, filetype, segments/sections, load commands, dylib dependencies, exports/bind/rebase/chained-fixup summaries, code/data-in-code metadata where available and dSYM relation. Universal binaries are represented as a container plus per-architecture slices.

## 7. Function table minimum fields

Metadata is stored in Parquet-compatible rows. Required logical fields include:

- `schema_version`, `binary_sha256`, `function_uid`;
- `address_kind`, `start_address`, optional `end_address`, `size`;
- `image_base`/load-bias metadata where meaningful;
- mangled and demangled names as optional labels only;
- source file and line/range mappings;
- debug identity/provenance records;
- `origin`: `project`, `stdlib`, `runtime`, `dependency`, `generated`, or `unknown`;
- inlining and folding/ICF indicators;
- `has_source_body`;
- `qualified`, `qualification_version`;
- metric-specific readiness map, default empty/false.

Only records explicitly classified as `origin=project` may become scoring candidates by default.

## 8. Build matrix

The matrix is intentionally richer than legacy O0/O2/O2-noinline datasets.

### C / C++ GNU-like profiles

Candidate optimization anchors include `O0`, `Og`, `O1`, `O2`, `O3`, `Os`, compiler-supported `Oz`, and `Ofast`/equivalent where available. Independent dimensions include inlining policy and LTO mode. Unsupported flag combinations are recorded as skipped, not silently rewritten.

### MSVC / clang-cl profiles

Candidate anchors include `/Od`, `/O1`, `/O2`, `/Ox` where accepted by the selected toolset, with explicit inlining and `/GL` dimensions. Debug profiles must retain PDB+CodeView using the exact flags selected by the toolchain adapter.

### Rust

Cover Cargo/rustc optimization levels `0/1/2/3/s/z`, LTO modes where supported, codegen-unit policy, panic strategy, debug info and symbol-mangling metadata. Monomorphized functions are not deduplicated by source name.

### Go

Capture exact Go toolchain version and both normal optimized builds and diagnostic no-optimization/no-inline variants where supported. DWARF/pclntab presence is recorded independently from the stripped derivative.

### Zig

Cover `Debug`, `ReleaseSafe`, `ReleaseFast`, and `ReleaseSmall`; capture Zig version and backend/toolchain metadata exposed by the build.

### Explosion control

[design] Do not materialize the full Cartesian product by default. The matrix engine supports anchor profiles plus pairwise/curated combinations. Full-cross builds are an explicit opt-in experiment.

## 9. Targets and architectures

Primary matrix:

- Linux/ELF: `x86`, `x86_64`, `armv7/ARM32`, `aarch64/ARM64`.
- Windows/PE-COFF: `x86`, `x86_64`, `aarch64` where supported by the toolchain/project.
- macOS/Mach-O: `x86_64`, `aarch64`.

Secondary/extensible targets may include `riscv64`, `ppc64le`, `mips*`, BSD targets and others after a pilot validates toolchain and loader support. Architecture support is capability-driven; unsupported project/target pairs are recorded as skips.

## 10. CFG artifacts

CFG outputs are derived artifacts and MUST include extractor identity/version/configuration.

Namespaces:

- `derived/cfg/machine/<extractor-version>/...`: machine-code CFG, potentially from multiple independent extractors.
- `derived/cfg/compiler_ir/<producer-version>/...`: compiler IR/MIR/SSA CFG when a toolchain can emit it reproducibly.
- `derived/cfg/source/<frontend-version>/...`: source-level CFG where a language frontend exists.

No single reverse-engineering tool's recovered CFG is automatically treated as ground truth. Raw debug/build artifacts remain the authoritative provenance layer.

## 11. Split and leakage policy

- Split by project/repository family, never by function.
- Keep forks/mirrors and vendored copies in the same split using provenance and content similarity.
- Deduplicate exact binaries by SHA-256.
- Track normalized function-body hashes for analysis, but do not collapse distinct provenance records blindly (important for generic/template instantiations and ICF).
- Maintain a date-based holdout policy for future evaluation snapshots.

## 12. Safety

- Repository build scripts are untrusted code.
- Linux builders run sandboxed with network disabled during the build phase, resource limits and read-only base images where practical.
- Dependency acquisition is a separate controlled phase; locked/vendorable dependency graphs are preferred.
- Windows and macOS native runners require equivalent isolation and disposable workspaces.
- Never execute produced binaries.
- Malware is excluded from default corpus discovery. Any future malware collection must use a physically/logically separate gated quarantine dataset and policy.

## 13. Native runner constraints

[design] Full coverage cannot be implemented as Linux Docker alone.

- MSVC/PDB qualification requires Windows-native toolchains/runners for representative builds.
- Apple SDK/Xcode licensing and Mach-O/dSYM fidelity make a native macOS runner the default for Apple targets; do not redistribute Apple SDKs in public container images.
- Linux and many cross targets can use pinned containers.

## 14. Hugging Face packaging

[verified 2026-10-23] Hub guidance recommends keeping total repository file counts below ~100k where possible, fewer than 10k entries per folder, and merging many small files into larger Parquet/WebDataset-style artifacts. Large payloads should be sharded rather than represented as millions of individual Hub files.

Dataset layout target:

- Parquet metadata shards for viewer/query access;
- content-addressed tar/WebDataset-style payload shards for binaries, debug artifacts, source snapshots and derived CFGs;
- SHA-256 shard manifests mapping logical artifact IDs to shard/member paths;
- `schema_version` on every logical record;
- upload pipeline is dry-run by default.

## 15. Reproducibility

Each project/profile is built twice in fresh workspaces. Report separately:

- identical binary hash;
- identical debug artifact hash;
- normalized-equivalent metadata;
- known nondeterministic fields and normalization policy.

A non-reproducible build may remain in `raw` with an explicit reproducibility status; it cannot silently be called deterministic.

## 16. v0 acceptance criteria

M0:

- specification, schemas, matrix policy and safety/architecture docs exist;
- matrix validates deterministically.

M1:

- adapters can emit normalized build manifests;
- matrix expansion produces stable build IDs;
- format-specific extractor interfaces exist for ELF, PE/CodeView/PDB and Mach-O/dSYM;
- no produced binary execution is required.

M2 pilot:

- 10-20 representative projects per language where practical;
- exact compiler-version distribution reported;
- target/optimization success and skip reasons reported;
- function/origin/CFG metadata manually sampled and audit error rates documented.
