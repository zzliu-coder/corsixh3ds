#!/bin/false
# Invoke through scripts/run_verifier_python.sh.
"""Reviewer policy builder and raw-evidence producer for Runtime Core v2 C3."""

from __future__ import annotations

import argparse
import contextlib
import io
import datetime as dt
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Optional

FORBIDDEN = [
    "0637cc8d64a3152ae27bee344806ae9aec58592b",
    "9ff2b84114df9070d578c88fe927255369c12b6d",
    "4b3bea525923a9ba6199c7b08f36aa814863f4e4",
    "7f637a26a966e470cb250d9dba6ec55a7e834ace",
    "161fa9cbff67138aca6b1c7d22eada7293f70fac",
    "ff919031256fd057d87d6bb8126a076164588478",
]
MATRIX_SHA256 = "8b7cf0d8e3b3702e9aa3c32aff9d1ed3e363ceab52699539251975a61985060f"
REQUIRED_PROTOCOL_GATES = [
    "GIT_TOPOLOGY", "ALLOWLIST", "PRODUCT_DIFF_ZERO", "POLICY_SCHEMA",
    "EVIDENCE_SCHEMA", "NAMESPACE_CLOSURE", "REFERENCE_GRAPH_CLOSURE",
    "SAFE_PATH_AND_TOCTOU", "PROCESS_STREAM_BINDING", "TOOL_IDENTITY",
    "SEALED_INPUT_CLOSURE", "ADVERSARIAL_60_OF_60", "HOST_REGRESSION",
    "SIMULATOR", "SANITIZER_INSTRUMENTATION_AND_CLEAN_STREAMS",
    "RH09_EVIDENCE", "RH07_EVIDENCE", "RH10_SYNTHETIC_PROVENANCE",
    "XBUILD_COMPILE_LINK", "UPSTREAM_SNAPSHOT_BYTES",
    "RAW_ANCESTRY_CLOSURE", "TOOL_IMPLEMENTATION_IDENTITY",
    "XBUILD_INPUT_CLOSURE", "SIMULATOR_SEMANTIC_BASELINE",
    "FINAL_ELF_RUNTIME_CORE_PROOF", "RAW_EVIDENCE_CLOSURE",
]
REQUIRED_PRODUCT_BASELINE = {
    "RH09_PRODUCT": "FAIL", "RH07_PRODUCT": "FAIL",
    "UPSTREAM_GIT_PROVENANCE": "NOT_PROVEN",
    "REAL_DEVICE_RUNTIME": "NOT_PROVEN",
    "S70_REAL_DEVICE_MEMORY": "NOT_PROVEN",
}
ARCHIVE_SHA = "e1bc438183bbc95e40edf9363628cb73897559c01f537cdce42638e5bb2076f8"
UPSTREAM_DIGEST = "e8622007fa508f3471294e5954ebc83168d95c81beb3b09b797bf65c02bf1801"
PRODUCT_FP = "4b027341762b902c75c10b522a8edc15330e0723b73512e9fcdc9e24841f0ca6"
CLOSURE_INPUTS = {
    "wrapper": "scripts/run_verifier_python.sh",
    "driver": "scripts/verifier_driver.py",
    "verifier-lock": "requirements/verifier.lock",
    "consumer": "scripts/consume_runtime_core_v2.py",
    "producer": "scripts/verify_runtime_core_v2.py",
    "review-policy-schema": "tests/runtime_core_v2/review-policy.schema.json",
    "evidence-manifest-schema": "tests/runtime_core_v2/evidence-manifest.schema.json",
    "observation-schema": "tests/runtime_core_v2/observation.schema.json",
    "result-schema": "tests/runtime_core_v2/result.schema.json",
    "red-oracle": "docs/runtime-core-v2-red-oracle.md",
    "adversarial-matrix-runner": "tests/runtime_core_v2/evidence_protocol_adversarial.py",
    "fixture-generator": "tests/runtime_core_v2/generate_no_level_fixture.py",
    "host-python-runner": "scripts/run_host_python_suite.py",
    "host-python-manifest": "tests/host-python-suite.json",
}


def require_verified_invocation(context: Any, operations: tuple[str, ...]) -> None:
    """Require the driver's private in-memory authority object."""
    if context is None or context.__class__.__name__ != "VerifiedInvocation":
        raise RuntimeError("VERIFIED_INVOCATION_REQUIRED")
    context.require(operations)


def require_policy_context(context: Any, policy: dict[str, Any]) -> None:
    if policy.get("verified_invocation") != context.record or \
       policy.get("verified_invocation_sha256") != context.digest:
        raise RuntimeError("VERIFIED_INVOCATION_BINDING_MISMATCH")
    selected = context.record.get("baseline_identity")
    base = policy.get("base_identity")
    if not isinstance(selected, dict) or not isinstance(base, dict) or \
       base.get("commit") != selected.get("commit") or \
       base.get("tree") != selected.get("tree"):
        raise RuntimeError("VERIFIED_BASELINE_IDENTITY_MISMATCH")

