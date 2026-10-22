from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True)
class ExtractionRequest:
    binary: Path
    debug_artifacts: tuple[Path, ...]
    output_dir: Path
    format: str
    arch: str


@dataclass(frozen=True)
class ExtractionResult:
    loader_metadata: Path
    function_table: Path | None = None
    debug_metadata: Path | None = None
    cfg_manifests: tuple[Path, ...] = ()


class FormatExtractor(Protocol):
    """Format-specific metadata extractor.

    Implementations parse artifacts only; they must never execute the produced
    program. Every emitted file must carry extractor name/version/configuration.
    """

    name: str
    version: str
    supported_formats: Sequence[str]

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        ...


@dataclass(frozen=True)
class ExtractionContract:
    format: str
    required_debug_kind: str
    required_relationships: tuple[str, ...]
    reference_tools: tuple[str, ...]


CONTRACTS = {
    "elf": ExtractionContract(
        format="elf",
        required_debug_kind="dwarf",
        required_relationships=("binary<->split-debug when present",),
        reference_tools=("llvm-readobj", "llvm-dwarfdump"),
    ),
    "pe": ExtractionContract(
        format="pe",
        required_debug_kind="pdb-codeview",
        required_relationships=("PE debug directory CodeView<->PDB identity",),
        reference_tools=("llvm-readobj", "llvm-pdbutil"),
    ),
    "macho": ExtractionContract(
        format="macho",
        required_debug_kind="dsym-dwarf",
        required_relationships=("Mach-O UUID<->dSYM UUID", "fat container<->architecture slices"),
        reference_tools=("llvm-objdump", "llvm-dwarfdump"),
    ),
}


def contract_for_format(format_name: str) -> ExtractionContract:
    try:
        return CONTRACTS[format_name]
    except KeyError as exc:
        raise ValueError(f"unsupported object format: {format_name}") from exc


def validate_request(request: ExtractionRequest) -> None:
    contract_for_format(request.format)
    if not request.binary.name:
        raise ValueError("binary path is required")
    if request.binary in request.debug_artifacts:
        raise ValueError("binary and external debug artifact must be represented separately")
