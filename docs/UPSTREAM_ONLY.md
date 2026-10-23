# Upstream-only corpus admission

The user requires real open-source projects, rather than dataset-authored programs.
This is a mandatory corpus-admission constraint, separate from metric readiness.

Primary program code must come from a reviewed public upstream repository at a
full immutable Git commit. Retain the source archive/tree identity, license file
and hash, tracked source-file hashes, original product entrypoint/build target,
toolchain, exact ordered commands and outputs. Primary products in this campaign
are Mint, ZLS, JSON-Fortran, DustMite and Nimble. No collector-created main function,
API wrapper, scoring fixture or sample program is admitted as corpus program code.

`scripts/upstream_sources.py` rejects synthetic origins, dataset-authored programs,
collector-supplied harnesses, unresolved commits and missing license evidence.
It refuses dirty upstream checkouts and compares tracked program source bytes
before/after builds. Publishing requires that this check passed for every primary
successful artifact. Tooling tests stay outside corpus paths and are not samples.

Generated files from upstream build systems or compilers (Nim's C backend, Zig
build options, Swift package manifests, Fortran module/build metadata) are derived
evidence. They do not replace original source or become extra primary samples.
Original-source obfuscation retains the upstream clean baseline and transformed
source lineage. Dependencies have their own original repository/version/hash or
package-lock/content-hash evidence and retain upstream license notices.

The Nimble build requires `compiler/nimblecmd` from matching Nim 1.6.14 source;
the dependency is fetched from nim-lang/Nim, never replaced with a handwritten
stub. Build/derivation failures remain history, rather than synthetic fallback
corpora or guessed successful mappings. Final corpus programs are not executed.

## Reference dataset inspection

The user supplied https://huggingface.co/datasets/noelo-lab/decbench-dataset as an
example. Its card and `configs/sample-set/manifest.json` were inspected at revision
`815eb96f130b6d2ef7fa600e04669bf20139bf27`. The useful packaging pattern is a
self-contained index connecting real project sources, binaries and downloadable
configurations. This collection adds per-language indexes with source/binary/shard
identities and metadata. No source CFGs, decompilations, scores, function counts or
qualification are copied or fabricated from that benchmark. All new records remain
raw with `qualified=false` and empty readiness maps.