VERIFIER_DEPENDENCIES = {
    "jsonschema": "4.25.1",
    "attrs": "25.3.0",
    "jsonschema-specifications": "2025.9.1",
    "referencing": "0.36.2",
    "rpds-py": "0.27.1",
    "typing-extensions": "4.14.1",
}
BUILD_ROLES = ["host-regression", "sanitized-red-observers", "xbuild-old3ds"]
TOOL_ROLES = [
    "python", "cmake", "ctest", "git", "cxx", "nm", "cxx-linker",
    "symbol-reader", "elf-reader", "disassembler",
]
ARTIFACT_ROLES = [
    "host-configure-stdout", "host-configure-stderr",
    "host-build-stdout", "host-build-stderr",
    "host-cmake-cache", "host-compile-commands",
    "cpp-test-binary", "simulator-binary", "runtime-probe-binary",
    "ctest-stdout", "ctest-stderr", "ctest-log",
    "cpp-stdout", "cpp-stderr", "python-stdout", "python-stderr",
    "simulator-stdout", "simulator-stderr", "simulator-top-ppm",
    "simulator-bottom-ppm", "simulator-trace-json",
    "red-configure-stdout", "red-configure-stderr",
    "red-build-stdout", "red-build-stderr", "red-cmake-cache",
    "red-compile-commands", "h1-binary", "h1-binary-nm-stdout",
    "h1-binary-nm-stderr", "h2-binary", "h2-binary-nm-stdout",
    "h2-binary-nm-stderr", "rh10-generator-stdout",
    "rh10-generator-stderr", "rh10-open-trace",
    "fixture-tracked-bundle-json", "fixture-tracked-fixture-manifest",
    "fixture-tracked-core-package", "fixture-tracked-language-package",
    "fixture-fresh-bundle-json", "fixture-fresh-fixture-manifest",
    "fixture-fresh-core-package", "fixture-fresh-language-package",
    "rh09-h1-stdout", "rh09-h1-stderr", "rh07-h2-stdout", "rh07-h2-stderr",
    "xbuild-upstream-snapshot-archive",
    "xbuild-upstream-source-tree-manifest",
    "xbuild-integrated-source-tree-manifest",
    "xbuild-prepare-source-stdout", "xbuild-prepare-source-stderr",
    "xbuild-configure-stdout", "xbuild-configure-stderr",
    "xbuild-build-stdout", "xbuild-build-stderr",
    "xbuild-cmake-cache", "xbuild-compile-commands", "xbuild-build-graph",
    "xbuild-final-elf", "xbuild-final-3dsx", "xbuild-key-symbols",
    "xbuild-symbol-reader-stderr", "xbuild-elf-headers",
    "xbuild-elf-reader-stderr", "xbuild-allocator-call-disassembly",
    "xbuild-disassembler-stderr",
]
INVOCATION_ROLES = [
    "configure-host", "build-host", "ctest", "cpp", "python", "simulator",
    "configure-red", "build-red", "nm-h1", "nm-h2", "rh10-generator",
    "RH09-H1", "RH07-H2", "prepare-xbuild-source", "configure-xbuild",
    "build-xbuild", "xbuild-symbol-reader", "xbuild-elf-reader",
    "xbuild-disassembler",
]
STREAM_OUTPUTS = {
    "configure-host": ("host-configure-stdout", "host-configure-stderr",
                       ["host-cmake-cache", "host-compile-commands"]),
    "build-host": ("host-build-stdout", "host-build-stderr",
                   ["cpp-test-binary", "simulator-binary", "runtime-probe-binary"]),
    "ctest": ("ctest-stdout", "ctest-stderr", ["ctest-log"]),
    "cpp": ("cpp-stdout", "cpp-stderr", []),
    "python": ("python-stdout", "python-stderr", []),
    "simulator": ("simulator-stdout", "simulator-stderr",
                  ["simulator-top-ppm", "simulator-bottom-ppm", "simulator-trace-json"]),
    "configure-red": ("red-configure-stdout", "red-configure-stderr",
                      ["red-cmake-cache", "red-compile-commands"]),
    "build-red": ("red-build-stdout", "red-build-stderr", ["h1-binary", "h2-binary"]),
    "nm-h1": ("h1-binary-nm-stdout", "h1-binary-nm-stderr", []),
    "nm-h2": ("h2-binary-nm-stdout", "h2-binary-nm-stderr", []),
    "rh10-generator": ("rh10-generator-stdout", "rh10-generator-stderr",
                       ["rh10-open-trace", "fixture-fresh-bundle-json",
                        "fixture-fresh-fixture-manifest", "fixture-fresh-core-package",
                        "fixture-fresh-language-package"]),
    "RH09-H1": ("rh09-h1-stdout", "rh09-h1-stderr", []),
    "RH07-H2": ("rh07-h2-stdout", "rh07-h2-stderr", []),
    "prepare-xbuild-source": ("xbuild-prepare-source-stdout",
                              "xbuild-prepare-source-stderr",
                              ["xbuild-upstream-source-tree-manifest",
                               "xbuild-integrated-source-tree-manifest"]),
    "configure-xbuild": ("xbuild-configure-stdout", "xbuild-configure-stderr",
                         ["xbuild-cmake-cache", "xbuild-compile-commands",
                          "xbuild-build-graph"]),
    "build-xbuild": ("xbuild-build-stdout", "xbuild-build-stderr",
                     ["xbuild-final-elf", "xbuild-final-3dsx"]),
    "xbuild-symbol-reader": ("xbuild-key-symbols",
                             "xbuild-symbol-reader-stderr", []),
    "xbuild-elf-reader": ("xbuild-elf-headers",
                          "xbuild-elf-reader-stderr", []),
    "xbuild-disassembler": ("xbuild-allocator-call-disassembly",
                            "xbuild-disassembler-stderr", []),
}
MEDIA = {
    role: ("application/json" if role.endswith("-json") or
           role in {"xbuild-upstream-source-tree-manifest",
                    "xbuild-integrated-source-tree-manifest",
                    "fixture-tracked-bundle-json",
                    "fixture-tracked-fixture-manifest",
                    "fixture-fresh-bundle-json",
                    "fixture-fresh-fixture-manifest"}
           else "image/x-portable-pixmap" if role.endswith("-ppm")
           else "application/x-executable" if role.endswith("-binary")
           or role in {"xbuild-final-elf", "xbuild-final-3dsx"}
           else "application/octet-stream" if role.endswith("-package")
           or role == "xbuild-upstream-snapshot-archive"
           else "text/plain")
    for role in ARTIFACT_ROLES
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def lstat_closure(root: Path) -> dict[str, Any]:
    """Hash node identity without losing symlink type or target spelling."""
    root = root.absolute()
    if root.is_symlink():
        raise RuntimeError(f"closure root may not be a symlink: {root}")
    root_real = root.resolve(strict=True)
    nodes: list[dict[str, Any]] = []
    paths = [root_real] if root_real.is_file() else [
        root_real, *root_real.rglob("*")]
    for path in sorted(paths, key=lambda value: (
            "." if value == root_real else value.relative_to(root_real).as_posix()).encode()):
        relative = "." if path == root_real else path.relative_to(root_real).as_posix()
        if unicodedata.normalize("NFC", relative) != relative or "\0" in relative:
            raise RuntimeError(f"non-canonical closure path: {relative!r}")
        info = path.lstat()
        mode = oct(stat.S_IMODE(info.st_mode))
        if stat.S_ISDIR(info.st_mode):
            row = {"path": relative, "type": "directory", "mode": mode}
        elif stat.S_ISREG(info.st_mode):
            row = {"path": relative, "type": "regular", "mode": mode,
                   "bytes": info.st_size, "sha256": sha_file(path)}
        elif stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            if unicodedata.normalize("NFC", target) != target or "\0" in target:
                raise RuntimeError(f"non-canonical symlink target: {relative}")
            resolved = path.resolve(strict=True)
            if root_real.is_dir() and root_real not in [resolved, *resolved.parents]:
                raise RuntimeError(f"symlink escapes closure root: {relative} -> {target}")
            row = {"path": relative, "type": "symlink", "mode": mode,
                   "target": target,
                   "resolved_path": resolved.relative_to(root_real).as_posix()}
        else:
            raise RuntimeError(f"unsupported closure node: {relative}")
        nodes.append(row)
    digest = sha_bytes(canonical(nodes))
    return {"algorithm": "lstat-tree-v1", "root_realpath": str(root_real),
            "node_count": len(nodes), "nodes": nodes, "sha256": digest}


def _run_identity(argv: list[str], env: dict[str, str]) -> bytes:
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"identity command failed ({result.returncode}): {argv}")
    return result.stdout


def tool_implementation_identity(tools: dict[str, str]) -> dict[str, Any]:
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"}
    if sys.platform == "darwin":
        developer_dir = _run_identity(
            ["/usr/bin/xcode-select", "-p"], env).decode().strip()
        env["DEVELOPER_DIR"] = developer_dir
        sdk_path = _run_identity(
            ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
            env).decode().strip()
    else:
        developer_dir = "/non-darwin"
        sdk_path = "/non-darwin"
    apple_names = {"python": "python3", "git": "git", "cxx": "clang++",
                   "nm": "nm"}
    rows = []
    for role in sorted(tools):
        dispatch = Path(tools[role]).resolve(strict=True)
        implementation = dispatch
        if sys.platform == "darwin" and role in apple_names and \
                dispatch.parent == Path("/usr/bin"):
            implementation = Path(_run_identity(
                ["/usr/bin/xcrun", "--find", apple_names[role]], env
            ).decode().strip()).resolve(strict=True)
        version = _run_identity([str(implementation), "--version"], env)
        rows.append({"role": role, "dispatch_realpath": str(dispatch),
                     "dispatch_sha256": sha_file(dispatch),
                     "implementation_realpath": str(implementation),
                     "implementation_bytes": implementation.stat().st_size,
                     "implementation_sha256": sha_file(implementation),
                     "version_sha256": sha_bytes(version)})
    target = _run_identity([str(Path(tools["cxx"]).resolve(strict=True)),
                            "-dumpmachine"], env).decode().strip()
    body = {"algorithm": "dispatched-tool-identity-v1",
            "developer_dir": developer_dir, "macos_sdk_realpath": sdk_path,
            "host_target": target, "tools": rows}
    body["sha256"] = sha_bytes(canonical(body))
    return body


def reviewer_ancestry_commitment(consumer: Any, repo: Path, head: str,
                                 git_path: str) -> dict[str, Any]:
    """Use the already verified consumer module; candidate paths stay data."""
    return consumer.raw_ancestry_commitment(git_path, repo, head, FORBIDDEN)


