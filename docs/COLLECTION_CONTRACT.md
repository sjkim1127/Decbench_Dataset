# Detailed collection contract (v0.2)

Scope: C, C++, Rust, Go, Zig, Swift, Fortran, D, Nim. The raw dataset is independent
of DecBench scoring. This is an implementation contract, not a claim that every
field or language adapter has already been collected.

## Target is separate from host

Record build host, container userspace, compiler host, requested target, observed
object target and deployment/runtime requirements separately. A Linux container
shares a kernel with its host; `/etc/os-release` is not a target minimum OS.

Required target dimensions:

| Dimension | Required detail |
|---|---|
| OS | family, distribution/release/build where applicable, target deployment minimum, evidence/status |
| Architecture | ISA, bitness, endianness, CPU baseline, tuning CPU, enabled/disabled ISA features |
| ABI | ABI name/version, data model, calling convention, float ABI, object ABI flags |
| Runtime | libc implementation/version, dynamic interpreter, C++ standard library and ABI mode, symbol-version requirements |
| SDK/sysroot | version/build, package manifest or immutable image digest, content identity, deployment flags |
| Object | ELF/PE/Mach-O, object type, image base/load model, build-id/UUID, imports/exports, relocations |

Capture `_GLIBCXX_USE_CXX11_ABI`, exceptions/RTTI, packing/alignment, wchar/enum
size, PIC/PIE, visibility, TLS model and sanitizer settings when applicable.
Preserve unknown values as `status=not-collected/not-qualified/unsupported` with
reasons. A target triple alone does not satisfy the ABI contract. Compiler built-in
macros and effective-option dumps are evidence, not inferred compatibility tests.

## Compiler and full invocation

- Compiler driver, frontend/backend, assembler, linker, archiver, strip/debug tools:
  exact raw versions, configuration output, executable hashes, package identities.
- Ordered argv arrays per invocation, cwd, exit status, stdout/stderr and relevant
  environment. Capture compile and link steps independently. Preserve repeated flags
  and ordering; a profile label or `compile_commands.json` alone is insufficient.
- Preserve response-file bytes/hash and their expansion order, generated build
  files, build-system/cache/tool versions and dependency locks/vendor hashes.
- Record requested options and compiler-reported effective settings separately.
  Classify options as explicit, driver-injected, toolchain-default, or unknown.
- For build systems, collect child process evidence using an appropriate tracing
  adapter; if only verbose driver logs exist, state that limitation explicitly.
- Keep originals and normalized representations. Never silently drop an unsupported
  option or transform a failed build into a different successful profile.

Pilot status: direct GCC/G++ driver argv plus verbose child-command logs and
effective-option dumps; no execve trace or normalized child argv table yet.

## Language-specific fields

| Language | Additional provenance |
|---|---|
| C/C++ | standard dialect, extensions, macros/includes, template instantiations, C++ ABI/stdlib, exceptions/RTTI |
| Rust | rustc verbose identity, Cargo.lock/features, edition, target specification, panic, codegen units, LTO, mangling, overflow checks |
| Go | `go version`, `go env` allowlist, module/sum/vendor graph, GOOS/GOARCH/GOAMD64 etc., cgo toolchain, gcflags/asmflags/ldflags, build tags, buildinfo/pclntab |
| Zig | compiler/backend identity, target/CPU/features, build mode, libc, safety settings, build.zig/zon and dependency hashes |
| Swift | swiftc/frontend identity, language mode, SDK/deployment target, module/interface, optimization/WMO, concurrency/library-evolution settings, runtime and C interop |
| Fortran | compiler and dialect, fixed/free form, module files, integer/real kind defaults, name mangling, array ABI, BLAS/LAPACK/runtime dependencies |
| D | DMD/LDC/GDC identity, language version, runtime/Phobos, BetterC, GC/bounds/assertions, templates, backend options |
| Nim | Nim identity, backend (C/C++), memory manager, generated sources/cache, native compiler/linker identity and argv, release/danger checks |

Generated C/C++ from Nim is a derived artifact with its own identity; preserve the
original Nim and intermediate source instead of labeling the sample as C.
Mixed-language builds need per-translation-unit language/toolchain provenance.

## Identity, evidence and failure denominator

An abstract variant includes the complete target/profile specification. A build
identity includes source snapshot, dependencies, toolchain identity, target detail,
options, environment and runner identity; exclude timestamps and volatile CPU
telemetry. Replay attempts retain separate artifact hashes and raw logs.

Preserve failed, skipped and unsupported combinations with the exact reason and
attempt denominator. Pilot packaging publishes successful builds only; keep failed
raw evidence locally/CI and add a separate campaign-attempt table before scaling.

Qualification is independent: raw DWARF/PDB/dSYM is not a validated source-function
mapping. Preserve inlining, specialization, folding and discontinuous ranges.
Future Multi lang DecBench can consume versioned build/binary/function IDs and
readiness maps without changing source artifacts or claiming unsupported metrics.

## Campaign execution

1. Verify upstream licenses and fixed source commits.
2. Acquire pinned toolchains/dependencies outside the build sandbox.
3. Build offline in disposable Docker/native workers, save all evidence.
4. Repeat in fresh writable workspaces and compare exact artifact hashes.
5. Validate formats/debug relationships, then qualify mappings separately.
6. Package Parquet indexes plus deterministic payload shards, checksum and publish.

Start with anchor profiles; add historical compiler versions, paired toggles and
target/ABI variants in resumable campaigns. Long campaigns should use bounded jobs,
an append-only attempt ledger, shard checkpoints and retry budgets. Do not rely on
one workflow staying alive indefinitely. Windows/MSVC and macOS SDK builds require
native workers; the supplied workflow currently covers the Linux C/C++ pilot only.

The package uploader runs outside build workers. No authentication environment is
passed into Docker. Public pilot location authorized by the user:
`sjkim1127/decbench-multilang-corpus`.

References: [LLVM debug metadata](https://llvm.org/docs/SourceLevelDebugging.html),
[Nim compiler](https://nim-lang.org/docs/nimc.html),
[HF cards](https://huggingface.co/docs/hub/datasets-cards),
[Actions workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
