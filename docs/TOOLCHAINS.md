# Toolchain locking

Compiler versions are a first-class corpus axis. Published build records must use exact, runner-observed toolchain identities rather than labels such as `latest`.

## Discovery

Run on the runner that will perform builds:

```bash
python -m decbench_dataset discover-toolchain gcc gcc
python -m decbench_dataset discover-toolchain clang clang
python -m decbench_dataset discover-toolchain rustc rustc
python -m decbench_dataset discover-toolchain go go
python -m decbench_dataset discover-toolchain zig zig
```

On a Windows MSVC runner:

```powershell
python -m decbench_dataset discover-toolchain msvc cl.exe
```

The command records:

- complete version output;
- parsed major/minor/patch when detectable;
- a human-readable first-line build identity;
- resolved executable path;
- SHA-256 of the compiler executable;
- runner OS;
- exact version-query command and exit status.

The output is a candidate lock entry for `configs/toolchains.json`. Review it before committing it. Toolchain discovery runs trusted compiler/version commands only; it never executes corpus-produced binaries.

## Version coverage policy

The final corpus should not collapse all builds onto one current compiler. Keep multiple exact versions per family so downstream analysis can stratify results by compiler generation. Historical versions should be pinned to compatible runner/container images and marked with explicit target support.

A concrete toolchain lock entry may additionally include:

- `container_image_digest` or VM image identity;
- `target_ids` to restrict unsupported cross-targets;
- linker/SDK identities;
- legacy/current channel labels for analysis only.

Those labels are descriptive; exact `version_raw` and executable/image identities remain authoritative.
