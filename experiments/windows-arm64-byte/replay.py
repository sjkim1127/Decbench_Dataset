"""Run frozen Windows ARM64 compilation inputs and retain hash-bound evidence."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import io
import json
import ntpath
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ROOT = Path.cwd()
STUDY = Path(__file__).resolve().parent
NONCE_SIZE = 12


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def seal():
    family = sys.argv[2]
    key = bytes.fromhex(os.environ["BYTE_STUDY_KEY"])
    archive = io.BytesIO()
    output = ROOT / f"native-{family}-results"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as files:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                files.write(path, path.relative_to(ROOT).as_posix())
    nonce = os.urandom(NONCE_SIZE)
    (ROOT / f"{family}-results.aes").write_bytes(
        nonce + AESGCM(key).encrypt(nonce, archive.getvalue(), family.encode())
    )


def unpack():
    key = bytes.fromhex(os.environ["BYTE_STUDY_KEY"])
    payload = (STUDY / "inputs.aes").read_bytes()
    archive = AESGCM(key).decrypt(payload[:NONCE_SIZE], payload[NONCE_SIZE:], b"inputs")
    with zipfile.ZipFile(io.BytesIO(archive)) as files:
        files.extractall(ROOT)


def compile_row(exe, flags, source, destination, contract_hash, identity, timeout):
    destination.parent.mkdir(parents=True, exist_ok=True)
    log = destination.with_suffix(".log")
    command = [str(exe), *flags, f"/Fo{destination}", source]
    proof = {**identity, "argv": command, "source_sha256": digest(ROOT / source),
             "contract_sha256": contract_hash}
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=timeout, check=False)
        log.write_bytes(result.stdout + result.stderr)
        code = result.returncode
        status = "compiled" if code == 0 and destination.exists() else "compile_error"
    except subprocess.TimeoutExpired as error:
        log.write_bytes((error.stdout or b"") + (error.stderr or b""))
        code = None
        status = "timeout"
    row = {**proof, "status": status, "exit_code": code,
           "log": log.as_posix(), "log_sha256": digest(log)}
    if status == "compiled":
        row.update(object=destination.as_posix(), object_sha256=digest(destination))
    return row


def run():
    family = sys.argv[2]
    plan_path = ROOT / "COMPILE-PLAN.json"
    native_path = ROOT / "NATIVE-PLAN.json"
    plan = json.loads(plan_path.read_bytes())
    native = json.loads(native_path.read_bytes())
    cells = {key: spec for key, spec in plan["compiler_cells"].items() if spec["family"] == family}
    expected, = {spec["compiler_sha256"] for spec in cells.values()}
    env = {name: os.environ.get(name, "") for name in (
        "INCLUDE", "VCToolsVersion", "WindowsSDKVersion", "VSCMD_ARG_TGT_ARCH", "ImageVersion",
    )}
    assert env["VSCMD_ARG_TGT_ARCH"] == "arm64"
    assert env["VCToolsVersion"] == native["vc_tools"]
    assert env["WindowsSDKVersion"].rstrip("\\/") == native["windows_sdk"]
    assert [ntpath.normcase(ntpath.normpath(p)) for p in env["INCLUDE"].split(";")] == [
        ntpath.normcase(ntpath.normpath(p)) for p in native["include"].split(";")
    ]
    exe_name = "cl.exe" if family == "msvc" else "clang-cl.exe"
    exe = Path(shutil.which(exe_name) or exe_name)
    if family == "clang-cl" and (not exe.is_file() or digest(exe) != expected):
        exe = Path(os.environ["RUNNER_TEMP"]) / "exact-llvm" / "bin" / exe_name
    assert exe.is_file() and digest(exe) == expected, f"{family} compiler digest mismatch"
    out = Path(f"native-{family}-results")
    out.mkdir(exist_ok=True)
    contract = out / "CONTRACT.json"
    write(contract, {
        "plan_sha256": digest(plan_path), "native_plan_sha256": digest(native_path),
        "compiler_sha256": expected, "compiler": str(exe), "environment": env,
        "script_sha256": digest(Path(__file__)), "run_id": os.environ.get("GITHUB_RUN_ID"),
    })
    contract_hash = digest(contract)
    capture_root = Path("corpus") / f"cpp-tu-{family}"
    capture_env = {**os.environ, "PATH": str(exe.parent) + os.pathsep + os.environ["PATH"]}
    capture_command = [sys.executable, "scripts/collect_windows_matrix.py", "--family", family,
                       "--arch", "aarch64", "--profiles", "O0", "O2", "O2-noinline", "--projects",
                       "pugixml", "tinyxml2", "--capture-cpp-tu", "--output", str(capture_root)]
    with (out / "collector.log").open("wb") as log:
        capture = subprocess.run(capture_command, env=capture_env, cwd=ROOT, stdout=log,
                                 stderr=subprocess.STDOUT, timeout=600, check=False)
    controls = []
    for cell in cells:
        item = native["controls"][cell]
        folder = capture_root / "builds" / item["project"] / item["profile"] / "1"
        record_path = folder / "manifest.json"
        result = {"cell": cell, "status": "control_rebuild_failed"}
        if record_path.is_file():
            record = json.loads(record_path.read_bytes())
            assert record["source"]["commit_sha"] == item["commit_sha"]
            assert record["source"]["tree_hash"] == item["tree_hash"]
            assert record["toolchain"]["sha256"] == expected
            if record["status"] == "success":
                destination = out / "controls" / cell
                destination.mkdir(parents=True, exist_ok=True)
                for name in ("unit.obj", "unit.replayed.obj", "manifest.json"):
                    shutil.copy2(folder / name, destination / name)
                result = {"cell": cell, "status": "compiled", "path": destination.as_posix(),
                          "manifest_sha256": digest(destination / "manifest.json")}
        controls.append(result)
    write(out / "CONTROLS.json", controls)
    print("Original-control collector exit code", capture.returncode, flush=True)

    def produce(row):
        cell, tool, address = (row[name] for name in ("cell", "tool", "address"))
        identity = {"cell": cell, "tool": tool, "address": address}
        if not row["nonempty"]:
            return {**identity, "status": "empty_producer"}
        assert digest(ROOT / row["source"]) == row["source_sha256"]
        return compile_row(exe, cells[cell]["flags"], row["source"],
                           out / cell / tool / f"{address:x}.obj", contract_hash, identity, 45)

    rows = []
    selected = [row for row in plan["rows"] if row["cell"] in cells]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for row in pool.map(produce, selected):
            rows.append(row)
            if len(rows) % 1000 == 0:
                print(f"Completed {len(rows)}/{len(selected)} records", flush=True)
    assert digest(exe) == expected and digest(plan_path) == json.loads(contract.read_bytes())["plan_sha256"]
    statuses = Counter(row["status"] for row in rows)
    write(out / "COMPILATION.json", {"rows": rows, "contract_sha256": contract_hash, "statuses": statuses})
    print(dict(statuses), flush=True)


if __name__ == "__main__":
    {"unpack": unpack, "run": run, "seal": seal}[sys.argv[1]]()
