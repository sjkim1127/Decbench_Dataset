# Decbench_Dataset

Foundation repository for a large, reproducible, multi-language binary corpus for future DecBench expansion and Fission development.

## Scope

The corpus is designed around five first-class axes:

1. **Language**: C, C++, Rust, Go, Zig, Swift, Fortran, D, Nim.
2. **Compiler**: family **and exact compiler version/build identity**.
3. **Optimization**: more than the legacy O0/O2/O2-noinline set; profiles include size/speed/debug, inlining and LTO dimensions where supported.
4. **Target**: OS, object format and architecture (ELF/PE-COFF/Mach-O; x86, x86_64, ARM32, AArch64, plus extensible secondary architectures).
5. **Ground-truth/debug artifacts**: source snapshot, DWARF/dSYM or PDB+CodeView, loader metadata and versioned CFG extraction outputs.

The raw corpus does **not** define a decompiler score. Qualification and metric readiness are separate, versioned stages.

## Status

`foundation/v0-multilang-matrix` establishes M0/M1 foundations:

- `SPEC.md`: corpus invariants and artifact contract.
- `configs/build-matrix.json`: optimization/target matrix policy.
- `schemas/`: JSON Schemas for build, binary and function records.
- `src/decbench_dataset/`: deterministic matrix expansion and validation CLI.
- `docs/ARCHITECTURE.md`: automation pipeline and runner model.

## Design principles

- Never identify functions by name alone.
- Preserve raw inputs and provenance; derived artifacts are replaceable and versioned.
- Never execute produced binaries during corpus generation.
- Treat repository build systems as untrusted code.
- Split by project, not function, to reduce evaluation leakage.
- Prefer deterministic manifests and content-addressed artifacts.
- Keep Hugging Face metadata viewer-friendly (Parquet) and payload file counts low (tar/WebDataset-style shards).

## Quick start

```bash
python -m pip install -e .
python -m decbench_dataset validate-matrix configs/build-matrix.json
python -m decbench_dataset expand-matrix configs/build-matrix.json --language cpp --limit 20
```

No Hugging Face upload is performed by default. Upload support will remain dry-run-first until explicitly enabled.

## Nine-language collection and initial pilot

See [the detailed contract](docs/COLLECTION_CONTRACT.md) for OS/ABI/ISA/SDK,
compiler/linker version, full ordered options and language-specific provenance.
The nine-language matrix is a planning policy; executable adapters are currently
limited to the real C/C++ Linux pilot. No scores or function qualification yet.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[publish,test]'
docker pull --platform linux/amd64 gcc@sha256:16ae525998c94df36a116c191524256b1d46e72d7a0e9aaf6c153455e40eb5b8
.venv/bin/python scripts/collect_pilot.py --output corpus/pilot
.venv/bin/python scripts/publish_pilot.py --corpus corpus/pilot --output shards/pilot
# Explicit publication, after inspecting local shards:
.venv/bin/python scripts/publish_pilot.py --corpus corpus/pilot --output shards/pilot --publish
```

Use a fresh `--output` directory for each campaign: existing attempt directories
are refused to prevent accidental overwrite. Linux GitHub Actions execution is
available in `.github/workflows/collect-pilot.yml` through manual dispatch once
these source changes are pushed. Uploads use the local HF authentication or a
separate publisher secret; builders never receive it. The authorized public
repository is https://huggingface.co/datasets/sjkim1127/decbench-multilang-corpus.
