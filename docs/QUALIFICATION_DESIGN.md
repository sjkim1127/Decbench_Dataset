# Function mapping and qualification

This layer records independently inspectable evidence, not a DecBench integration.
Raw builds remain usable as stress-test inputs whether or not mapping succeeds.
Qualification is per binary/function and versioned; build-level `qualified=false`
must not be changed merely because some candidate pairs were extracted.

```
immutable binary + debug + source identity
    -> verified binary/debug association
    -> source AST body extraction with source blob hash and byte range
    -> machine-code function entry + extent (independent boundary evidence)
    -> candidate source/binary relation and ambiguity evidence
    -> transformation/semantic review and calibrated confidence
    -> separately versioned benchmark-eligible record
```

The record schema is `schemas/qualification-record.schema.json`. Linked ELF
virtual addresses are recorded as `elf-linked-va`; PE RVA and Mach-O VM address
are future adapters and must never silently share a coordinate convention.
Unknown inline, outlining, and compiler-generated status is null, not false.
`oracle_confidence` stays null until a documented, calibrated policy exists.
`candidate` is not benchmark eligible. Failure reasons and unresolved cases are
retained, not silently dropped from denominator counts.

`qualified=true` requires every explicit gate: binary/debug association,
source body, independent machine boundary, unique mapping, transformation
review, and semantic oracle. A valid schema can only verify that claims are
present, not that the claims are true. Function aliases, ICF, same-address names,
inlining, outlining, ranges, thunks and compiler-generated functions require
separate evidence and may force rejection or an ambiguous relation. Confidence
must never be invented from DWARF alone.

The first ELF proof-of-evidence tool is `scripts/qualify_elf_pilot.py`. It checks
GNU debuglink CRC and `.text` equality, extracts C source bodies using the
independent Clang AST, joins DWARF subprogram entries to ELF symbols and source
locations, and retains all attempted debug entries with explicit reasons. The
pilot uses a different Clang environment to parse the original source; its AST
is supporting evidence rather than a faithful reconstruction of all original
build preprocessing. Symbol extent and DWARF are compiler-produced evidence,
not independent machine boundary validation. The tool emits zero qualified
functions, regardless of the number of candidates.

Near-term extensions should independently recover instruction/control-flow
boundaries and verify source compilation context, detect inlined DIEs and folded
aliases, and define score-specific semantic gates. PE CodeView/PDB GUID+age and
Mach-O UUID associations require separate adapters. Do not use a filename or
matching name as sufficient proof of debug association or function identity.

For leakage control, introduce stable family, project, revision, variant and
replay group identities only when their underlying relations can be proven.
Project-family split assignment is a future explicit operation; optimization or
compiler variants from one family cannot be assigned to opposite splits. No
train/test split is published by this pilot.
