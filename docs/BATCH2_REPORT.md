# Raw collection batch 2 — 2026-10-23

This is corpus acquisition only. No DecBench eligibility, metric validity,
function mapping or semantic correctness is asserted. All qualification flags
remain false and final corpus programs are never executed.

## New source projects

Native C/C++: tidwall/hashmap.c, tidwall/btree.c, tidwall/json.c, antirez/sds,
udp/json-parser, richgel999/bc7enc_rdo. Fixed commits, source archives and reviewed
license hashes are in `configs/native-projects-batch2.json` and the payloads.

Full Rust CLIs: BurntSushi/ripgrep and sharkdp/hyperfine, using the pinned source
commits from `configs/research/github-candidates.json`. Their source, Cargo.lock,
vendored dependency source/licenses and build evidence are retained.

## Native platform batch

Hosted run: https://github.com/sjkim1127/Decbench_Dataset/actions/runs/39903835408

| Cell | Profiles | Attempts | Successful | Failed |
|---|---|---:|---:|---:|
| Linux x86-64 | O0/O2/O3/Os | 48 | 48 | 0 |
| Linux ARM64 | O0/O2/O3/Os | 48 | 48 | 0 |
| Windows x86 | O0/O2 | 24 | 16 | 8 |
| Windows x86-64 | O0/O2 | 24 | 16 | 8 |
| Windows ARM64 | O0/O2 | 24 | 16 | 8 |
| macOS x86-64 | O0/O2 | 24 | 24 | 0 |
| macOS ARM64 | O0/O2 | 24 | 24 | 0 |
| Total | | 216 | 192 | 24 |

Successful distinct variants: 96. Failed distinct variants: 12. Both replay
attempts and the source/compiler diagnostics are preserved, including failures.
MSVC rejected btree's atomics under the current C dialect and SDS's packed-struct
syntax. These are failed original-source recipes, not silently patched variants.
Their failed hosted jobs are retained as acquisition evidence, not hidden by a
green compatibility claim. A local macOS smoke campaign also completed 24/24.

The first and second hosted C/C++ campaigns together contain 180 successful
variants: Linux 72 (40%), Windows 60 (33.3%), macOS 48 (26.7%). These figures exclude
local pilots, Go and Rust campaigns and count neither replay as an extra variant.

## Rust CLI batch

Pinned Docker image:
`rust@sha256:48b7f435b8fc6378ce43b44f15e3a47fd8919b2825f835c39bd4bd3da50af5b8`.
Observed Rust 1.99.1, Cargo 1.99.1, Linux ARM64 GNU target. Toolchain resolution is
explicitly pinned to installed `1.99.1`; actual rustc/Cargo executable hashes are
separate from rustup proxy hashes.

Each project compiled at opt-level 0 and 2, with debug info and two fresh offline
build workspaces: 8/8 attempts succeeded, 4 distinct variants. All four pairs had
identical unstripped, stripped and separate-debug hashes. ELF machine headers were
checked. Cargo verbose/JSON logs retain compiler invocations and crate artifacts.

Dependency acquisition is a separate network-enabled phase using locked Cargo
vendoring. Builds use frozen dependency resolution, read-only source/vendor mounts,
network disabled and memory/CPU/process limits. Cargo build scripts and procedural
macro tools execute as compiler tooling inside this container. Final ripgrep and
hyperfine binaries are never executed. Standard-library sources are not separately
bundled; the exact compiler/toolchain identity is retained for their provenance.

Earlier collection infrastructure errors are preserved in `history/`: one
preparation failure from a rustup channel lookup and eight Cargo configuration
failures before source compilation. The working campaign selects the installed
version and mounts Cargo configuration below a directory rather than filesystem
root. These earlier failures are not counted as successful builds.

## Published paths

- `native/platforms-batch2-2026-10-23/`: 216 raw attempt rows, successful and failed,
  Parquet indexes, per-target tar shards, source/debug artifacts and checksums.
- `rust/cli-batch1-2026-10-23/`: eight raw attempts, source/vendor archives,
  per-project payload shards, replay comparisons, failure history and checksums.

Dataset: https://huggingface.co/datasets/sjkim1127/decbench-multilang-corpus

This batch adds 8 source projects and 100 successful distinct build variants.
Raw collection currently has executable C/C++, Go and Rust paths. Zig, Swift,
Fortran, D and Nim still need executable collection adapters and pilot evidence.
