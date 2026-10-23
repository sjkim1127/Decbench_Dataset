# Balanced cross-platform corpus campaign

## Targets, not current measurements

`configs/coverage-policy.json` specifies Linux/ELF 40%, Windows/PE 35%, macOS/Mach-O
25%. Within Linux: x86-64 50%, ARM64 30%, x86 15%, ARMv7 5%; Windows: x86-64 55%,
x86 30%, ARM64 15%; macOS: ARM64 60%, x86-64 40%.

The denominator is distinct successful build variants. Replay attempts, debug
files and stripped derivatives are not extra samples. Report project families,
source functions and machine functions independently. Prioritize new repository
families before more variants from already overrepresented projects. Weights are
an initial acquisition policy, not a measured property or reason to discard valid
data. Unsupported language/target cells remain explicit. A 10,000-build allocation
is a planning example, not a claim that 10,000 artifacts have been collected:

```sh
python -m decbench_dataset plan-coverage configs/coverage-policy.json --budget 10000
```

## GitHub discovery

`configs/research/github-candidates.json` locks 48 source projects/tool candidates
across all nine languages plus obfuscators. Each includes the observed full commit,
repository URL, detected license and license-blob identity where available. These
are discovery records, not a compatibility or redistribution approval claim.
`configs/native-projects.json` separately admits six reviewed direct compilation
recipes (cJSON, pugixml, inih, xxHash, tinyxml2, LZ4) and pins license-file SHA-256.
Retain all per-file upstream license notices in source snapshots.

## Execution

`.github/workflows/collect-native.yml` runs two profiles and two fresh attempts for
each admitted project on seven OS/architecture cells. Windows-2022/MSVC compiles
x64, x86 and cross-target ARM64; macOS clang builds separate ARM64 and x86-64
Mach-O slices with dSYM UUID checks; Linux clang runs on x86-64 and ARM64 workers.
ARM64 Windows binaries built by x64 MSVC are cross builds, not native execution.
32-bit Linux and ARMv7 remain quota deficits until an appropriate sysroot is pinned.

The native collector invokes only direct compiler/binutils commands and does not
run upstream build scripts or generated binaries. It captures ordered argv,
stdout/stderr, driver hashes, companion tool hashes, SDK/runner image versions,
allowlisted environment, source archives, binaries and debug files. Hosted images
are rolling installations: version details are observed per record rather than
inferred from labels. Native networking is not blocked; this limitation is recorded.
No HF credentials enter collection workers. Local and hosted results are raw until
language-specific debug/function/ABI qualification is performed.

PE/PDB presence and CodeView raw evidence are currently retained, without claiming
GUID/age matching qualification. Mach-O dSYM UUIDs are checked. Reproducibility
results preserve mismatches (including PDB/PE timestamps and debug paths), rather
than silently normalizing them. No generated program is executed.

## Source-backed obfuscation

Target 85% clean / 15% obfuscated as a separate initial policy. Every obfuscated
sample must link to original source and clean baseline and retain exact tool commit,
compiler, pass sequence, configuration, seed, transformed source/IR where available
and mapping/semantic-validation status. Stripping and optimization are distinct
attributes, not obfuscation. The original/obfuscated pair stays in one split group.

Candidates: [garble](https://github.com/burrowers/garble),
[OLLVM](https://github.com/obfuscator-llvm/obfuscator),
[O-MVLL](https://github.com/open-obfuscator/o-mvll),
[ollvm17](https://github.com/DreamSoule/ollvm17). Hikari is archived; record this
instead of assuming current toolchain support. O-MVLL is aimed at Android/iOS;
desktop target support needs a capability pilot. No obfuscated corpus artifact is
claimed from candidate discovery alone.

Sources checked 2026-10-23:
[GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[MSVC Windows containers](https://learn.microsoft.com/en-us/visualstudio/install/build-tools-container?view=visualstudio).
