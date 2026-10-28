# Original upstream language products — 2026-10-23

This batch adds five real open-source products, not dataset-authored programs or
collector-supplied wrappers. The mandatory policy is in `UPSTREAM_ONLY.md`.

| Language | Actual upstream product | Frozen commit | Observed target cells | Profiles | Attempts |
|---|---|---|---|---|---:|
| Swift | yonaskolb/Mint | 3ee0f63e6be99cb655a1c567d283aa51a294ffc5 | macOS ARM64 Mach-O | debug/release | 4 |
| Zig | zigtools/zls 0.15.0 | ce6c8f02c78e622421cfc2405c67c5222819ec03 | macOS ARM64, Linux ARM64, Windows x86-64 | Debug/ReleaseSafe | 12 |
| Fortran | jacobwilliams/json-fortran | d9ed2e4ee53745f4ed98d7536e17bee5198aa3b0 | Linux ARM64 ELF shared library | opt0/opt2 | 4 |
| D | CyberShadow/DustMite | ab68756bab23e09328a9b906f7c7b44bfa7bae25 | Linux ARM64 ELF executable | opt0/opt2 | 4 |
| Nim | nim-lang/nimble v0.14.2 | 3575fd54a890d910ace56678aa74b4237d604175 | Linux ARM64 ELF executable | opt0/opt2 | 4 |

All 28 final attempts succeeded: 14 distinct variants and two attempts per variant.
All 28 preserved the original tracked program-source bytes. Dataset-authored
programs: 0. Collector-supplied program entrypoint wrappers/harnesses: 0.
The products' own build manifests and compiler/upstream code generators are build
tooling, not extra corpus products. No final corpus product was executed.

## Source and dependency provenance

Every product retains its original Git archive, full commit/tree identity,
tracked-file hashes, upstream entrypoint, reviewed license file/hash and build
commands. Licenses: Mint/ZLS MIT, JSON-Fortran/Nimble BSD-3-Clause, DustMite BSL-1.0;
the exact upstream notices remain in source snapshots. Generated Nim C and Fortran
build/module metadata are explicitly derived, not substituted original sources.

Swift dependencies retain resolved revisions and original checkout sources. Zig
dependencies retain upstream content hashes and original package-cache sources.
Nimble requires Nim compiler support sources: nim-lang/Nim v1.6.14 at
`71ba2e7f3c5815d956b1ae0341b0743242b8fec6`, retained as a dependency with its MIT
license and source identity. No handwritten replacement for compiler/nimblecmd
was introduced. Runtime/standard-library source coverage is not universally complete.

## Toolchains, replay and limitations

Observed toolchains: Apple Swift 6.2.4 (SDK 26.2), Zig 0.15.2, GNU Fortran 13.3.0,
LDC 1.36.0 (DMD 2.106.1/LLVM 17.0.6), Nim 1.6.14. Container records retain exact
image/executable identities and package lists; native records retain compiler/SDK
versions, executable identities and full verbose command evidence.

The Fortran/D/Nim builders are resource-limited Linux containers with read-only
upstream mounts and build networking disabled. Native Swift/Zig builds deny
network access using macOS sandbox-exec. Swift's inner manifest sandbox is disabled
to avoid nesting, while the outer network-denying sandbox remains active.

Six binary replay pairs matched exactly (Fortran/D/Nim); eight did not
(Swift/Zig). Preserve the differences and do not label the latter byte-reproducible.
Source/function qualification, semantic execution and metric readiness remain false.
The Zig Windows target is GNU ABI, not an MSVC compilation.

## Acquisition history

Sixteen earlier collection attempts failed before producing an accepted primary
product: missing matching Nim compiler source, a Nim code-generation-only flag,
Swift dependency fixture-symlink copying, and nested Swift manifest sandboxing.
Their records/diagnostics remain history. They were fixed in collection tooling
or by fetching original upstream dependencies, without editing program bodies.

Eight successful ZLS builds encountered an unsupported Zig objcopy operation.
LLVM objcopy produced debug/stripped derivatives from those same original binaries,
whose hashes were verified unchanged. Original failure records and recovery tool
identity/commands remain in `postprocess-history` and the raw manifests. These
recoveries are not additional compiler attempts.

## Storage and the supplied example

Public path:
`opensource/languages-batch1-2026-10-23/` in
https://huggingface.co/datasets/sjkim1127/decbench-multilang-corpus.

The package has per-language Parquet rows, `configs/<language>/manifest.json`
self-contained source/binary/shard indexes, payload archives, member SHA-256
indexes, replay comparisons and checksums. The supplied noelo-lab example was
inspected at revision `815eb96f130b6d2ef7fa600e04669bf20139bf27` for packaging
structure. Its corpus, scores and CFGs were not copied or fabricated here.

Together with existing upstream C/C++/Rust/Go acquisition, all nine planned
languages now have raw compiled product evidence. This is not a claim of full
nine-language OS/architecture coverage or benchmark readiness. Tooling tests: 13
passed, including rejection of authored/harness inputs and modified upstream code.
