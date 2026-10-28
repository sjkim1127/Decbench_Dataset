# BLOCKERS

This file records unresolved decisions or unavailable infrastructure. Items here should not stop unrelated work.

## Foundation blockers

- [ ] Populate `configs/toolchains.json` with **verified exact compiler/toolchain versions**, executable identities and runner/image references. Do not invent versions.
- [ ] Define the initial project allowlist per language after license/buildability review.
- [x] First public HF repository authorized: `sjkim1127/decbench-multilang-corpus`. Pilot is bounded; larger campaign storage budgets remain open.
- [ ] Provision/identify isolated Windows runners for representative MSVC + PDB/CodeView builds.
- [ ] Provision/identify isolated macOS runners for Mach-O + dSYM builds.
- [ ] Select the first independent machine-CFG extractor baseline to run alongside Fission.
- [ ] Define the exact Parquet physical schema after the pilot exposes nested-column/query tradeoffs.

## Non-blockers

- C++ scoring is intentionally not required for raw corpus generation.
- Rust-Joern completion is intentionally not required for raw corpus generation.
- Source/compiler CFG availability may vary by language and toolchain; missing derived CFGs must be represented explicitly rather than guessed.

## Nine-language expansion

- [x] Bounded raw collectors exist for all nine languages, using original upstream products only. See `UPSTREAM_LANGUAGES_REPORT.md` for actual platform coverage.
- [ ] Expand project counts and platform/toolchain coverage per language; qualification remains separate from acquisition.
- [ ] Trace/normalize compiler child argv and response files for arbitrary build systems.
- [ ] Native Windows/macOS pilot and non-x86-64 targets.
- [ ] Normalized function/debug mappings and independent CFG extraction.
- [ ] Resumable campaign ledger, multi-shard rotation and full failure-denominator publication.
