# ARMv7 and RISC-V64 raw corpus

The 2026-10-28 cross-compilation campaign builds six unmodified pinned upstream
projects: cJSON, inih, xxHash, LZ4, pugixml and tinyxml2. Collection uses original
Git archives and reviewed license blobs, with no collector-written program or
wrapper. The final binaries were never executed.

| Target | ISA mode | Compilers | Successful attempts | Build variants |
| --- | --- | --- | ---: | ---: |
| Linux ARMv7 / hard-float ELF | ARM | GCC and Clang | 204 | 102 |
| Linux ARMv7 / hard-float ELF | Thumb | GCC and Clang | 204 | 102 |
| Linux RISC-V64 / ELF | RV64GC LP64D | GCC and Clang | 204 | 102 |
| Total | | | **612** | **306** |

Each variant is compiled twice. All 306 binary replay pairs matched byte for byte
within this campaign, after the same source, toolchain, target and flags were used.
This does not prove reproducibility across other host versions or toolchain images.

Both compilers cover `O0`, `O1`, `O2`, `O3`, `Os`, `Oz`, `O2-noinline` and
`O2-LTO`. Clang additionally covers `O2-ThinLTO`. ARM uses explicit `-marm` or
`-mthumb` and hard-float options; RISC-V uses `-march=rv64gc -mabi=lp64d`.
These are **single-translation-unit shared-library builds**, not whole-project
C++/LTO coverage. No missing target or compiler combination is implied.

The image is pinned by Docker image ID
`sha256:59d51dc5e3d9cf417046d449a6e8134cefd9032c3e73369e3f4461f1f84e0dc5`.
It uses Ubuntu cross GCC 13.3.0, Clang 18.1.3, GNU binutils 2.42 and LLD 18.1.3.
The first LLD version probe incorrectly invoked its resolved generic `lld` name;
the failed original probe is preserved along with a successful independent
`ld.lld --version` correction inside the same immutable image.

Every attempt retains both binaries, a separate debug file, object file, original
source archive, manifest, compiler/linker diagnostics, raw `execve` trace and a
normalized JSON table of observed process argv. A Clang integrated frontend need
not appear as a separate execve; the driver argv and verbose logs are retained.
GNU debuglink CRC is checked and the stripped/unstripped `.text` bytes match.
Debug association is evidence, not source-level or semantic qualification.

The companion C pilot checks a single older x86-64 cJSON ELF: 113 original source
functions, 113 DWARF subprogram records, 110 preliminary exact-name/line/symbol
candidates, 3 unassessed records, and **0 qualified functions**. The source AST was
parsed with a different host Clang and is not proof of original preprocessing;
independent boundaries, inlining/folding and semantic checks remain open.

`collect-windows-matrix.yml` separately collects MSVC and clang-cl. MSVC `/O1`
is labeled `Osize-msvc` because it is a size profile and is not equivalent to
Clang/GCC `-O1`. Treat its job/artifact status as measured independently; this
report does not claim Windows results before that workflow completes.
