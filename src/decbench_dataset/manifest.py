from __future__ import annotations

import hashlib
import json
from typing import Any


class ManifestError(ValueError):
    pass


def compute_build_id(manifest: dict[str, Any]) -> str:
    """Compute a stable build identity from immutable compilation inputs.

    Deliberately excludes output hashes and runtime timestamps. The exact compiler
    version/build identity is mandatory: a compiler family alone is insufficient.
    """
    source = manifest.get("source") or {}
    target = manifest.get("target") or {}
    toolchain = manifest.get("toolchain") or {}
    profile = manifest.get("profile") or {}

    required = {
        "project": manifest.get("project"),
        "language": manifest.get("language"),
        "source.repository_url": source.get("repository_url"),
        "source.commit_sha": source.get("commit_sha"),
        "source.tree_hash": source.get("tree_hash"),
        "target.id": target.get("id"),
        "toolchain.family": toolchain.get("family"),
        "toolchain.version_raw": toolchain.get("version_raw"),
        "profile.id": profile.get("id"),
    }
    missing = [key for key, value in required.items() if value in (None, "")]
    if missing:
        raise ManifestError("cannot compute build_id; missing: " + ", ".join(missing))

    canonical = {
        "project": manifest["project"],
        "language": manifest["language"],
        "source": {
            "repository_url": source["repository_url"],
            "commit_sha": source["commit_sha"],
            "tree_hash": source["tree_hash"],
        },
        "target": {
            "id": target["id"],
            "triple": target.get("triple"),
        },
        "toolchain": {
            "family": toolchain["family"],
            "version_raw": toolchain["version_raw"],
            "build_identity": toolchain.get("build_identity"),
            "executable_sha256": toolchain.get("executable_sha256"),
            "container_image_digest": toolchain.get("container_image_digest"),
        },
        "profile": profile,
        "commands": manifest.get("commands", []),
        "environment": manifest.get("environment", {}),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def finalize_build_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    result.setdefault("qualified", False)
    result.setdefault("eval_ready", {})
    result["build_id"] = compute_build_id(result)
    return result
