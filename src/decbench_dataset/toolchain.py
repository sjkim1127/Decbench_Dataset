from __future__ import annotations

import hashlib
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


class ToolchainDiscoveryError(RuntimeError):
    pass


_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(text: str) -> tuple[int | None, int | None, int | None]:
    match = _VERSION_RE.search(text)
    if not match:
        return None, None, None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3)) if match.group(3) is not None else None
    return major, minor, patch


def version_command(family: str, executable: str) -> list[str]:
    if family in {"gcc", "clang", "clang-cl"}:
        return [executable, "--version"]
    if family == "rustc":
        return [executable, "-Vv"]
    if family == "go":
        return [executable, "version"]
    if family == "zig":
        return [executable, "version"]
    if family == "msvc":
        # cl.exe prints its exact compiler version banner when invoked without input.
        return [executable]
    raise ToolchainDiscoveryError(f"unsupported toolchain family: {family}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_executable(executable: str) -> Path:
    candidate = shutil.which(executable)
    if candidate:
        return Path(candidate).resolve()
    path = Path(executable).expanduser()
    if path.is_file():
        return path.resolve()
    raise ToolchainDiscoveryError(f"compiler executable not found: {executable}")


def discover_toolchain(family: str, executable: str, *, timeout_seconds: int = 15) -> dict[str, Any]:
    resolved = _resolve_executable(executable)
    command = version_command(family, str(resolved))
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolchainDiscoveryError(f"failed to query {resolved}: {exc}") from exc

    combined = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part.strip()).strip()
    if not combined:
        raise ToolchainDiscoveryError(f"toolchain produced no version output: {resolved}")

    major, minor, patch = parse_version(combined)
    first_line = next((line.strip() for line in combined.splitlines() if line.strip()), combined)

    return {
        "family": family,
        "version_raw": combined,
        "version_line": first_line,
        "version_major": major,
        "version_minor": minor,
        "version_patch": patch,
        "build_identity": first_line,
        "executable": str(resolved),
        "executable_sha256": _sha256_file(resolved),
        "runner_os": platform.system().lower(),
        "version_command": command,
        "version_command_exit_code": proc.returncode,
    }
