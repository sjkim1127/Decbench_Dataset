from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .matrix import expand_matrix, load_json, validate_matrix
from .toolchain import ToolchainDiscoveryError, discover_toolchain


def _toolchain_path(matrix_path: Path, matrix: dict) -> Path | None:
    rel = (matrix.get("version_resolution") or {}).get("manifest")
    if not rel:
        return None
    candidate = Path(rel)
    if candidate.is_absolute():
        return candidate
    repo_root = matrix_path.parent.parent if matrix_path.parent.name == "configs" else matrix_path.parent
    return repo_root / candidate


def _load_toolchains(matrix_path: Path, matrix: dict) -> dict | None:
    path = _toolchain_path(matrix_path, matrix)
    if path and path.exists():
        return load_json(path)
    return None


def cmd_validate_matrix(args: argparse.Namespace) -> int:
    matrix_path = Path(args.matrix)
    matrix = load_json(matrix_path)
    toolchains = _load_toolchains(matrix_path, matrix)
    errors = validate_matrix(matrix, toolchains)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    unresolved = []
    if toolchains:
        for name, spec in toolchains.get("sets", {}).items():
            if not spec.get("versions"):
                unresolved.append(name)

    print(f"matrix ok: version={matrix['matrix_version']} languages={len(matrix['languages'])} targets={len(matrix['targets'])}")
    if unresolved:
        print("toolchain sets awaiting exact locked versions: " + ", ".join(sorted(unresolved)))
    return 0


def cmd_expand_matrix(args: argparse.Namespace) -> int:
    matrix_path = Path(args.matrix)
    matrix = load_json(matrix_path)
    toolchains = _load_toolchains(matrix_path, matrix)
    variants = expand_matrix(
        matrix,
        toolchains=toolchains,
        language=args.language,
        primary_only=not args.include_secondary,
    )
    count = 0
    for variant in variants:
        if args.limit is not None and count >= args.limit:
            break
        print(json.dumps(variant.as_dict(), sort_keys=True))
        count += 1
    print(f"expanded_variants={count}", file=sys.stderr)
    return 0


def cmd_discover_toolchain(args: argparse.Namespace) -> int:
    try:
        record = discover_toolchain(args.family, args.executable)
    except ToolchainDiscoveryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decbench-dataset")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate-matrix", help="validate matrix structure and toolchain references")
    validate.add_argument("matrix")
    validate.set_defaults(func=cmd_validate_matrix)

    expand = sub.add_parser("expand-matrix", help="emit deterministic abstract build variants as JSONL")
    expand.add_argument("matrix")
    expand.add_argument("--language", choices=["c", "cpp", "rust", "go", "zig"])
    expand.add_argument("--include-secondary", action="store_true")
    expand.add_argument("--limit", type=int)
    expand.set_defaults(func=cmd_expand_matrix)

    discover = sub.add_parser("discover-toolchain", help="capture an installed compiler's exact version and executable hash")
    discover.add_argument("family", choices=["gcc", "clang", "clang-cl", "msvc", "rustc", "go", "zig"])
    discover.add_argument("executable", help="compiler executable name or path")
    discover.set_defaults(func=cmd_discover_toolchain)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
