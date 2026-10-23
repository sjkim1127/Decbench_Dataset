# Initial public pilot — 2026-10-23

Public dataset: https://huggingface.co/datasets/sjkim1127/decbench-multilang-corpus

Verified revision: `3af34739021c76a867dbc314895be14cb880ce5b`.

## Measured scope

- Real upstream projects: cJSON v1.7.19 and pugixml v1.15, fixed full commit IDs.
- Languages actually collected: C and C++.
- Profiles: O0, O2, O3, Os; 8 variants, 16 offline Docker builds.
- Artifacts: x86-64 Linux ELF shared libraries from one translation unit each,
  object files, stripped derivatives, separate DWARF, raw ELF/DWARF logs and source snapshots.
- Compiler: observed GCC/G++ 13.5.0, pinned GCC image digest in `configs/pilot.json`.
- All 8 variants reproduced identical unstripped binary, stripped binary, separate
  debug and object hashes across two fresh writable containers.
- Both attempts passed ELF64-LE/ET_DYN/x86-64 checks, allocated-section equality
  after stripping, DWARF presence and GNU debuglink filename/CRC validation.
- Payload archive: 394 members, individually re-read and SHA-256 verified.
- HF download verification: 16 checksum-listed files, 130,536,212 bytes,
  downloaded from the exact revision and independently hashed; repository public.
- Tooling tests: 8 passed; matrix validation, Python compilation and diff whitespace checks passed.

## Explicit limits

The nine-language policy is configured, but the remaining seven language adapters,
native Windows/macOS builds and additional target architectures remain pending.
The local pilot uses Docker's linux/amd64 platform on an Apple Silicon host;
this is not native x86-64 hardware validation. Runtime minimum-OS/ABI compatibility
is unqualified. Libraries are not whole upstream project builds or upstream test
suite runs. Generated corpus programs were never executed.

Source-function qualification, normalized compiler child argv/execve tracing,
machine CFG extraction and semantic scoring are pending. All records are raw,
`qualified=false`, with empty metric-readiness maps. The Actions workflow is
written locally and has not been dispatched remotely.

The current collector refuses existing attempt directories; resumable campaign
scheduling and multi-shard rotation are subsequent work. No DecBench code changed.
