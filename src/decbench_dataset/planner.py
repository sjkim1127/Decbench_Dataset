from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from .matrix import Variant


class PlanningError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectSource:
    project: str
    repository_url: str
    commit_sha: str
    tree_hash: str


@dataclass(frozen=True)
class BuildJob:
    job_id: str
    variant_id: str
    project: ProjectSource
    language: str
    compiler_set: str
    toolchain: dict[str, Any]
    profile: dict[str, Any]
    target: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "variant_id": self.variant_id,
            "project": {
                "project": self.project.project,
                "repository_url": self.project.repository_url,
                "commit_sha": self.project.commit_sha,
                "tree_hash": self.project.tree_hash,
            },
            "language": self.language,
            "compiler_set": self.compiler_set,
            "toolchain": self.toolchain,
            "profile": self.profile,
            "target": self.target,
        }


def _job_id(source: ProjectSource, variant: Variant, toolchain: dict[str, Any]) -> str:
    version_raw = toolchain.get("version_raw")
    if not version_raw:
        raise PlanningError("exact toolchain version_raw is required before planning a build job")
    canonical = {
        "project": source.project,
        "repository_url": source.repository_url,
        "commit_sha": source.commit_sha,
        "tree_hash": source.tree_hash,
        "variant_id": variant.variant_id,
        "toolchain": {
            "version_raw": version_raw,
            "build_identity": toolchain.get("build_identity"),
            "executable_sha256": toolchain.get("executable_sha256"),
            "image_digest": toolchain.get("container_image_digest"),
        },
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def plan_jobs(source: ProjectSource, variant: Variant, toolchains: dict[str, Any]) -> Iterable[BuildJob]:
    try:
        toolchain_set = toolchains["sets"][variant.compiler_set]
    except KeyError as exc:
        raise PlanningError(f"unknown compiler set: {variant.compiler_set}") from exc

    versions = toolchain_set.get("versions", [])
    for locked in versions:
        supported_targets = locked.get("target_ids")
        if supported_targets and variant.target_id not in supported_targets:
            continue
        yield BuildJob(
            job_id=_job_id(source, variant, locked),
            variant_id=variant.variant_id,
            project=source,
            language=variant.language,
            compiler_set=variant.compiler_set,
            toolchain=locked,
            profile=variant.profile,
            target=variant.target,
        )
