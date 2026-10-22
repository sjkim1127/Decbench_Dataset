# BLOCKERS

This file records unresolved decisions or unavailable infrastructure. Items here should not stop unrelated work.

## Foundation blockers

- [ ] Populate `configs/toolchains.json` with **verified exact compiler/toolchain versions**, executable identities and runner/image references. Do not invent versions.
- [ ] Define the initial project allowlist per language after license/buildability review.
- [ ] Decide the first Hugging Face dataset repository name and storage budget before upload automation is enabled.
- [ ] Provision/identify isolated Windows runners for representative MSVC + PDB/CodeView builds.
- [ ] Provision/identify isolated macOS runners for Mach-O + dSYM builds.
- [ ] Select the first independent machine-CFG extractor baseline to run alongside Fission.
- [ ] Define the exact Parquet physical schema after the pilot exposes nested-column/query tradeoffs.

## Non-blockers

- C++ scoring is intentionally not required for raw corpus generation.
- Rust-Joern completion is intentionally not required for raw corpus generation.
- Source/compiler CFG availability may vary by language and toolchain; missing derived CFGs must be represented explicitly rather than guessed.
