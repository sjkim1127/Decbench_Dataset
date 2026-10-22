from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class MatrixError(ValueError):
    pass


@dataclass(frozen=True)
class Variant:
    variant_id: str
    language: str
    compiler_set: str
    profile_id: str
    target_id: str
    profile: dict[str, Any]
    target: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "language": self.language,
            "compiler_set": self.compiler_set,
            "profile_id": self.profile_id,
            "target_id": self.target_id,
            "profile": self.profile,
            "target": self.target,
        }


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise MatrixError(f"top-level JSON object required: {path}")
    return data


def _resolved_profiles(matrix: dict[str, Any], language: str) -> list[dict[str, Any]]:
    langs = matrix["languages"]
    node = langs[language]
    if "profiles" in node:
        profiles = node["profiles"]
    else:
        source = node.get("profiles_from")
        if source not in langs or "profiles" not in langs[source]:
            raise MatrixError(f"{language}: invalid profiles_from={source!r}")
        profiles = langs[source]["profiles"]
    if not isinstance(profiles, list) or not profiles:
        raise MatrixError(f"{language}: at least one profile is required")
    return profiles


def validate_matrix(matrix: dict[str, Any], toolchains: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    for key in ("schema_version", "matrix_version", "targets", "languages"):
        if key not in matrix:
            errors.append(f"missing top-level key: {key}")

    if errors:
        return errors

    target_ids: set[str] = set()
    target_formats: set[str] = set()
    for target in matrix.get("targets", []):
        tid = target.get("id")
        if not tid:
            errors.append("target missing id")
            continue
        if tid in target_ids:
            errors.append(f"duplicate target id: {tid}")
        target_ids.add(tid)
        for key in ("os", "format", "arch"):
            if not target.get(key):
                errors.append(f"target {tid}: missing {key}")
        if target.get("format"):
            target_formats.add(target["format"])

    languages = matrix.get("languages", {})
    if not isinstance(languages, dict) or not languages:
        errors.append("languages must be a non-empty object")
        return errors

    known_sets = set((toolchains or {}).get("sets", {}).keys()) if toolchains else set()
    for language, node in languages.items():
        compiler_sets = node.get("compiler_sets", [])
        if not compiler_sets:
            errors.append(f"{language}: compiler_sets is empty")
        for compiler_set in compiler_sets:
            if toolchains is not None and compiler_set not in known_sets:
                errors.append(f"{language}: unknown compiler set {compiler_set}")
                continue
            if toolchains is not None:
                spec = toolchains["sets"][compiler_set]
                supported = set(spec.get("supported_formats", []))
                if not supported:
                    errors.append(f"toolchain set {compiler_set}: supported_formats is empty")
                elif not (supported & target_formats):
                    errors.append(f"toolchain set {compiler_set}: no compatible target format")
        try:
            profiles = _resolved_profiles(matrix, language)
        except MatrixError as exc:
            errors.append(str(exc))
            continue
        profile_ids: set[str] = set()
        for profile in profiles:
            pid = profile.get("id")
            if not pid:
                errors.append(f"{language}: profile missing id")
                continue
            if pid in profile_ids:
                errors.append(f"{language}: duplicate profile id {pid}")
            profile_ids.add(pid)

    return errors


def _variant_id(matrix_version: str, language: str, compiler_set: str, profile_id: str, target_id: str, *, profile: dict | None = None, target: dict | None = None) -> str:
    canonical = json.dumps(
        {
            "matrix_version": matrix_version,
            "language": language,
            "compiler_set": compiler_set,
            "profile_id": profile_id,
            "target_id": target_id,
            "profile": profile,
            "target": target,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _target_supported(target: dict[str, Any], toolchain_spec: dict[str, Any] | None) -> bool:
    if toolchain_spec is None:
        return True
    supported_formats = set(toolchain_spec.get("supported_formats", []))
    if target.get("format") not in supported_formats:
        return False
    runner_os = toolchain_spec.get("runner_os")
    if runner_os and target.get("os") != runner_os:
        return False
    return True


def expand_matrix(
    matrix: dict[str, Any],
    *,
    toolchains: dict[str, Any] | None = None,
    language: str | None = None,
    primary_only: bool = True,
) -> Iterable[Variant]:
    errors = validate_matrix(matrix, toolchains)
    if errors:
        raise MatrixError("; ".join(errors))

    languages = [language] if language else list(matrix["languages"].keys())
    targets = [t for t in matrix["targets"] if (t.get("primary", True) or not primary_only)]
    toolchain_sets = (toolchains or {}).get("sets", {})

    for lang in languages:
        if lang not in matrix["languages"]:
            raise MatrixError(f"unknown language: {lang}")
        node = matrix["languages"][lang]
        profiles = _resolved_profiles(matrix, lang)
        for compiler_set in node["compiler_sets"]:
            toolchain_spec = toolchain_sets.get(compiler_set) if toolchains is not None else None
            for profile in profiles:
                for target in targets:
                    if not _target_supported(target, toolchain_spec):
                        continue
                    yield Variant(
                        variant_id=_variant_id(
                            matrix["matrix_version"], lang, compiler_set, profile["id"], target["id"],
                            profile=profile, target=target
                        ),
                        language=lang,
                        compiler_set=compiler_set,
                        profile_id=profile["id"],
                        target_id=target["id"],
                        profile=profile,
                        target=target,
                    )
