# Cross-platform acquisition report — 2026-10-23

Final hosted campaign: https://github.com/sjkim1127/Decbench_Dataset/actions/runs/39828247074

All seven jobs succeeded. Six upstream library projects × two optimization
profiles × seven target cells = 84 distinct build variants and 168 replay attempts.
The admitted projects are cJSON, pugixml, inih, xxHash, tinyxml2 and LZ4.

| OS / format | Architectures actually collected | Variants | Attempts |
|---|---|---:|---:|
| Linux / ELF | x86-64, ARM64 | 24 | 48 |
| Windows / PE + PDB | x86, x86-64, ARM64 | 36 | 72 |
| macOS / Mach-O + dSYM | x86-64, ARM64 | 24 | 48 |

Observed compilers: Ubuntu clang 18.1.3, Apple clang 17.0.0 build
`clang-1700.0.13.5`, MSVC 19.44.35229 (target-specific drivers).
Windows ARM64 and macOS x86-64 are cross builds. No generated program was executed.
Full compiler version output, including MSVC `/Bv` stderr, is retained per record.

Both Linux cells had 12/12 identical binary-hash replay pairs. Each Windows and
macOS cell had 0/12 identical binary-hash replay pairs; timestamps, UUID/debug paths
and other differences remain visible in raw artifacts. Do not call the native
campaign byte reproducible. Replay manifests retain per-artifact comparisons.

Earlier hosted runs `39827709195` and `39827972520` exposed Windows license
checkout-EOL handling and a VsDevCmd ARM64 target-selection issue. The corrected
final campaign is the published seven-cell campaign; earlier successful duplicate
jobs are not added to its variant count. Acquisition errors before compilation
remain in those CI logs rather than in the native build-attempt rows.

## Source-backed obfuscation

BurntSushi/toml `cmd/tomlv` at commit
`d733fc535e4a9f3c454e421a87b90ade5d49bf31` was built clean and with garble v0.15.0,
using Go 1.25.5 and a fixed seed, for Linux x86-64, Windows x86-64 and macOS ARM64.
All six final builds succeeded. Original source, transformed Go source, build
commands/logs, standard-library license and exact target/tool provenance are kept.

Garble's release tag is an annotated tag: tag object
`05caa14fcc5401e350f6babc935d78282eab96af` resolves to compiler-tool commit
`6dab979d1cae7c703aeff286f1c70319c34a6c35`. The current manifests distinguish them.
This pilot does not claim semantic-equivalence testing, function mapping, or
replay reproducibility. All records remain raw and unqualified.

## Storage and next coverage deficits

Public dataset: https://huggingface.co/datasets/sjkim1127/decbench-multilang-corpus

- `native/platforms-2026-10-23/`: 84 variants / 168 attempt rows; Parquet,
  deterministic per-target tar shards, indexes and checksums.
- `obfuscated/go-garble-2026-10-23/`: three clean/obfuscated pairs, sources,
  transformed sources, metadata and checksums.
- Existing initial Docker and local macOS pilots are separate campaigns.

The 40/35/25 OS mix is a target policy, not the current measured distribution.
Initial equal-sized target cells yield Linux 28.6%, Windows 42.9%, macOS 28.6%.
Linux x86/ARMv7, musl and historical compiler versions remain deficits. The 48
GitHub candidates are discovery records, not 48 built projects. Rust, Zig, Swift,
Fortran, D and Nim still need executable collection adapters.