def baseline_identity(context: Any, consumer: Any, repo: Path,
                      git_path: str) -> dict[str, Any]:
    """Derive all non-selector baseline facts from the driver's verified context."""
    selected = context.record.get("baseline_identity")
    if not isinstance(selected, dict) or set(selected) != {"commit", "tree"}:
        raise RuntimeError("VERIFIED_BASELINE_IDENTITY_MISSING")
    commit = selected.get("commit", "")
    tree = selected.get("tree", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or \
       not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise RuntimeError("VERIFIED_BASELINE_IDENTITY_MALFORMED")
    ancestry = consumer.raw_ancestry_commitment(git_path, repo, commit, [])
    if ancestry["head"] != commit or ancestry["head_tree"] != tree or \
       len(ancestry["head_parents"]) != 1:
        raise RuntimeError("VERIFIED_BASELINE_IDENTITY_MISMATCH")
    tracked_fp, tracked_entries = fingerprint(repo, commit)
    return {
        "commit": commit,
        "tree": tree,
        "parent": ancestry["head_parents"][0],
        "tracked_fingerprint_v3": tracked_fp,
        "tracked_entries": tracked_entries,
    }


def reject_verdict_fields(value: Any) -> None:
    forbidden_keys = {
        "protocol_gates", "review_verdict", "product_verdicts",
        "failure_codes",
    }
    forbidden_values = {
        "ACCEPT_C3_EVIDENCE_PROTOCOL", "REJECT_C3_EVIDENCE_PROTOCOL",
    }
    if isinstance(value, dict):
        overlap = forbidden_keys.intersection(value)
        if overlap:
            raise RuntimeError("PRODUCER_VERDICT_FORBIDDEN: " +
                               ",".join(sorted(overlap)))
        for child in value.values():
            reject_verdict_fields(child)
    elif isinstance(value, list):
        for child in value:
            reject_verdict_fields(child)
    elif isinstance(value, str) and value in forbidden_values:
        raise RuntimeError("PRODUCER_VERDICT_FORBIDDEN: verdict value")


def strict_load_bytes(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate key {key}")
            result[key] = value
        return result
    def constant(value: str) -> None:
        raise ValueError(f"non-finite number {value}")
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                      parse_constant=constant)


def strict_load(path: Path) -> Any:
    return strict_load_bytes(path.read_bytes())


def git(repo: Path, *args: str, allow: tuple[int, ...] = (0,)) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode not in allow:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout


def fingerprint(repo: Path, revision: str,
                exact: Optional[set[str]] = None,
                prefixes: tuple[str, ...] = ()) -> tuple[str, int]:
    listing = git(repo, "ls-tree", "-r", "-z", "--full-tree", revision)
    digest = hashlib.sha256()
    count = 0
    for row in listing.split(b"\0"):
        if not row:
            continue
        meta, path_raw = row.split(b"\t", 1)
        mode, kind, oid = meta.split(b" ", 2)
        path = os.fsdecode(path_raw)
        if exact is not None and path not in exact and not path.startswith(prefixes):
            continue
        if kind == b"commit":
            raise RuntimeError(f"submodule rejected: {path}")
        payload = git(repo, "cat-file", "-p", oid.decode())
        for value in (mode, kind, path_raw, sha_bytes(payload).encode()):
            digest.update(value)
            digest.update(b"\0")
        count += 1
    return digest.hexdigest(), count


def source_tree(root: Path, run_id: str, tree_role: str,
                root_id: str) -> dict[str, Any]:
    files = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().encode()):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise RuntimeError(f"source symlink rejected: {relative}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError(f"source node rejected: {relative}")
        mode = "100755" if info.st_mode & 0o111 else "100644"
        files.append({"mode": mode, "path": relative, "bytes": info.st_size,
                      "sha256": sha_file(path)})
    digest = hashlib.sha256()
    for item in files:
        for value in (item["mode"], item["path"], str(item["bytes"]), item["sha256"]):
            digest.update(value.encode())
            digest.update(b"\0")
    return {
        "schema": "cth3ds.source-tree-manifest/v1", "tree_role": tree_role,
        "run_id": run_id, "source_root_id": root_id, "file_count": len(files),
        "files": files, "tree_digest": digest.hexdigest(),
    }


def fixture_digest(root: Path) -> str:
    wanted = ["bundle.json", "core.package.bin", "fixture-manifest.json",
              "lang/en.package.bin"]
    digest = hashlib.sha256()
    for relative in wanted:
        path = root / relative
        payload = path.read_bytes()
        for value in (relative.encode(), str(len(payload)).encode(),
                      sha_bytes(payload).encode()):
            digest.update(value)
            digest.update(b"\0")
    return digest.hexdigest()


def extract_archive(archive: Path, destination: Path) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError(f"archive destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            pure = Path(member.name)
            if not pure.parts or pure.parts[0] != "CorsixTH-56bd5d00f76331c7f76d7b696726a7926303ca0c":
                raise RuntimeError(f"archive top directory mismatch: {member.name}")
            relative = Path(*pure.parts[1:])
            if not relative.parts:
                continue
            if relative.is_absolute() or ".." in relative.parts or member.issym() or member.islnk():
                raise RuntimeError(f"unsafe archive member: {member.name}")
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = handle.extractfile(member)
                if source is None:
                    raise RuntimeError(f"cannot read archive member: {member.name}")
                target.write_bytes(source.read())
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise RuntimeError(f"unsupported archive member: {member.name}")


def integrate(repo: Path, integrated: Path) -> None:
    tool = repo / "tools/integrate_corsixth.py"
    for tail in (("--json",), ("--check", "--json")):
        result = subprocess.run(
            [sys.executable, str(tool), str(integrated),
             "--overlay-root", str(repo), *tail],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if result.returncode:
            raise RuntimeError(
                "integration tool failed: " + result.stderr.decode(errors="replace")
            )


def prepare_sources(repo: Path, archive: Path, snapshot: Path, integrated: Path,
                    upstream_manifest: Path, integrated_manifest: Path,
                    run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    extract_archive(archive, snapshot)
    if integrated.exists() and any(integrated.iterdir()):
        raise RuntimeError(f"integrated destination is not empty: {integrated}")
    shutil.copytree(snapshot, integrated, copy_function=shutil.copy2,
                    dirs_exist_ok=True)
    integrate(repo, integrated)
    upstream = source_tree(snapshot, run_id, "upstream-snapshot",
                           "source_upstream_snapshot")
    combined = source_tree(integrated, run_id, "integrated",
                           "source_xbuild_integrated")
    upstream_manifest.parent.mkdir(parents=True, exist_ok=True)
    upstream_manifest.write_bytes(canonical(upstream))
    integrated_manifest.write_bytes(canonical(combined))
    return upstream, combined


def tool_paths(context: Any) -> dict[str, str]:
    require_verified_invocation(context, ("fresh-chain",))
    identity_env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"}

    def host_find(*names: str) -> Optional[str]:
        if sys.platform == "darwin":
            identity_env["DEVELOPER_DIR"] = subprocess.check_output(
                ["/usr/bin/xcode-select", "-p"], text=True).strip()
            return subprocess.check_output(
                ["/usr/bin/xcrun", "--find", names[0]], env=identity_env,
                text=True).strip()
        for name in names:
            found = shutil.which(name)
            if found is not None:
                return found
        return None

    required = {
        "python": str(context.python),
        "cmake": shutil.which("cmake"),
        "ctest": shutil.which("ctest"), "git": host_find("git"),
        "cxx": host_find("clang++", "g++", "c++"), "nm": host_find("nm"),
        "cxx-linker": "/opt/devkitpro/devkitARM/bin/arm-none-eabi-g++",
        "symbol-reader": "/opt/devkitpro/devkitARM/bin/arm-none-eabi-nm",
        "elf-reader": "/opt/devkitpro/devkitARM/bin/arm-none-eabi-readelf",
        "disassembler": "/opt/devkitpro/devkitARM/bin/arm-none-eabi-objdump",
    }
    result = {}
    for role, raw in required.items():
        if raw is None:
            raise RuntimeError(f"tool missing: {role}")
        path = Path(raw).resolve(strict=True)
        if not path.is_file():
            raise RuntimeError(f"tool missing: {role}")
        result[role] = (str(Path(raw).absolute()) if role == "python" else str(path))
    return result


def python_dependencies() -> list[dict[str, Any]]:
    import jsonschema  # noqa: F401
    result = {}
    for name, expected_version in VERIFIER_DEPENDENCIES.items():
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise RuntimeError(f"verifier dependency missing: {name}") from error
        if distribution.version != expected_version:
            raise RuntimeError(
                f"verifier dependency version mismatch: {name}="
                f"{distribution.version}, expected {expected_version}")
        for entry in distribution.files or ():
            relative = Path(str(entry))
            if relative.suffix == ".pyc" or "__pycache__" in relative.parts:
                continue
            path = Path(distribution.locate_file(entry)).resolve(strict=True)
            if not path.is_file():
                raise RuntimeError(f"verifier dependency is not a file: {path}")
            if path.stat().st_size == 0:
                continue
            result[str(path)] = {"absolute_realpath": str(path),
                                 "bytes": path.stat().st_size,
                                 "sha256": sha_file(path)}
    return [result[key] for key in sorted(result)]


def root_records(run_root: Path, reviewer_root: Optional[Path] = None) -> list[dict[str, Any]]:
    specs = [
        ("candidate", "candidate", "readonly", ["artifact", "closure_input"]),
        ("evidence_raw", "evidence_raw", "producer_write_then_freeze",
         ["artifact", "invocation"]),
        ("build_host", "build", "producer_write_then_freeze", ["artifact", "build"]),
        ("build_red", "build", "producer_write_then_freeze", ["artifact", "build"]),
        ("source_upstream_snapshot", "source", "producer_write_then_freeze",
         ["source_file"]),
        ("source_xbuild_integrated", "source", "producer_write_then_freeze",
         ["source_file"]),
        ("build_xbuild", "build", "producer_write_then_freeze",
         ["artifact", "build"]),
        ("reviewer_bundle", "reviewer_bundle", "readonly",
         ["artifact", "closure_input"]),
        ("seal", "seal", "consumer_write_once", ["seal_output"]),
    ]
    return [{"root_id": root_id, "class": cls,
             "absolute_realpath": str((reviewer_root if root_id == "reviewer_bundle" and
                                        reviewer_root is not None else
                                        run_root / root_id).resolve()),
             "node_type": "directory", "access": access,
             "allowed_kinds": kinds}
            for root_id, cls, access, kinds in specs]


def role_root(role: str) -> str:
    if role.startswith("fixture-tracked-"):
        return "candidate"
    if role == "xbuild-upstream-snapshot-archive":
        return "reviewer_bundle"
    if role.startswith("host-") or role in {
        "cpp-test-binary", "simulator-binary", "runtime-probe-binary",
        "ctest-log", "simulator-top-ppm", "simulator-bottom-ppm",
        "simulator-trace-json",
    }:
        return "build_host" if role not in {
            "host-configure-stdout", "host-configure-stderr",
            "host-build-stdout", "host-build-stderr",
        } else "evidence_raw"
    if role.startswith("red-") or role in {"h1-binary", "h2-binary"}:
        return "build_red" if role not in {
            "red-configure-stdout", "red-configure-stderr",
            "red-build-stdout", "red-build-stderr",
        } else "evidence_raw"
    if role.startswith("xbuild-") and role not in {
        "xbuild-upstream-source-tree-manifest",
        "xbuild-integrated-source-tree-manifest",
        "xbuild-prepare-source-stdout", "xbuild-prepare-source-stderr",
        "xbuild-configure-stdout", "xbuild-configure-stderr",
        "xbuild-build-stdout", "xbuild-build-stderr",
        "xbuild-key-symbols", "xbuild-symbol-reader-stderr",
        "xbuild-elf-headers", "xbuild-elf-reader-stderr",
        "xbuild-allocator-call-disassembly", "xbuild-disassembler-stderr",
    }:
        return "build_xbuild"
    return "evidence_raw"


def owner_for(role: str, policy_id: str) -> tuple[str, str, str]:
    if role.startswith("fixture-tracked-"):
        return "fixture", "f-no-level-synthetic", role
    if role == "xbuild-upstream-snapshot-archive":
        return "policy", policy_id, "upstream_source_archive"
    for invocation, (_, _, outputs) in STREAM_OUTPUTS.items():
        stdout, stderr = STREAM_OUTPUTS[invocation][:2]
        if role in [stdout, stderr, *outputs]:
            return "invocation", "i-" + invocation.lower(), role
    raise RuntimeError(f"no owner for {role}")


def registry(policy_id: str) -> list[dict[str, Any]]:
    rows = []
    for role in BUILD_ROLES:
        root = {"host-regression": "build_host",
                "sanitized-red-observers": "build_red",
                "xbuild-old3ds": "build_xbuild"}[role]
        rows.append({"kind": "build", "role": role, "count": 1,
                     "allowed_root_ids": [root], "node_type": "directory",
                     "media_type": "inode/directory", "required_owner_kind": "none"})
    for role in TOOL_ROLES:
        rows.append({"kind": "tool", "role": role, "count": 1,
                     "allowed_root_ids": ["candidate"], "node_type": "regular_file",
                     "media_type": "application/x-executable",
                     "required_owner_kind": "none"})
    for role in ARTIFACT_ROLES:
        owner_kind = owner_for(role, policy_id)[0]
        rows.append({"kind": "artifact", "role": role, "count": 1,
                     "allowed_root_ids": [role_root(role)],
                     "node_type": "regular_file", "media_type": MEDIA[role],
                     "required_owner_kind": owner_kind})
    rows.append({"kind": "fixture", "role": "no-level-synthetic", "count": 1,
                 "allowed_root_ids": ["candidate", "evidence_raw"],
                 "node_type": "directory", "media_type": "inode/directory",
                 "required_owner_kind": "none"})
    for role in INVOCATION_ROLES:
        rows.append({"kind": "invocation", "role": role, "count": 1,
                     "allowed_root_ids": ["evidence_raw"], "node_type": "process_record",
                     "media_type": "application/json", "required_owner_kind": "none"})
    for role in CLOSURE_INPUTS:
        rows.append({"kind": "closure_input", "role": role, "count": 1,
                     "allowed_root_ids": ["candidate"], "node_type": "regular_file",
                     "media_type": "application/octet-stream",
                     "required_owner_kind": "none"})
    assert len(rows) == 115
    return rows


def command_records(context: Any, repo: Path, roots: dict[str, Path], tools: dict[str, str],
                    run_id: str, deps: Path) -> list[dict[str, Any]]:
    host = roots["build_host"]
    red = roots["build_red"]
    xbuild = roots["build_xbuild"]
    evidence = roots["evidence_raw"]
    fresh = evidence / "rh10-fresh"
    fixture = repo / "tests/runtime_core_v2/fixtures/no-level"
    h1 = red / "cth3ds-red-h1-level-requires-package"
    h2 = red / "cth3ds-red-h2-transition-lease-escape"
    simulator = host / "cth3ds-simulator"
    runtime_probe = host / "cth3ds-runtime-probe"
    cpp = host / "cth3ds-tests"
    internal_host_result = Path("/tmp") / ("cth3ds-host-unittest-" + run_id + ".json")
    argv = {
        "configure-host": [tools["cmake"], "-S", str(repo), "-B", str(host),
            "-DCTH3DS_BUILD_TESTS=ON", "-DCTH3DS_BUILD_SIMULATOR=ON",
            "-DCTH3DS_BUILD_3DS_SYNTAX_CHECK=ON",
            "-DCTH3DS_WARNINGS_AS_ERRORS=ON", "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"],
        "build-host": [tools["cmake"], "--build", str(host), "--parallel"],
        "ctest": [tools["ctest"], "--test-dir", str(host), "--output-on-failure"],
        "cpp": [str(cpp)],
        "python": context.child_command("_host-unittest", [
            "--repo", str(repo), "--output", str(internal_host_result)]),
        "simulator": [str(simulator), str(host / "simulator-direct")],
        "configure-red": [tools["cmake"], "-S", str(repo / "tests/runtime_core_v2"),
            "-B", str(red), "-DCTH3DS_ENABLE_SANITIZERS=ON",
            "-DCTH3DS_WARNINGS_AS_ERRORS=ON", "-DCMAKE_BUILD_TYPE=Debug",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"],
        "build-red": [tools["cmake"], "--build", str(red), "--parallel",
            "--target", "cth3ds-red-h1-level-requires-package",
            "cth3ds-red-h2-transition-lease-escape"],
        "nm-h1": [tools["nm"], "-u", str(h1)],
        "nm-h2": [tools["nm"], "-u", str(h2)],
        "rh10-generator": [str(context.python), "-I", str(context.driver),
            "in-process:fixture-generator",
            "--out", str(fresh), "--trace", str(evidence / "rh10-open-trace.json")],
        "RH09-H1": [str(h1), "--run-id", run_id, "--fixture", str(fixture),
                    "--level", "hospital-01"],
        "RH07-H2": [str(h2), "--run-id", run_id, "--fault",
                    "after-first-staged-acquire"],
        "prepare-xbuild-source": [str(context.python), "-I", str(context.driver),
            "in-process:prepare-xbuild-source",
            "--repo", str(repo), "--archive",
            str(roots["reviewer_bundle"] / "CorsixTH.tar.gz"),
            "--snapshot", str(roots["source_upstream_snapshot"]),
            "--integrated", str(roots["source_xbuild_integrated"]),
            "--upstream-manifest", str(evidence / "upstream-source-tree.json"),
            "--integrated-manifest", str(evidence / "integrated-source-tree.json"),
            "--run-id", run_id],
        "configure-xbuild": [tools["cmake"], "-S",
            str(roots["source_xbuild_integrated"]), "-B", str(xbuild),
            "-G", "Ninja", "-DCMAKE_TOOLCHAIN_FILE=/opt/devkitpro/cmake/3DS.cmake",
            "-DCMAKE_BUILD_TYPE=MinSizeRel", "-DCMAKE_PREFIX_PATH=" +
            str(deps) + ";/opt/devkitpro/portlibs/3ds",
            "-DCMAKE_FIND_ROOT_PATH=" + str(deps) +
            ";/opt/devkitpro/portlibs/3ds;/opt/devkitpro/libctru",
            "-DCORSIXTH_3DS=ON", "-DCORSIXTH_3DS_DEPS_PREFIX=" + str(deps),
            "-DBUILD_CORSIXTH=ON", "-DBUILD_ANIMVIEW=OFF", "-DBUILD_TOOLS=OFF",
            "-DENABLE_UNIT_TESTS=OFF", "-DENABLE_SANITIZERS=OFF",
            "-DWITH_TRACY=OFF", "-DWITH_MOVIES=OFF", "-DWITH_UPDATE_CHECK=OFF",
            "-DWITH_MIDI_DEVICE=OFF", "-DFETCH_SOUNDFONT=OFF",
            "-DFETCH_UNICODE_FONT=OFF", "-DUSE_SOURCE_DATADIRS=OFF",
            "-DSEARCH_LOCAL_DATADIRS=OFF", "-DWITH_FONT=",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"],
        "build-xbuild": [tools["cmake"], "--build", str(xbuild), "--parallel", "4",
                         "--target", "corsixth_3dsx"],
        "xbuild-symbol-reader": [tools["symbol-reader"], "-C", "-S",
            "--defined-only", str(xbuild / "CorsixTH/CorsixTH-3DS.elf")],
        "xbuild-elf-reader": [tools["elf-reader"], "-h", "-SW",
            str(xbuild / "CorsixTH/CorsixTH-3DS.elf")],
        "xbuild-disassembler": [tools["disassembler"], "-d", "-C",
            str(xbuild / "CorsixTH/CorsixTH-3DS.elf")],
    }
    executable = {
        "cpp": ("artifact", "cpp-test-binary"),
        "simulator": ("artifact", "simulator-binary"),
        "RH09-H1": ("artifact", "h1-binary"),
        "RH07-H2": ("artifact", "h2-binary"),
    }
    tool_role = {
        "configure-host": "cmake", "build-host": "cmake", "ctest": "ctest",
        "python": "python", "configure-red": "cmake", "build-red": "cmake",
        "nm-h1": "nm", "nm-h2": "nm", "rh10-generator": "python",
        "prepare-xbuild-source": "python", "configure-xbuild": "cmake",
        "build-xbuild": "cmake", "xbuild-symbol-reader": "symbol-reader",
        "xbuild-elf-reader": "elf-reader", "xbuild-disassembler": "disassembler",
    }
    profiles = {
        "python": "python-regression-v1",
        "configure-red": "asan-ubsan-red-v1", "build-red": "asan-ubsan-red-v1",
        "nm-h1": "asan-ubsan-red-v1", "nm-h2": "asan-ubsan-red-v1",
        "RH09-H1": "asan-ubsan-red-v1", "RH07-H2": "asan-ubsan-red-v1",
        "prepare-xbuild-source": "devkitarm-xbuild-v1",
        "configure-xbuild": "devkitarm-xbuild-v1",
        "build-xbuild": "devkitarm-xbuild-v1",
        "xbuild-symbol-reader": "devkitarm-xbuild-v1",
        "xbuild-elf-reader": "devkitarm-xbuild-v1",
        "xbuild-disassembler": "devkitarm-xbuild-v1",
    }
    cwd = {
        "prepare-xbuild-source": "evidence_raw",
        "configure-xbuild": "source_xbuild_integrated",
        "build-xbuild": "build_xbuild",
        "xbuild-symbol-reader": "build_xbuild",
        "xbuild-elf-reader": "build_xbuild",
        "xbuild-disassembler": "build_xbuild",
    }
    rows = []
    for role in INVOCATION_ROLES:
        kind, exe_role = executable.get(role, ("tool", tool_role.get(role, "cmake")))
        stdout, stderr, outputs = STREAM_OUTPUTS[role]
        rows.append({"command_id": "cmd-" + role.lower(), "role": role,
            "gate_id": role, "executable_kind": kind,
            "executable_role": exe_role, "argv": argv[role],
            "cwd_root_id": cwd.get(role, "candidate"),
            "environment_profile_id": profiles.get(role, "host-v1"),
            "timeout_seconds": 3600 if role in {"build-host", "python", "build-xbuild"}
            else 900, "stdout_role": stdout, "stderr_role": stderr,
            "output_roles": outputs})
    return rows


def build_policy(context: Any, consumer: Any, args: argparse.Namespace) -> int:
    from jsonschema import Draft202012Validator, FormatChecker

    require_verified_invocation(context, ("fresh-chain",))
    authority = context.require_validation_authority(
        args.validation_change_authority)

    if not args.review_session_id or not re.fullmatch(
            r"[0-9a-f]{32}", args.review_session_id):
        raise RuntimeError("fresh-chain review session id required")
    if args.session_root is None:
        raise RuntimeError("fresh-chain session root required")
    repo = args.repo.resolve(strict=True)
    executing_repo = context.repo.resolve(strict=True)
    archive = args.archive.resolve(strict=True)
    deps = args.deps_prefix.resolve(strict=True)
    run_root = args.run_root.resolve()
    if run_root.exists() and any(run_root.iterdir()):
        raise RuntimeError(f"run root must be fresh and empty: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    reviewer_root = args.reviewer_root.resolve() if args.reviewer_root else None
    roots = root_records(run_root, reviewer_root)
    root_map = {row["root_id"]: Path(row["absolute_realpath"]) for row in roots}
    root_map["candidate"] = repo
    for row in roots:
        if row["root_id"] == "candidate":
            row["absolute_realpath"] = str(repo)
        Path(row["absolute_realpath"]).mkdir(parents=True, exist_ok=True)
    reviewer_archive = root_map["reviewer_bundle"] / "CorsixTH.tar.gz"
    shutil.copyfile(archive, reviewer_archive)
    if reviewer_archive.stat().st_size != 4416083 or sha_file(reviewer_archive) != ARCHIVE_SHA:
        raise RuntimeError("upstream archive identity mismatch")

    tools = tool_paths(context)
    head = git(repo, "rev-parse", "HEAD^{commit}").decode().strip()
    if head != context.record["repository"]["head"]:
        raise RuntimeError("EXECUTING_CANDIDATE_HEAD_MISMATCH")
    for role, relative in (("producer", "scripts/verify_runtime_core_v2.py"),
                           ("consumer", "scripts/consume_runtime_core_v2.py"),
                           ("runner", "tests/runtime_core_v2/evidence_protocol_adversarial.py"),
                           ("driver", "scripts/verifier_driver.py"),
                           ("host_python_runner", "scripts/run_host_python_suite.py"),
                           ("host_python_manifest", "tests/host-python-suite.json")):
        if sha_file(repo / relative) != context.record["source_closure"][role]["sha256"]:
            raise RuntimeError("EXECUTING_SOURCE_CLOSURE_MISMATCH: " + role)
    ancestry = reviewer_ancestry_commitment(consumer, repo, head, tools["git"])
    tree = ancestry["head_tree"]
    base = baseline_identity(context, consumer, repo, tools["git"])
    if base["commit"] != authority["baseline"]["commit"] or \
            base["tree"] != authority["baseline"]["tree"]:
        raise RuntimeError("VALIDATION_AUTHORITY_BASELINE_MISMATCH")
    if ancestry["head_parents"] != [base["commit"]]:
        raise RuntimeError("candidate first parent is not the remediation baseline")
    tracked_fp, tracked_entries = fingerprint(repo, head)
    product_fp, product_entries = fingerprint(
        repo, head, {"tools/th3ds_convert.py", "scripts/build_3ds.sh",
                     "scripts/bootstrap_upstream.sh"},
        ("cmake/", "include/", "src/", "lua/"))
    expected_product = authority["product_boundary"]
    if expected_product["sha256"] != PRODUCT_FP or \
            product_fp != PRODUCT_FP or \
            product_entries != expected_product["entry_count"]:
        raise RuntimeError("VALIDATION_AUTHORITY_PRODUCT_MISMATCH")

    run_id = uuid.uuid4().hex
    policy_id = "c3-" + run_id
    upstream_manifest = root_map["evidence_raw"] / "policy-upstream-unused.json"
    integrated_manifest = root_map["evidence_raw"] / "policy-integrated-unused.json"
    with tempfile.TemporaryDirectory(prefix="cth3ds-c3-reviewer-") as temp:
        temp_root = Path(temp)
        upstream, combined = prepare_sources(
            repo, reviewer_archive, temp_root / "upstream", temp_root / "integrated",
            temp_root / "upstream.json", temp_root / "integrated.json", run_id)
    if upstream["file_count"] != 644 or upstream["tree_digest"] != UPSTREAM_DIGEST:
        raise RuntimeError("reviewer upstream tree expectation mismatch")

    tool_identity = tool_implementation_identity(tools)
    xbuild_roots = {
        "deps_prefix": deps,
        "devkitarm": Path("/opt/devkitpro/devkitARM"),
        "devkitpro_tools": Path("/opt/devkitpro/tools"),
        "libctru": Path("/opt/devkitpro/libctru"),
        "portlibs_3ds": Path("/opt/devkitpro/portlibs/3ds"),
        "cmake_3ds": Path("/opt/devkitpro/cmake/3DS.cmake"),
    }
    xbuild_closures = {name: lstat_closure(path)
                       for name, path in sorted(xbuild_roots.items())}
    paths = {row["root_id"]: Path(row["absolute_realpath"]) for row in roots}
    commands = command_records(context, repo, paths, tools, run_id, deps)
    host_manifest_path = repo / "tests/host-python-suite.json"
    host_manifest = json.loads(host_manifest_path.read_text(encoding="utf-8"))
    closure = []
    for role, relative in CLOSURE_INPUTS.items():
        path = repo / relative
        closure.append({"closure_input_id": "ci-" + role, "role": role,
                        "root_id": "candidate", "relative_path": relative,
                        "bytes": path.stat().st_size, "sha256": sha_file(path)})
    overlay = []
    module_path = repo / "tools/integrate_corsixth.py"
    spec = importlib.util.spec_from_file_location("c3_policy_integrator", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load integrator for overlay mapping")
    module = importlib.util.module_from_spec(spec)
    sys.modules["c3_policy_integrator"] = module
    spec.loader.exec_module(module)
    for source, target in module.iter_overlay_files(repo):
        relative = source.relative_to(repo).as_posix()
        row = git(repo, "ls-files", "-s", "--", relative).decode().strip().split()
        if len(row) < 4:
            raise RuntimeError(f"overlay source is untracked: {relative}")
        overlay.append({"candidate_path": relative, "candidate_blob": row[1],
                        "integrated_path": target.as_posix(), "mode": row[0]})

    base_env = {
        "PATH": os.environ.get(
            "PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
        "LC_ALL": "C", "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": tempfile.gettempdir(),
    }
    if sys.platform == "darwin":
        base_env["DEVELOPER_DIR"] = tool_identity["developer_dir"]
    policy = {
        "schema": "cth3ds.runtime-core-review-policy/v6", "stage_id": "C3-R5",
        "policy_id": policy_id, "created_at": now(), "base_identity": base,
        "verified_invocation": context.record,
        "verified_invocation_sha256": context.digest,
        "validation_change_authority": authority,
        "candidate_identity": {
            "required_first_parent": base["commit"], "forbidden_ancestors": FORBIDDEN,
            "expected_commit": head, "expected_tree": tree,
            "expected_candidate_fingerprint": tracked_fp,
            "expected_candidate_entries": tracked_entries, "require_clean": True,
            "ancestry": ancestry,
        },
        "product_boundary": {
            "fingerprint_algorithm": "v3-mode-type-path-payload-sha256-nul",
            "product_exact": ["tools/th3ds_convert.py", "scripts/build_3ds.sh",
                              "scripts/bootstrap_upstream.sh"],
            "product_prefixes": ["cmake/", "include/", "src/", "lua/"],
            "expected_product_fingerprint": expected_product["sha256"],
            "expected_product_entries": expected_product["entry_count"],
            "allowlist_exact": list(authority["authorized_diff_exact"]),
            "forbidden_patterns": ["config/**", "tests/** except tests/runtime_core_v2/**",
                                   "game-data", "build-output-in-repository"],
            "require_product_diff_empty": True,
        },
        "roots": roots, "role_registry": registry(policy_id),
        "environment_profiles": [
            {"profile_id": "host-v1", "clear_environment": True,
             "variables": base_env, "unset_variables": ["HOME", "PYTHONPATH"],
             "locale": "C"},
            {"profile_id": "python-regression-v1", "clear_environment": True,
             "variables": {**base_env,
                 "CTH3DS_RUNTIME_PROBE": str(root_map["build_host"] / "cth3ds-runtime-probe"),
                 "CTH3DS_SIMULATOR": str(root_map["build_host"] / "cth3ds-simulator")},
             "unset_variables": ["HOME", "PYTHONPATH"], "locale": "C"},
            {"profile_id": "asan-ubsan-red-v1", "clear_environment": True,
             "variables": {**base_env,
                 "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                 "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"},
             "unset_variables": ["HOME", "PYTHONPATH"], "locale": "C"},
            {"profile_id": "devkitarm-xbuild-v1", "clear_environment": True,
             "variables": {**base_env, "DEVKITPRO": "/opt/devkitpro",
                 "DEVKITARM": "/opt/devkitpro/devkitARM",
                 "PATH": "/opt/devkitpro/devkitARM/bin:/opt/devkitpro/tools/bin:" +
                         base_env["PATH"]},
             "unset_variables": ["HOME", "PYTHONPATH"], "locale": "C"},
        ],
        "commands": commands,
        "gate_oracles": {
            "pool_order": ["audio", "sprite", "texture", "language_font",
                           "metadata", "scratch", "other"],
            "backend_order": ["regular", "linear"],
            "stable_states": ["MENU_STABLE", "LEVEL_STABLE"],
            "h1": {"oracle_id": "H1_LEVEL_REQUIRES_DECLARED_PACKAGE",
                   "failure_code": "H1_LEVEL_NOT_DECLARED_ACCEPTED"},
            "h2": {"oracle_id": "H2_TRANSITION_CAPABILITY_ROLLBACK",
                   "failure_code": "H2_ESCAPED_CAPABILITY_PUBLISHED_STABLE"},
        },
        "rh10_provenance": {
            "fixture_role": "no-level-synthetic",
            "payload_origin": "generated_synthetic",
            "contains_original_theme_hospital_data": False,
            "container_schema_claim": {"contains_user_game_data": True,
                                       "redistributable": False},
            "container_claim_scope": "TH3DSR1_container_safety_classification",
        },
        "upstream_source": {
            "archive_artifact_id": "a-xbuild-upstream-snapshot-archive",
            "archive_root_id": "reviewer_bundle",
            "archive_relative_path": "CorsixTH.tar.gz", "archive_bytes": 4416083,
            "archive_sha256": ARCHIVE_SHA,
            "archive_top_directory": "CorsixTH-56bd5d00f76331c7f76d7b696726a7926303ca0c/",
            "snapshot_root_id": "source_upstream_snapshot",
            "upstream_tree_manifest_artifact_id": "a-xbuild-upstream-source-tree-manifest",
            "upstream_expected_file_count": 644,
            "upstream_expected_tree_digest": UPSTREAM_DIGEST,
            "integrated_root_id": "source_xbuild_integrated",
            "integrated_tree_manifest_artifact_id": "a-xbuild-integrated-source-tree-manifest",
            "integrated_expected_file_count": combined["file_count"],
            "integrated_expected_tree_digest": combined["tree_digest"],
            "overlay_mapping": overlay, "tree_digest_algorithm": "source-tree-v1",
        },
        "closure_inputs": closure,
        "host_regression": {
            "unexpected_skipped": 0,
            "allowed_skip_reason_prefixes": host_manifest["allowed_skip_reason_prefixes"],
            "runner_path": "scripts/run_host_python_suite.py",
            "runner_sha256": sha_file(repo / "scripts/run_host_python_suite.py"),
            "manifest_path": "tests/host-python-suite.json",
            "manifest_sha256": sha_file(host_manifest_path),
            "baseline_count": host_manifest["baseline"]["count"],
            "baseline_sorted_ids_sha256": host_manifest["baseline"]["sorted_ids_sha256"],
            "selected_count": host_manifest["selected_count"],
            "selected_sorted_ids_sha256": host_manifest["selected_sorted_ids_sha256"],
            "interpreter_executable": context.record["python"]["executable"],
            "interpreter_version": context.record["python"]["version"],
            "interpreter_implementation_sha256": context.record["python"]["implementation_sha256"],
        },
        "simulator_semantic_baseline": {
            "top": sha_file(repo / "assets/simulator-baseline/top.ppm"),
            "bottom": sha_file(repo / "assets/simulator-baseline/bottom.ppm"),
            "trace": sha_file(repo / "assets/simulator-baseline/trace.json")},
        "tool_implementation_identity": tool_identity,
        "xbuild_input_closures": xbuild_closures,
        "fresh_chain": {
            "review_session_id": args.review_session_id,
            "session_root_realpath": str(args.session_root.resolve(strict=True))
                if args.session_root else str(run_root.parent.resolve()),
            "initial_entry_count": 0,
            "allowed_external_input_roles": [
                "candidate", "archive", "deps_prefix", "frozen_matrix",
                "base_acceptance_cases", "r4_acceptance_cases"],
            "forbidden_prior_artifact_roles": [
                "facts", "closure_fixture", "matrix_receipt", "final_seal"],
            "canonical_seal_writer": "finalizer",
            "closure_fixture_owner": "reviewer_matrix_runner",
        },
        "acceptance_inputs": {
            "matrix_sha256": MATRIX_SHA256,
            "matrix_total": 60,
            "matrix_case_id_set": "E01..E60",
            "runner_relative_path":
                "tests/runtime_core_v2/evidence_protocol_adversarial.py",
            "runner_sha256": sha_file(
                repo / "tests/runtime_core_v2/evidence_protocol_adversarial.py"),
            "fact_consumer_relative_path": "scripts/consume_runtime_core_v2.py",
            "fact_consumer_sha256": sha_file(
                repo / "scripts/consume_runtime_core_v2.py"),
            "finalizer_relative_path": "scripts/consume_runtime_core_v2.py",
            "finalizer_sha256": sha_file(
                repo / "scripts/consume_runtime_core_v2.py"),
            "result_schema_sha256": sha_file(
                repo / "tests/runtime_core_v2/result.schema.json"),
            "required_protocol_gate_ids": REQUIRED_PROTOCOL_GATES,
            "required_product_baseline": REQUIRED_PRODUCT_BASELINE,
        },
        "limits": {"max_artifact_bytes": 268435456,
                   "max_source_file_bytes": 67108864, "max_source_files": 4096},
    }
    schema_path = repo / "tests/runtime_core_v2/review-policy.schema.json"
    schema = strict_load(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(
        schema, format_checker=FormatChecker()).iter_errors(policy),
        key=lambda error: [str(x) for x in error.path])
    if errors:
        raise RuntimeError("policy schema: " + errors[0].message)
    policy_path = root_map["reviewer_bundle"] / "review-policy.json"
    policy_path.write_bytes(canonical(policy))
    reviewer_archive.chmod(0o444)
    policy_path.chmod(0o444)
    root_map["reviewer_bundle"].chmod(0o555)
    print(json.dumps({"policy": str(policy_path),
                      "policy_sha256": sha_file(policy_path), "run_id": run_id,
                      "integrated_expected_file_count": combined["file_count"],
                      "integrated_expected_tree_digest": combined["tree_digest"]},
                     sort_keys=True, separators=(",", ":")))
    return 0


def environment(policy: dict[str, Any], profile_id: str) -> dict[str, str]:
    profile = next(item for item in policy["environment_profiles"]
                   if item["profile_id"] == profile_id)
    return dict(profile["variables"])


def artifact_path(role: str, repo: Path, roots: dict[str, Path]) -> Path:
    fixed = {
        "host-cmake-cache": roots["build_host"] / "CMakeCache.txt",
        "host-compile-commands": roots["build_host"] / "compile_commands.json",
        "cpp-test-binary": roots["build_host"] / "cth3ds-tests",
        "simulator-binary": roots["build_host"] / "cth3ds-simulator",
        "runtime-probe-binary": roots["build_host"] / "cth3ds-runtime-probe",
        "ctest-log": roots["build_host"] / "Testing/Temporary/LastTest.log",
        "simulator-top-ppm": roots["build_host"] / "simulator-direct/top.ppm",
        "simulator-bottom-ppm": roots["build_host"] / "simulator-direct/bottom.ppm",
        "simulator-trace-json": roots["build_host"] / "simulator-direct/trace.json",
        "red-cmake-cache": roots["build_red"] / "CMakeCache.txt",
        "red-compile-commands": roots["build_red"] / "compile_commands.json",
        "h1-binary": roots["build_red"] / "cth3ds-red-h1-level-requires-package",
        "h2-binary": roots["build_red"] / "cth3ds-red-h2-transition-lease-escape",
        "rh10-open-trace": roots["evidence_raw"] / "rh10-open-trace.json",
        "fixture-tracked-bundle-json": repo / "tests/runtime_core_v2/fixtures/no-level/bundle.json",
        "fixture-tracked-fixture-manifest": repo / "tests/runtime_core_v2/fixtures/no-level/fixture-manifest.json",
        "fixture-tracked-core-package": repo / "tests/runtime_core_v2/fixtures/no-level/core.package.bin",
        "fixture-tracked-language-package": repo / "tests/runtime_core_v2/fixtures/no-level/lang/en.package.bin",
        "fixture-fresh-bundle-json": roots["evidence_raw"] / "rh10-fresh/bundle.json",
        "fixture-fresh-fixture-manifest": roots["evidence_raw"] / "rh10-fresh/fixture-manifest.json",
        "fixture-fresh-core-package": roots["evidence_raw"] / "rh10-fresh/core.package.bin",
        "fixture-fresh-language-package": roots["evidence_raw"] / "rh10-fresh/lang/en.package.bin",
        "xbuild-upstream-snapshot-archive": roots["reviewer_bundle"] / "CorsixTH.tar.gz",
        "xbuild-upstream-source-tree-manifest": roots["evidence_raw"] / "upstream-source-tree.json",
        "xbuild-integrated-source-tree-manifest": roots["evidence_raw"] / "integrated-source-tree.json",
        "xbuild-cmake-cache": roots["build_xbuild"] / "CMakeCache.txt",
        "xbuild-compile-commands": roots["build_xbuild"] / "compile_commands.json",
        "xbuild-build-graph": roots["build_xbuild"] / "build.ninja",
        "xbuild-final-elf": roots["build_xbuild"] / "CorsixTH/CorsixTH-3DS.elf",
        "xbuild-final-3dsx": roots["build_xbuild"] / "CorsixTH-3DS.3dsx",
    }
    if role in fixed:
        return fixed[role]
    return roots["evidence_raw"] / (role + (".json" if MEDIA[role] == "application/json" else ".txt"))


def execute(context: Any, command: dict[str, Any], policy: dict[str, Any], repo: Path,
            roots: dict[str, Path]) -> dict[str, Any]:
    stdout_role, stderr_role = command["stdout_role"], command["stderr_role"]
    stdout_path = artifact_path(stdout_role, repo, roots)
    stderr_path = artifact_path(stderr_role, repo, roots)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    started = now()
    timed_out = False
    signal = None
    try:
        if command["role"] == "rh10-generator":
            module_path = repo / "tests/runtime_core_v2/generate_no_level_fixture.py"
            spec = importlib.util.spec_from_file_location("cth3ds_verified_fixture_generator", module_path)
            if spec is None or spec.loader is None:
                raise RuntimeError("cannot load fixture generator")
            module = importlib.util.module_from_spec(spec)
            sys.modules["cth3ds_verified_fixture_generator"] = module
            spec.loader.exec_module(module)
            output = io.StringIO()
            errors = io.StringIO()
            previous = sys.argv
            sys.argv = [str(module_path), "--out", str(roots["evidence_raw"] / "rh10-fresh"),
                        "--trace", str(roots["evidence_raw"] / "rh10-open-trace.json")]
            try:
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    code = int(module.main() or 0)
            finally:
                sys.argv = previous
            stdout, stderr = output.getvalue().encode(), errors.getvalue().encode()
        elif command["role"] == "prepare-xbuild-source":
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                upstream, combined = prepare_sources(
                    repo, roots["reviewer_bundle"] / "CorsixTH.tar.gz",
                    roots["source_upstream_snapshot"], roots["source_xbuild_integrated"],
                    roots["evidence_raw"] / "upstream-source-tree.json",
                    roots["evidence_raw"] / "integrated-source-tree.json",
                    policy["policy_id"][3:])
                print(json.dumps({"upstream_file_count": upstream["file_count"],
                                  "integrated_file_count": combined["file_count"]},
                                 sort_keys=True))
            code, stdout, stderr = 0, output.getvalue().encode(), b""
        else:
            proc = subprocess.run(command["argv"], cwd=roots[command["cwd_root_id"]],
                env=environment(policy, command["environment_profile_id"]),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                timeout=command["timeout_seconds"])
            code = proc.returncode
            stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        code = 124
        stdout, stderr = error.stdout or b"", error.stderr or b""
    if code < 0:
        signal = -code
        code = 128 + signal
    finished = now()
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    invocation_id = "i-" + command["role"].lower()
    return {
        "invocation_id": invocation_id, "role": command["role"],
        "gate_id": command["gate_id"], "run_id": policy["policy_id"][3:],
        "executable_kind": command["executable_kind"],
        "executable_id": (("t-" if command["executable_kind"] == "tool" else "a-") +
                          command["executable_role"]),
        "argv": command["argv"], "cwd_root_id": command["cwd_root_id"],
        "environment_profile_id": command["environment_profile_id"],
        "started_at": started, "finished_at": finished, "exit_code": code,
        "signal": signal, "timed_out": timed_out, "stream_truncated": False,
        "stdout_artifact_id": "a-" + stdout_role,
        "stderr_artifact_id": "a-" + stderr_role,
        "observation_artifact_id": ("a-" + stdout_role
            if command["role"] in {"RH09-H1", "RH07-H2"} else None),
        "output_artifact_ids": ["a-" + role for role in command["output_roles"]],
    }


def freeze(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        mode = 0o555 if path.is_dir() or path.stat().st_mode & 0o111 else 0o444
        path.chmod(mode)
    root.chmod(0o555)


def produce(context: Any, args: argparse.Namespace) -> int:
    from jsonschema import Draft202012Validator, FormatChecker

    require_verified_invocation(context, ("fresh-chain",))

    policy_path = args.policy.resolve(strict=True)
    raw = policy_path.read_bytes()
    if sha_bytes(raw) != args.expected_policy_sha256:
        raise RuntimeError("policy hash mismatch")
    policy = strict_load_bytes(raw)
    require_policy_context(context, policy)
    repo = next(Path(item["absolute_realpath"]) for item in policy["roots"]
                if item["root_id"] == "candidate")
    schema = strict_load(repo / "tests/runtime_core_v2/review-policy.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(
        schema, format_checker=FormatChecker()).iter_errors(policy))
    if errors:
        raise RuntimeError("policy schema invalid: " + errors[0].message)
    roots = {item["root_id"]: Path(item["absolute_realpath"])
             for item in policy["roots"]}
    for root_id in ("evidence_raw", "build_host", "build_red",
                    "source_upstream_snapshot", "source_xbuild_integrated",
                    "build_xbuild"):
        if any(roots[root_id].iterdir()):
            raise RuntimeError(f"producer root not empty: {root_id}")
    if any(roots["seal"].iterdir()):
        raise RuntimeError("seal root is not empty")

    tools = tool_paths(context)
    before = {role: (Path(path).stat().st_size, sha_file(Path(path)))
              for role, path in tools.items()}
    invocations = []
    for command in policy["commands"]:
        invocation = execute(context, command, policy, repo, roots)
        invocations.append(invocation)
        if invocation["timed_out"] or invocation["signal"] is not None or \
           invocation["exit_code"] != 0:
            stdout_detail = artifact_path(
                command["stdout_role"], repo, roots).read_text(errors="replace")
            stderr_detail = artifact_path(
                command["stderr_role"], repo, roots).read_text(errors="replace")
            detail = ("stdout-tail:\n" + stdout_detail[-6000:] +
                      "\nstderr-tail:\n" + stderr_detail[-3000:])
            raise RuntimeError(f"{command['role']} failed: {detail}")
        for role in command["output_roles"]:
            path = artifact_path(role, repo, roots)
            if not path.is_file():
                raise RuntimeError(f"{command['role']} missing output {role}")

    if tool_implementation_identity(tools) != policy["tool_implementation_identity"]:
        raise RuntimeError("TOOL_IMPLEMENTATION_IDENTITY_MISMATCH")
    for name, expected in policy["xbuild_input_closures"].items():
        observed = lstat_closure(Path(expected["root_realpath"]))
        if observed != expected:
            raise RuntimeError(f"XBUILD_INPUT_CLOSURE_MISMATCH: {name}")

    tool_rows = []
    deps = python_dependencies()
    for role in TOOL_ROLES:
        path = Path(tools[role])
        after = (path.stat().st_size, sha_file(path))
        tool_rows.append({"tool_id": "t-" + role, "role": role,
            "absolute_realpath": str(path), "bytes_before": before[role][0],
            "sha256_before": before[role][1], "bytes_after": after[0],
            "sha256_after": after[1],
            "runtime_dependency_files": deps if role == "python" else []})

    artifacts = []
    for role in ARTIFACT_ROLES:
        path = artifact_path(role, repo, roots)
        root_id = role_root(role)
        root = roots[root_id]
        relative = path.relative_to(root).as_posix()
        owner_kind, owner_id, slot = owner_for(role, policy["policy_id"])
        artifacts.append({"artifact_id": "a-" + role, "role": role,
            "root_id": root_id, "relative_path": relative,
            "media_type": MEDIA[role], "bytes": path.stat().st_size,
            "sha256": sha_file(path),
            "canonical_owner": {"kind": owner_kind, "id": owner_id, "slot": slot}})

    tracked = [item["artifact_id"] for item in artifacts
               if item["role"].startswith("fixture-tracked-")]
    fresh = [item["artifact_id"] for item in artifacts
             if item["role"].startswith("fixture-fresh-")]
    fixture_root = repo / "tests/runtime_core_v2/fixtures/no-level"
    fresh_root = roots["evidence_raw"] / "rh10-fresh"
    fixtures = [{"fixture_id": "f-no-level-synthetic",
        "role": "no-level-synthetic", "tracked_artifact_ids": tracked,
        "fresh_artifact_ids": fresh,
        "directory_digest_algorithm": "fixture-directory-v1",
        "tracked_directory_digest": fixture_digest(fixture_root),
        "fresh_directory_digest": fixture_digest(fresh_root)}]
    inv_by_role = {item["role"]: item for item in invocations}
    builds = [
        {"build_id": "b-host-regression", "role": "host-regression",
         "source_root_id": "candidate", "build_root_id": "build_host",
         "configure_invocation_id": inv_by_role["configure-host"]["invocation_id"],
         "build_invocation_id": inv_by_role["build-host"]["invocation_id"],
         "cmake_cache_artifact_id": "a-host-cmake-cache",
         "compile_commands_artifact_id": "a-host-compile-commands",
         "input_artifact_ids": [], "output_artifact_ids":
         ["a-cpp-test-binary", "a-simulator-binary", "a-runtime-probe-binary"],
         "sanitizer_profile_id": "none",
         "tool_ids": ["t-cmake", "t-cxx"]},
        {"build_id": "b-sanitized-red-observers",
         "role": "sanitized-red-observers", "source_root_id": "candidate",
         "build_root_id": "build_red",
         "configure_invocation_id": inv_by_role["configure-red"]["invocation_id"],
         "build_invocation_id": inv_by_role["build-red"]["invocation_id"],
         "cmake_cache_artifact_id": "a-red-cmake-cache",
         "compile_commands_artifact_id": "a-red-compile-commands",
         "input_artifact_ids": [], "output_artifact_ids":
         ["a-h1-binary", "a-h2-binary"],
         "sanitizer_profile_id": "asan-ubsan-red-v1",
         "tool_ids": ["t-cmake", "t-cxx", "t-nm"]},
        {"build_id": "b-xbuild-old3ds", "role": "xbuild-old3ds",
         "source_root_id": "source_xbuild_integrated",
         "build_root_id": "build_xbuild",
         "configure_invocation_id": inv_by_role["configure-xbuild"]["invocation_id"],
         "build_invocation_id": inv_by_role["build-xbuild"]["invocation_id"],
         "cmake_cache_artifact_id": "a-xbuild-cmake-cache",
         "compile_commands_artifact_id": "a-xbuild-compile-commands",
         "input_artifact_ids": ["a-xbuild-upstream-snapshot-archive",
             "a-xbuild-upstream-source-tree-manifest",
             "a-xbuild-integrated-source-tree-manifest"],
         "output_artifact_ids": ["a-xbuild-final-elf", "a-xbuild-final-3dsx"],
         "sanitizer_profile_id": "none",
         "tool_ids": ["t-cmake", "t-cxx-linker", "t-symbol-reader",
                      "t-elf-reader", "t-disassembler"]},
    ]
    manifest = {
        "schema": "cth3ds.runtime-core-evidence/v4", "stage_id": "C3",
        "run_id": policy["policy_id"][3:],
        "producer_version": "cth3ds-runtime-core-observer/4",
        "policy_id": policy["policy_id"],
        "policy_sha256": args.expected_policy_sha256, "created_at": now(),
        "base_identity": policy["base_identity"],
        "candidate_identity": {
            "commit": policy["candidate_identity"]["expected_commit"],
            "tree": policy["candidate_identity"]["expected_tree"],
            "first_parent": policy["base_identity"]["commit"],
            "tracked_fingerprint_v3":
                policy["candidate_identity"]["expected_candidate_fingerprint"],
            "tracked_entries":
                policy["candidate_identity"]["expected_candidate_entries"],
        },
        "product_fingerprint": {
            "algorithm": "v3-mode-type-path-payload-sha256-nul",
            "sha256": policy["product_boundary"]["expected_product_fingerprint"],
            "entries": policy["product_boundary"]["expected_product_entries"]},
        "builds": builds, "tools": tool_rows, "artifacts": artifacts,
        "fixtures": fixtures, "invocations": invocations,
    }
    reject_verdict_fields(manifest)
    manifest_schema = strict_load(repo / "tests/runtime_core_v2/evidence-manifest.schema.json")
    Draft202012Validator.check_schema(manifest_schema)
    errors = list(Draft202012Validator(
        manifest_schema, format_checker=FormatChecker()).iter_errors(manifest))
    if errors:
        raise RuntimeError("manifest schema invalid: " + errors[0].message)
    manifest_path = roots["evidence_raw"] / "producer-manifest.json"
    manifest_path.write_bytes(canonical(manifest))
    for root_id in ("evidence_raw", "build_host", "build_red",
                    "source_upstream_snapshot", "source_xbuild_integrated",
                    "build_xbuild"):
        freeze(roots[root_id])
    print(json.dumps({"manifest": str(manifest_path),
                      "manifest_sha256": sha_file(manifest_path),
                      "run_id": manifest["run_id"]},
                     sort_keys=True, separators=(",", ":")))
    return 0


def internal_prepare(args: argparse.Namespace) -> int:
    upstream, combined = prepare_sources(
        args.repo.resolve(strict=True), args.archive.resolve(strict=True),
        args.snapshot.resolve(), args.integrated.resolve(),
        args.upstream_manifest.resolve(), args.integrated_manifest.resolve(),
        args.run_id)
    print(json.dumps({"upstream_file_count": upstream["file_count"],
                      "upstream_tree_digest": upstream["tree_digest"],
                      "integrated_file_count": combined["file_count"],
                      "integrated_tree_digest": combined["tree_digest"]},
                     sort_keys=True, separators=(",", ":")))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="mode", required=True)
    policy = sub.add_parser("policy")
    policy.add_argument("--repo", type=Path, required=True)
    policy.add_argument("--run-root", type=Path, required=True)
    policy.add_argument("--archive", type=Path, required=True)
    policy.add_argument("--deps-prefix", type=Path, required=True)
    policy.add_argument("--reviewer-root", type=Path)
    policy.add_argument("--review-session-id")
    policy.add_argument("--session-root", type=Path)
    produce_parser = sub.add_parser("produce")
    produce_parser.add_argument("--policy", type=Path, required=True)
    produce_parser.add_argument("--expected-policy-sha256", required=True)
    internal = sub.add_parser("internal-prepare")
    internal.add_argument("--repo", type=Path, required=True)
    internal.add_argument("--archive", type=Path, required=True)
    internal.add_argument("--snapshot", type=Path, required=True)
    internal.add_argument("--integrated", type=Path, required=True)
    internal.add_argument("--upstream-manifest", type=Path, required=True)
    internal.add_argument("--integrated-manifest", type=Path, required=True)
    internal.add_argument("--run-id", required=True)
    tests = sub.add_parser("internal-unittest")
    tests.add_argument("--repo", type=Path, required=True)
    return result


def main() -> int:
    print("DIRECT_ENTRY_FORBIDDEN: use scripts/run_verifier_python.sh", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
