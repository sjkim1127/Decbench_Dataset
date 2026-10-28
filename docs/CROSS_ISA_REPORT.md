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

The Windows campaign ran separately in GitHub Actions run 40620095669. MSVC
19.44.35229 and clang-cl 20.1.8 each target x86, x86-64 and ARM64: 144 MSVC and
252 clang-cl attempts succeeded, across 198 variants. Each build has a PE DLL,
PDB and `llvm-objcopy --strip-debug` DLL. An independent LLVM PDB check matched
the original PE CodeView GUID and age in all 396 cases. The `.text` bytes within
the declared virtual size match in all 396 pairs; 394 pairs differ in the raw
section padding. CodeView information remains in all 396 stripped DLLs, so they
are not fully stripped and other sections were not compared. MSVC `/O1` is labeled `Osize-msvc`
because it is a size profile and is not equivalent to Clang/GCC `-O1`. clang-cl
has O0/O1/O2/O3/Os/Oz and O2-noinline; MSVC has O0/O2/Osize-msvc/O2-noinline.

The original `richgel999/bc7enc_rdo` CMake executable adds a whole-project C++
case with nine translation units on Linux AArch64. O2 and O2-LTO were each built
twice; all four succeeded, and debuglink CRC and stripped `.text` were checked.
The first four attempts failed because upstream `ert.h` uses standard integer
types without including the corresponding header. The successful recipe supplies
`-include cstdint` as a recorded compiler flag; original source remains unchanged.
Initial failure manifests and diagnostics are retained in the package history.
