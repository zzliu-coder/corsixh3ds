#!/usr/bin/env python3
"""Fail-closed C3 evidence consumer and write-once seal verifier."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import stat
import struct
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator, FormatChecker

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID32 = re.compile(r"^[0-9a-f]{32}$")
BASE_COMMIT = "9bf6f5e64bccb2366f80d17cc426060e26664ce5"
BASE_TREE = "b62f968430e266dc0b5b53df44cfb029d999d332"
BASE_PARENT = "e486e5f05f25492ea4d7b109d5c74b078e855476"
BASE_FP = "2dddab9ff327dc7e3804f0a912cb54ac1648b13b625138141c02b3a332176ec0"
PRODUCT_FP = "5134c31548fcf786ddc13308f3c18489e6f09470e59c6c152e701f99076bf82f"
FORBIDDEN_KEYS = {
    "assertions", "status", "gate_status", "product_status",
    "review_decision", "candidate_is_expected",
    "transaction_generation_residue", "stable_state_published",
}
FINAL_AUTHORITY_KEYS = {
    "protocol_gates", "review_verdict", "product_verdicts", "failure_codes",
}
FINAL_AUTHORITY_VALUES = {
    "ACCEPT_C3_EVIDENCE_PROTOCOL", "REJECT_C3_EVIDENCE_PROTOCOL",
}
SANITIZER_MARKERS = (
    b"ERROR: AddressSanitizer", b"SUMMARY: AddressSanitizer",
    b"UndefinedBehaviorSanitizer", b"runtime error:",
)
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
FACT_PROTOCOL_GATES = [
    value for value in REQUIRED_PROTOCOL_GATES
    if value not in {"SEALED_INPUT_CLOSURE", "ADVERSARIAL_60_OF_60"}
]
REQUIRED_PRODUCT_BASELINE = {
    "RH09_PRODUCT": "FAIL", "RH07_PRODUCT": "FAIL",
    "UPSTREAM_GIT_PROVENANCE": "NOT_PROVEN",
    "REAL_DEVICE_RUNTIME": "NOT_PROVEN",
    "S70_REAL_DEVICE_MEMORY": "NOT_PROVEN",
}
REQUIRED_FAILURE_CODES = [
    "H1_LEVEL_NOT_DECLARED_ACCEPTED",
    "H2_ESCAPED_CAPABILITY_PUBLISHED_STABLE",
]
CLOSURE_SEAL_IDS = {
    "consumer": "ci-consumer", "policy": "policy",
    "producer": "ci-producer", "review-policy-schema": "ci-review-policy-schema",
    "evidence-manifest-schema": "ci-evidence-manifest-schema",
    "observation-schema": "ci-observation-schema",
    "result-schema": "ci-result-schema", "red-oracle": "ci-red-oracle",
    "adversarial-matrix-runner": "ci-adversarial-matrix-runner",
    "fixture-generator": "ci-fixture-generator",
}


class EvidenceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def fail(code: str, message: str) -> None:
    raise EvidenceError(code, message)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes, default_code: str = "JSON_INVALID") -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                fail("JSON_DUPLICATE_KEY", f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def constant(value: str) -> None:
        fail("JSON_NONFINITE_NUMBER", f"non-finite JSON token: {value}")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except EvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(default_code, f"invalid JSON: {error}")
    def finite(node: Any) -> None:
        if isinstance(node, float) and not math.isfinite(node):
            fail("JSON_NONFINITE_NUMBER", "non-finite parsed float")
        if isinstance(node, dict):
            for child in node.values():
                finite(child)
        elif isinstance(node, list):
            for child in node:
                finite(child)
    finite(value)
    return value


def validate_schema(instance: Any, schema: Any, code: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        fail("SCHEMA_INVALID", str(error))
    errors = sorted(Draft202012Validator(
        schema, format_checker=FormatChecker()).iter_errors(instance),
        key=lambda item: [str(value) for value in item.absolute_path])
    if errors:
        error = errors[0]
        descendants = [error]
        for item in descendants:
            descendants.extend(item.context)
        if any(item.validator == "required" for item in descendants):
            specific = "SCHEMA_REQUIRED_FIELD_MISSING"
        elif list(error.absolute_path) == ["candidate_identity", "expected_commit"]:
            specific = "MALFORMED_CANDIDATE_IDENTITY"
        elif list(error.absolute_path) == ["product_boundary",
                                           "expected_product_fingerprint"]:
            specific = "PRODUCT_FINGERPRINT_MISMATCH"
        elif error.validator in {"additionalProperties", "unevaluatedProperties"}:
            specific = "NESTED_UNKNOWN_FIELD"
        else:
            specific = code
        location = "/".join(str(value) for value in error.absolute_path)
        fail(specific, f"schema at {location}: {error.message}")


def validate_definition(instance: Any, schema: dict[str, Any], name: str,
                        code: str) -> None:
    validate_schema(instance, {"$schema": schema["$schema"],
                               "$defs": schema["$defs"],
                               "$ref": f"#/$defs/{name}"}, code)


def reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        overlap = set(value) & FORBIDDEN_KEYS
        if overlap:
            if "transaction_generation_residue" in overlap:
                fail("H2_DERIVED_OR_MISLABELED_FIELD_FORBIDDEN",
                     "H2 contains generation-specific derived field")
            fail("PRODUCER_VERDICT_FORBIDDEN",
                 f"producer verdict fields forbidden: {sorted(overlap)}")
        for child in value.values():
            reject_forbidden_keys(child)
    elif isinstance(value, list):
        for child in value:
            reject_forbidden_keys(child)


def reject_final_authority(value: Any) -> None:
    if isinstance(value, dict):
        overlap = FINAL_AUTHORITY_KEYS.intersection(value)
        if overlap:
            fail("PRODUCER_VERDICT_FORBIDDEN",
                 f"final authority fields forbidden: {sorted(overlap)}")
        for child in value.values():
            reject_final_authority(child)
    elif isinstance(value, list):
        for child in value:
            reject_final_authority(child)
    elif isinstance(value, str) and value in FINAL_AUTHORITY_VALUES:
        fail("PRODUCER_VERDICT_FORBIDDEN", "final authority value forbidden")


def clean_relative(raw: str) -> list[str]:
    if not raw or raw.startswith("/") or "\\" in raw or "\0" in raw or \
       unicodedata.normalize("NFC", raw) != raw:
        fail("SAFE_PATH_INVALID", f"invalid relative path: {raw!r}")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        fail("SAFE_PATH_INVALID", f"invalid relative component: {raw!r}")
    return parts


def stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)


def secure_read(root: Path, relative: str, maximum: int,
                rename_hook: Callable[[Path], None] | None = None,
                require_single_link: bool = True) -> bytes:
    parts = clean_relative(relative)
    root_real = root.resolve(strict=True)
    if root_real != root:
        fail("SYMLINK_ESCAPE", f"root is not literal realpath: {root}")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(root_real, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    current = directory
    opened = []
    try:
        for part in parts[:-1]:
            try:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY |
                             os.O_CLOEXEC | nofollow, dir_fd=current)
            except OSError as error:
                fail("SYMLINK_COMPONENT", f"cannot open directory component: {error}")
            opened.append(fd)
            current = fd
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_CLOEXEC | nofollow,
                         dir_fd=current)
        except OSError as error:
            fail("SYMLINK_ESCAPE", f"cannot safely open file: {error}")
        opened.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or \
           (require_single_link and before.st_nlink != 1):
            fail("SAFE_NODE_INVALID", "artifact is not a single-link regular file")
        if before.st_size > maximum:
            fail("ARTIFACT_TOO_LARGE", "artifact exceeds policy limit")
        chunks = []
        total = 0
        while True:
            block = os.read(fd, min(1024 * 1024, maximum + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > maximum:
                fail("ARTIFACT_TOO_LARGE", "artifact exceeds policy limit")
        after = os.fstat(fd)
        if stat_identity(before) != stat_identity(after):
            fail("TOCTOU_FILE_CHANGED", "artifact changed during read")
        if rename_hook is not None:
            rename_hook(root / relative)
        try:
            reopened = os.open(parts[-1], os.O_RDONLY | os.O_CLOEXEC | nofollow,
                               dir_fd=current)
        except OSError as error:
            fail("PATH_IDENTITY_CHANGED", f"artifact pathname changed: {error}")
        try:
            again = os.fstat(reopened)
            if (again.st_dev, again.st_ino) != (before.st_dev, before.st_ino):
                fail("PATH_IDENTITY_CHANGED", "artifact pathname inode changed")
        finally:
            os.close(reopened)
        return b"".join(chunks)
    finally:
        for fd in reversed(opened):
            os.close(fd)
        os.close(directory)


def bootstrap_read(path: Path, maximum: int = 268435456,
                   require_single_link: bool = True) -> bytes:
    if not path.is_absolute() or path.is_symlink():
        fail("SAFE_PATH_INVALID", "bootstrap path must be absolute non-symlink")
    resolved = path.resolve(strict=True)
    return secure_read(resolved.parent, resolved.name, maximum,
                       require_single_link=require_single_link)


def run_git(git_path: str, repo: Path, *args: str,
            allow: tuple[int, ...] = (0,)) -> tuple[int, bytes, bytes]:
    env = {
        "PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
    }
    result = subprocess.run([git_path, *args], cwd=repo, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False,
                            env=env)
    if result.returncode not in allow:
        fail("GIT_COMMAND_FAILED", result.stderr.decode(errors="replace"))
    return result.returncode, result.stdout, result.stderr


def parse_raw_commit(payload: bytes, expected_oid: str) -> dict[str, Any]:
    """Parse one raw commit object without consulting revision traversal."""
    if not HEX40.fullmatch(expected_oid):
        fail("ANCESTRY_OBJECT_UNREADABLE", f"malformed commit id: {expected_oid}")
    actual_oid = hashlib.sha1(
        b"commit " + str(len(payload)).encode("ascii") + b"\0" + payload
    ).hexdigest()
    if actual_oid != expected_oid:
        fail("ANCESTRY_OBJECT_UNREADABLE",
             f"commit object id mismatch: expected={expected_oid} actual={actual_oid}")
    separator = payload.find(b"\n\n")
    if separator < 0:
        fail("ANCESTRY_OBJECT_UNREADABLE", f"commit header terminator missing: {expected_oid}")
    tree_rows: list[str] = []
    parents: list[str] = []
    for line in payload[:separator].split(b"\n"):
        if line.startswith(b" "):
            continue
        if line.startswith(b"tree "):
            value = line[5:].decode("ascii", errors="strict")
            tree_rows.append(value)
        elif line.startswith(b"parent "):
            value = line[7:].decode("ascii", errors="strict")
            if not HEX40.fullmatch(value):
                fail("ANCESTRY_OBJECT_UNREADABLE",
                     f"malformed parent in {expected_oid}: {value!r}")
            parents.append(value)
    if len(tree_rows) != 1 or not HEX40.fullmatch(tree_rows[0]):
        fail("ANCESTRY_OBJECT_UNREADABLE",
             f"commit must contain one valid tree: {expected_oid}")
    return {"oid": expected_oid, "tree": tree_rows[0], "parents": parents,
            "raw_sha256": sha_bytes(payload)}


def git_pollution_preflight(git_path: str, repo: Path) -> dict[str, Any]:
    object_format = run_git(git_path, repo, "rev-parse", "--show-object-format")[1].decode().strip()
    if object_format != "sha1":
        fail("GIT_OBJECT_FORMAT_UNSUPPORTED", f"object format: {object_format}")
    shallow = run_git(git_path, repo, "rev-parse", "--is-shallow-repository")[1].decode().strip()
    if shallow != "false":
        fail("GIT_SHALLOW_REPOSITORY", f"shallow repository: {shallow}")
    replace = run_git(git_path, repo, "for-each-ref", "--format=%(refname)",
                      "refs/replace")[1].decode().splitlines()
    if replace:
        fail("GIT_REPLACE_REFS_PRESENT", f"replace refs: {replace}")
    git_dir = Path(run_git(git_path, repo, "rev-parse", "--absolute-git-dir")[1]
                   .decode().strip()).resolve(strict=True)
    common_dir_raw = run_git(git_path, repo, "rev-parse", "--git-common-dir")[1].decode().strip()
    common_dir = (repo / common_dir_raw).resolve(strict=True) if not common_dir_raw.startswith("/") \
        else Path(common_dir_raw).resolve(strict=True)
    graft = common_dir / "info/grafts"
    if graft.exists() and graft.stat().st_size:
        fail("GIT_GRAFTS_PRESENT", f"legacy graft file: {graft}")
    object_dir = common_dir / "objects"
    alternate = object_dir / "info/alternates"
    if alternate.exists() and alternate.stat().st_size:
        fail("GIT_ALTERNATES_PRESENT", f"alternate object database: {alternate}")
    for name in ("GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                 "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE"):
        if os.environ.get(name):
            fail("GIT_OBJECT_DIRECTORY_EXTERNAL", f"forbidden Git environment: {name}")
    if common_dir not in [git_dir, *git_dir.parents] and git_dir not in common_dir.parents:
        # Linked worktrees are accepted only as construction inputs. The full
        # authority path normalizes them to a standalone repository first.
        pass
    return {"object_format": object_format, "shallow": False,
            "replace_ref_count": 0, "graft_bytes": 0, "alternate_bytes": 0,
            "git_dir": str(git_dir), "common_dir": str(common_dir),
            "object_dir": str(object_dir.resolve(strict=True))}


def raw_ancestry_commitment(git_path: str, repo: Path, head: str,
                            forbidden: list[str]) -> dict[str, Any]:
    pollution = git_pollution_preflight(git_path, repo)
    pending = [head]
    visiting: set[str] = set()
    rows: dict[str, dict[str, Any]] = {}
    while pending:
        oid = pending.pop()
        if oid in rows:
            continue
        if oid in visiting:
            fail("GIT_TOPOLOGY", f"ancestry cycle: {oid}")
        visiting.add(oid)
        code, kind, _ = run_git(git_path, repo, "--no-replace-objects",
                                "cat-file", "-t", oid, allow=(0, 128))
        if code != 0 or kind.strip() != b"commit":
            fail("ANCESTRY_OBJECT_UNREADABLE",
                 f"commit object unavailable: oid={oid} git_exit={code}")
        code, payload, _ = run_git(git_path, repo, "--no-replace-objects",
                                   "cat-file", "commit", oid, allow=(0, 128))
        if code != 0:
            fail("ANCESTRY_OBJECT_UNREADABLE",
                 f"commit payload unavailable: oid={oid} git_exit={code}")
        row = parse_raw_commit(payload, oid)
        rows[oid] = row
        visiting.remove(oid)
        pending.extend(parent for parent in row["parents"] if parent not in rows)
    commits = [rows[oid] for oid in sorted(rows)]
    roots = sorted(row["oid"] for row in commits if not row["parents"])
    first_parent_chain = []
    current = head
    chain_seen: set[str] = set()
    while current:
        if current in chain_seen or current not in rows:
            fail("GIT_TOPOLOGY", "invalid first-parent chain")
        chain_seen.add(current)
        first_parent_chain.append(current)
        current = rows[current]["parents"][0] if rows[current]["parents"] else ""
    intersection = sorted(set(rows).intersection(forbidden))
    body = {"algorithm": "raw-full-parent-closure-v1",
            "object_format": pollution["object_format"], "head": head,
            "head_tree": rows[head]["tree"],
            "head_parents": rows[head]["parents"],
            "first_parent_chain": first_parent_chain, "roots": roots,
            "commit_count": len(commits),
            "edge_count": sum(len(row["parents"]) for row in commits),
            "commits": commits, "forbidden_intersection": intersection}
    body["closure_sha256"] = sha_bytes(canonical(body))
    if intersection:
        fail("GIT_TOPOLOGY", f"forbidden reachable commits: {intersection}")
    return body


def parse_unittest_counts(text: str) -> dict[str, int]:
    runs = re.findall(r"Ran (\d+) tests?", text)
    if len(runs) != 1:
        fail("HOST_REGRESSION_COUNT_MISMATCH", "one unittest executed count required")
    summaries = re.findall(r"^FAILED \(([^)]*)\)$|^OK(?: \(([^)]*)\))?$",
                           text, flags=re.MULTILINE)
    if len(summaries) != 1:
        fail("HOST_REGRESSION_COUNT_MISMATCH", "one unittest summary required")
    fields = next((value for value in summaries[0] if value), "")
    counts = {"executed": int(runs[0]), "failures": 0, "errors": 0, "skipped": 0}
    for name, value in re.findall(r"(failures|errors|skipped)=(\d+)", fields):
        counts[name] = int(value)
    counts["passed"] = counts["executed"] - counts["failures"] - \
        counts["errors"] - counts["skipped"]
    if counts["passed"] < 0:
        fail("HOST_REGRESSION_COUNT_MISMATCH", "unittest counts are inconsistent")
    return counts


def parse_unittest_skip_reasons(text: str) -> list[str]:
    """Return every verbose unittest skip reason in transcript order."""
    return re.findall(r"^(?:.* \.\.\. )?skipped ['\"](.*)['\"]$", text,
                      flags=re.MULTILINE)


def fingerprint(git_path: str, repo: Path, revision: str,
                exact: set[str] | None = None,
                prefixes: tuple[str, ...] = ()) -> tuple[str, int, list[tuple[str, bytes]]]:
    _, listing, _ = run_git(git_path, repo, "ls-tree", "-r", "-z",
                            "--full-tree", revision)
    digest = hashlib.sha256()
    count = 0
    blobs = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, path_raw = record.split(b"\t", 1)
        mode, kind, oid = metadata.split(b" ", 2)
        path = os.fsdecode(path_raw)
        if exact is not None and path not in exact and not path.startswith(prefixes):
            continue
        if kind == b"commit":
            fail("GIT_SUBMODULE_FORBIDDEN", f"submodule: {path}")
        _, payload, _ = run_git(git_path, repo, "cat-file", "-p", oid.decode())
        for value in (mode, kind, path_raw, sha_bytes(payload).encode()):
            digest.update(value)
            digest.update(b"\0")
        blobs.append((path, payload))
        count += 1
    return digest.hexdigest(), count, blobs


def source_tree(root: Path, maximum_files: int,
                maximum_bytes: int) -> dict[str, Any]:
    files = []
    root = root.resolve(strict=True)
    for path in sorted(root.rglob("*"),
                       key=lambda item: item.relative_to(root).as_posix().encode()):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            fail("SOURCE_TREE_NODE_INVALID", f"source symlink: {relative}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail("SOURCE_TREE_NODE_INVALID", f"source node: {relative}")
        data = secure_read(root, relative, maximum_bytes)
        files.append({"mode": "100755" if info.st_mode & 0o111 else "100644",
                      "path": relative, "bytes": len(data),
                      "sha256": sha_bytes(data)})
        if len(files) > maximum_files:
            fail("SOURCE_TREE_EXPANDED", "source file limit exceeded")
    digest = hashlib.sha256()
    for item in files:
        for value in (item["mode"], item["path"], str(item["bytes"]),
                      item["sha256"]):
            digest.update(value.encode())
            digest.update(b"\0")
    return {"files": files, "file_count": len(files),
            "tree_digest": digest.hexdigest()}


def parse_time(value: str) -> dt.datetime:
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("TIME_FORMAT_INVALID", f"invalid time: {value}")
    if result.tzinfo is None:
        fail("TIME_FORMAT_INVALID", f"time has no timezone: {value}")
    return result


def exact_role_map(rows: list[dict[str, Any]], expected: set[str],
                   kind: str) -> dict[str, dict[str, Any]]:
    roles = [item.get("role") for item in rows]
    if len(roles) != len(set(roles)):
        fail(f"DUPLICATE_{kind.upper()}_ROLE", f"duplicate {kind} role")
    actual = set(roles)
    missing = expected - actual
    extra = actual - expected
    if missing:
        if kind == "artifact" and \
           "xbuild-upstream-source-tree-manifest" in missing:
            fail("UPSTREAM_TREE_MANIFEST_MISSING", "upstream tree manifest absent")
        if kind == "artifact" and \
           "fixture-tracked-fixture-manifest" in missing:
            fail("RH10_TRACKED_OUTER_MANIFEST_MISSING",
                 "tracked outer fixture manifest absent")
        fail(f"MISSING_{kind.upper()}_ROLE", f"missing {kind}: {sorted(missing)}")
    if extra:
        if kind == "build":
            fail("EXTRA_ROOT_OR_BUILD", f"extra build: {sorted(extra)}")
        if kind == "artifact":
            fail("EXTRA_ORPHAN_ARTIFACT", f"extra artifact: {sorted(extra)}")
        fail(f"EXTRA_{kind.upper()}_ROLE", f"extra {kind}: {sorted(extra)}")
    return {item["role"]: item for item in rows}


def extract_embedded_manifest(data: bytes) -> dict[str, Any]:
    start = data.find(b'{"budgets"')
    if start < 0:
        fail("RH10_CONTAINER_MANIFEST_MISSING", "embedded TH3DSR1 manifest absent")
    depth = 0
    quoted = False
    escaped = False
    end = None
    for index in range(start, len(data)):
        value = data[index]
        if quoted:
            if escaped:
                escaped = False
            elif value == 0x5C:
                escaped = True
            elif value == 0x22:
                quoted = False
        else:
            if value == 0x22:
                quoted = True
            elif value == 0x7B:
                depth += 1
            elif value == 0x7D:
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
    if end is None:
        fail("RH10_CONTAINER_MANIFEST_INVALID", "embedded JSON is incomplete")
    value = strict_json(data[start:end])
    if not isinstance(value, dict):
        fail("RH10_CONTAINER_MANIFEST_INVALID", "embedded manifest is not object")
    return value


def validate_observations(h1: dict[str, Any], h2: dict[str, Any],
                          run_id: str, observation_schema: Any,
                          stable_states: list[str]) -> tuple[dict[str, Any],
                                                             dict[str, Any],
                                                             bool, bool]:
    for item, gate in ((h1, "RH09-H1"), (h2, "RH07-H2")):
        validate_schema(item, observation_schema, "OBSERVATION_SCHEMA_INVALID")
        if item["run_id"] != run_id or item["gate_id"] != gate:
            fail("OBSERVATION_REPLAY", f"observation binding mismatch: {gate}")
    a = h1["observations"]
    zero_pairs = [
        ("mount_generation",), ("catalog_generation",), ("entries",),
        ("leases",), ("pins",), ("dependencies",), ("allocation_records",),
        ("regular_reconciliation",), ("linear_reconciliation",),
    ]
    h1_ok = (
        a["requested_level"] == "hospital-01" and
        a["declared_level_count"] == 0 and a["call_result"] == "OK" and
        a["state_before"] == "MENU_STABLE" and
        a["state_after"] == "LEVEL_STABLE" and
        a["transition_active_after"] is False and
        a["mounted_package_ids_before"] == a["mounted_package_ids_after"] and
        a["catalog_fingerprint_before"] == a["catalog_fingerprint_after"] and
        a["pool_bytes_before"] == a["pool_bytes_after"] and
        a["backend_bytes_before"] == a["backend_bytes_after"] and
        all(a[name[0] + "_before"] == a[name[0] + "_after"] for name in zero_pairs)
    )
    b = h2["observations"]
    delta = lambda name: b[name + "_after"] - b[name + "_before"]
    pool = [after - before for before, after in
            zip(b["pool_bytes_before"], b["pool_bytes_after"])]
    backend = [after - before for before, after in
               zip(b["backend_bytes_before"], b["backend_bytes_after"])]
    stable = b["state_after"] in stable_states and \
        b["transition_active_after"] is False
    h2_ok = (
        b["fault_point"] == "after-first-staged-acquire" and
        b["call_result"] == "E_TEST_PREPARE_ABORT" and
        b["state_before"] == "MENU_STABLE" and
        b["state_after"] == "MENU_STABLE" and
        b["transition_active_before"] is False and
        b["transition_active_after"] is False and stable and
        b["escaped_lease_valid_after"] is True and
        delta("mounted_package_count") == 0 and delta("entries") == 1 and
        delta("leases") == 1 and delta("pins") == 0 and
        delta("dependencies") == 0 and delta("allocation_records") == 1 and
        pool == [0, 0, 64, 0, 0, 0, 0] and backend == [64, 0] and
        delta("linear_reconciliation") == 0
    )
    return ({"all_deltas_zero": True, "stable_state_published": True},
            {"allocation_record_residue_delta": 1,
             "pool_byte_deltas": pool, "backend_byte_deltas": backend,
             "stable_state_published": stable}, h1_ok, h2_ok)


def mkdir_at(parent: int, name: str) -> int:
    try:
        os.mkdir(name, 0o755, dir_fd=parent)
    except FileExistsError:
        pass
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC |
                   getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)


def seal_bytes(seal_root: Path, seal_id: str, basename: str,
               data: bytes) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", seal_id):
        fail("SEAL_ID_INVALID", f"bad seal id: {seal_id}")
    if "/" in basename or basename in {"", ".", ".."}:
        fail("SEAL_PATH_INVALID", f"bad basename: {basename}")
    root_fd = os.open(seal_root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        sealed_fd = mkdir_at(root_fd, "sealed")
        try:
            item_fd = mkdir_at(sealed_fd, seal_id)
            try:
                try:
                    target = os.open(basename, os.O_WRONLY | os.O_CREAT |
                                     os.O_EXCL | os.O_CLOEXEC |
                                     getattr(os, "O_NOFOLLOW", 0), 0o444,
                                     dir_fd=item_fd)
                except FileExistsError:
                    fail("SEAL_WRITE_ONCE_VIOLATION", f"sealed file exists: {seal_id}")
                try:
                    offset = 0
                    while offset < len(data):
                        offset += os.write(target, data[offset:])
                    os.fsync(target)
                finally:
                    os.close(target)
                os.fsync(item_fd)
            finally:
                os.close(item_fd)
        finally:
            os.close(sealed_fd)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    relative = f"sealed/{seal_id}/{basename}"
    if sha_bytes((seal_root / relative).read_bytes()) != sha_bytes(data):
        fail("SEAL_COPY_MISMATCH", f"sealed hash mismatch: {relative}")
    return relative


def write_once(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC |
                 getattr(os, "O_NOFOLLOW", 0), 0o444)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)


def verify_checksums(seal: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    sums_path = seal / "SHA256SUMS"
    raw = bootstrap_read(sums_path, 16 * 1024 * 1024)
    rows = raw.decode("utf-8").splitlines()
    seen = set()
    for row in rows:
        if not re.fullmatch(r"[0-9a-f]{64}  [^\x00]+", row):
            fail("FINAL_CHECKSUM_FORMAT", f"bad checksum row: {row!r}")
        digest, relative = row.split("  ", 1)
        clean_relative(relative)
        if relative == "SHA256SUMS" or relative in seen:
            fail("FINAL_CHECKSUM_FORMAT", f"duplicate/self checksum: {relative}")
        seen.add(relative)
        path = seal / relative
        if not path.is_file() or sha_bytes(secure_read(seal, relative, 268435456)) != digest:
            fail("FINAL_CHECKSUM_MISMATCH", f"checksum mismatch: {relative}")
    if rows != sorted(rows, key=lambda row: row.split("  ", 1)[1]):
        fail("FINAL_CHECKSUM_FORMAT", "checksum rows are not sorted")
    required = {"run-manifest.json", "result.json"}
    if not required.issubset(seen):
        fail("SEALED_INPUT_CLOSURE", "final outputs not checksummed")
    manifest = strict_json(secure_read(seal, "run-manifest.json", 268435456))
    result = strict_json(secure_read(seal, "result.json", 268435456))
    if result.get("run_manifest_sha256") != sha_bytes(
            secure_read(seal, "run-manifest.json", 268435456)):
        fail("FINAL_CHECKSUM_MISMATCH", "result/run-manifest binding mismatch")
    entries = {item["seal_id"] for item in manifest.get("inputs", [])}
    for role, seal_id in CLOSURE_SEAL_IDS.items():
        if seal_id not in entries:
            code = {
                "consumer": "CONSUMER_NOT_SEALED", "policy": "POLICY_NOT_SEALED",
                "red-oracle": "ORACLE_NOT_SEALED",
            }.get(role, "SCHEMA_NOT_SEALED")
            fail(code, f"closure input absent from run manifest: {role}")
    return manifest, result


def consume(args: argparse.Namespace) -> int:
    policy_path = args.policy.resolve(strict=True)
    policy_raw = bootstrap_read(policy_path)
    if sha_bytes(policy_raw) != args.expected_policy_sha256:
        fail("POLICY_HASH_MISMATCH", "policy bytes differ from reviewer hash")
    policy = strict_json(policy_raw)
    if not isinstance(policy, dict):
        fail("POLICY_SCHEMA", "policy is not object")
    roots_rows = policy.get("roots", [])
    if len(roots_rows) != 9:
        fail("EXTRA_ROOT_OR_BUILD", "policy root cardinality changed")
    roots = {item["root_id"]: Path(item["absolute_realpath"]) for item in roots_rows}
    if len(roots) != 9:
        fail("EXTRA_ROOT_OR_BUILD", "duplicate policy root")
    candidate = args.candidate_root.resolve(strict=True)
    evidence = args.evidence_root.resolve(strict=True)
    seal = args.seal_root.resolve(strict=True)
    if roots.get("candidate") != candidate or roots.get("evidence_raw") != evidence or \
       roots.get("seal") != seal:
        fail("ROOT_IDENTITY_MISMATCH", "CLI roots differ from reviewer policy")
    if any(seal.iterdir()):
        fail("SEAL_NOT_EMPTY", "seal root must be empty")

    policy_schema_raw = secure_read(candidate,
        "tests/runtime_core_v2/review-policy.schema.json",
        policy["limits"]["max_artifact_bytes"])
    policy_schema = strict_json(policy_schema_raw)
    validate_schema(policy, policy_schema, "POLICY_SCHEMA")
    registry = policy["role_registry"]
    expected = {}
    for item in registry:
        key = (item["kind"], item["role"])
        if key in expected:
            fail("POLICY_ROLE_DUPLICATE", f"duplicate registry role: {key}")
        expected[key] = item
        if item["count"] != 1:
            fail("POLICY_CARDINALITY_INVALID", f"role count not one: {key}")

    closure_data = {}
    for item in policy["closure_inputs"]:
        data = secure_read(candidate, item["relative_path"],
                           policy["limits"]["max_artifact_bytes"])
        if len(data) != item["bytes"] or sha_bytes(data) != item["sha256"]:
            code = {
                "consumer": "CONSUMER_HASH_MISMATCH",
                "red-oracle": "ORACLE_HASH_MISMATCH",
            }.get(item["role"], "SCHEMA_HASH_MISMATCH")
            if item["role"] in {"producer", "adversarial-matrix-runner",
                                "fixture-generator"}:
                code = "CLOSURE_INPUT_HASH_MISMATCH"
            fail(code, f"closure input changed: {item['role']}")
        closure_data[item["role"]] = (item, data)
    if set(closure_data) != {
        "consumer", "producer", "review-policy-schema",
        "evidence-manifest-schema", "observation-schema", "result-schema",
        "red-oracle", "adversarial-matrix-runner", "fixture-generator",
    }:
        fail("SEALED_INPUT_CLOSURE", "closure input role set mismatch")
    if sha_bytes(bootstrap_read(Path(__file__).resolve())) != \
       policy["closure_inputs"][0]["sha256"] and \
       closure_data["consumer"][1] != bootstrap_read(Path(__file__).resolve()):
        fail("CONSUMER_HASH_MISMATCH", "executing consumer differs from policy")

    tool_policy = {item["role"]: item for item in registry if item["kind"] == "tool"}
    manifest_path = evidence / "producer-manifest.json"
    manifest_raw = bootstrap_read(manifest_path)
    manifest = strict_json(manifest_raw)
    reject_forbidden_keys(manifest)
    for kind, key in (("build", "builds"), ("tool", "tools"),
                      ("artifact", "artifacts"), ("fixture", "fixtures"),
                      ("invocation", "invocations")):
        rows = manifest.get(key)
        if not isinstance(rows, list):
            fail("SCHEMA_REQUIRED_FIELD_MISSING", f"missing {key}")
        expected_roles = {role for k, role in expected if k == kind}
        exact_role_map(rows, expected_roles, kind)
    manifest_schema = strict_json(closure_data["evidence-manifest-schema"][1])
    validate_schema(manifest, manifest_schema, "EVIDENCE_SCHEMA")
    if manifest["policy_id"] != policy["policy_id"] or \
       manifest["policy_sha256"] != args.expected_policy_sha256:
        fail("POLICY_BINDING_MISMATCH", "manifest/policy binding mismatch")
    run_id = manifest["run_id"]
    if run_id != policy["policy_id"][3:] or not ID32.fullmatch(run_id):
        fail("RUN_ID_MISMATCH", "manifest run id differs from policy")

    tools = exact_role_map(manifest["tools"],
        {role for kind, role in expected if kind == "tool"}, "tool")
    git_path = tools["git"]["absolute_realpath"]
    head = run_git(git_path, candidate, "rev-parse", "HEAD^{commit}")[1].decode().strip()
    identity = policy["candidate_identity"]
    if not HEX40.fullmatch(identity.get("expected_commit", "")) or \
       not HEX40.fullmatch(identity.get("expected_tree", "")):
        fail("MALFORMED_CANDIDATE_IDENTITY", "candidate identity malformed")
    ancestry = raw_ancestry_commitment(
        git_path, candidate, head, identity["forbidden_ancestors"])
    tree = ancestry["head_tree"]
    parents = ancestry["head_parents"]
    if head != identity["expected_commit"] or tree != identity["expected_tree"]:
        fail("CANDIDATE_IDENTITY_MISMATCH", "candidate commit/tree mismatch")
    if parents != [BASE_COMMIT]:
        fail("GIT_TOPOLOGY", "candidate is not the required single-parent commit")
    if ancestry != identity.get("ancestry"):
        fail("ANCESTRY_COMMITMENT_MISMATCH",
             "live raw full-parent closure differs from reviewer policy")
    status = run_git(git_path, candidate, "status", "--porcelain=v1",
                     "--untracked-files=all")[1]
    if status:
        fail("CANDIDATE_DIRTY", "candidate worktree is dirty")
    tracked_fp, tracked_count, tracked_blobs = fingerprint(
        git_path, candidate, head)
    if tracked_fp != identity["expected_candidate_fingerprint"] or \
       tracked_count != identity["expected_candidate_entries"]:
        fail("CANDIDATE_FINGERPRINT_MISMATCH", "candidate tracked fingerprint mismatch")
    live_identity = {
        "commit": head, "tree": tree, "first_parent": BASE_COMMIT,
        "tracked_fingerprint_v3": tracked_fp,
        "tracked_entries": tracked_count,
    }
    if manifest.get("candidate_identity") != live_identity:
        fail("MANIFEST_CANDIDATE_BINDING_MISMATCH",
             "producer manifest candidate differs from live Git identity")
    product = policy["product_boundary"]
    product_fp, product_count, _ = fingerprint(
        git_path, candidate, head, set(product["product_exact"]),
        tuple(product["product_prefixes"]))
    if product_fp != product["expected_product_fingerprint"] or \
       product_count != product["expected_product_entries"]:
        fail("PRODUCT_FINGERPRINT_MISMATCH", "product fingerprint mismatch")
    diff = run_git(git_path, candidate, "diff", "--name-only",
                   BASE_COMMIT, head)[1].decode().splitlines()
    if any(path not in set(product["allowlist_exact"]) for path in diff):
        fail("DIFF_OUTSIDE_ALLOWLIST", "candidate diff outside exact allowlist")
    if any(path in set(product["product_exact"]) or
           path.startswith(tuple(product["product_prefixes"])) for path in diff):
        fail("PRODUCT_DIFF_NONZERO", "product path changed")

    artifact_roles = {role for kind, role in expected if kind == "artifact"}
    artifacts = exact_role_map(manifest["artifacts"], artifact_roles, "artifact")
    artifact_data = {}
    rename_done = False
    for role in sorted(artifacts):
        item = artifacts[role]
        if item["root_id"] not in roots:
            fail("ROOT_IDENTITY_MISMATCH", f"unknown artifact root: {role}")
        hook = None
        if args.test_rename_artifact == role and not rename_done:
            def do_rename(path: Path) -> None:
                backup = path.with_name(path.name + ".c3-old")
                os.rename(path, backup)
                path.write_bytes(backup.read_bytes())
            hook = do_rename
            rename_done = True
        data = secure_read(roots[item["root_id"]], item["relative_path"],
                           policy["limits"]["max_artifact_bytes"], hook)
        if len(data) != item["bytes"] or sha_bytes(data) != item["sha256"]:
            if role == "xbuild-upstream-snapshot-archive":
                fail("UPSTREAM_ARCHIVE_HASH_MISMATCH", "archive identity changed")
            if role == "fixture-fresh-fixture-manifest":
                fail("RH10_FRESH_OUTER_MANIFEST_HASH_MISMATCH",
                     "fresh outer manifest identity changed")
            fail("ARTIFACT_HASH_MISMATCH", f"artifact identity mismatch: {role}")
        artifact_data[role] = data

    for role, item in tools.items():
        path = Path(item["absolute_realpath"])
        if str(path.resolve(strict=True)) != path.as_posix():
            fail("TOOL_PATH_MISMATCH", f"tool not literal realpath: {role}")
        data = bootstrap_read(path, require_single_link=False)
        if len(data) != item["bytes_before"] or len(data) != item["bytes_after"] or \
           sha_bytes(data) != item["sha256_before"] or \
           sha_bytes(data) != item["sha256_after"]:
            fail("TOOL_HASH_MISMATCH", f"tool changed: {role}")
        direct_paths = [command["argv"][0] for command in policy["commands"]
            if command["executable_kind"] == "tool" and
            command["executable_role"] == role]
        if direct_paths and any(value != path.as_posix()
                                for value in direct_paths):
            fail("TOOL_PATH_MISMATCH", f"argv[0] differs for tool: {role}")

    producer_path = candidate / "scripts/verify_runtime_core_v2.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("c3_r5_policy_tools", producer_path)
    if spec is None or spec.loader is None:
        fail("TOOL_IMPLEMENTATION_IDENTITY_MISMATCH", "cannot load sealed tool identity code")
    producer_module = importlib.util.module_from_spec(spec)
    sys.modules["c3_r5_policy_tools"] = producer_module
    spec.loader.exec_module(producer_module)
    live_tool_identity = producer_module.tool_implementation_identity(
        {role: item["absolute_realpath"] for role, item in tools.items()})
    if live_tool_identity != policy["tool_implementation_identity"]:
        fail("TOOL_IMPLEMENTATION_IDENTITY_MISMATCH",
             "actual dispatched tool or developer identity changed")
    xbuild_closures = {}
    for name, expected_closure in policy["xbuild_input_closures"].items():
        observed_closure = producer_module.lstat_closure(
            Path(expected_closure["root_realpath"]))
        if observed_closure != expected_closure:
            fail("XBUILD_INPUT_CLOSURE_MISMATCH",
                 f"cross-build input changed: {name}")
        xbuild_closures[name] = observed_closure["sha256"]

    commands = {item["role"]: item for item in policy["commands"]}
    invocations = exact_role_map(manifest["invocations"],
        {role for kind, role in expected if kind == "invocation"}, "invocation")
    artifact_ids = {item["artifact_id"]: item for item in manifest["artifacts"]}
    claimed_slots = set()
    reverse = set()
    for role, invocation in invocations.items():
        command = commands[role]
        for field in ("gate_id", "executable_kind", "cwd_root_id",
                      "environment_profile_id"):
            if invocation[field] != command[field]:
                code = {"cwd_root_id": "CWD_MISMATCH",
                        "environment_profile_id": "ENVIRONMENT_MISMATCH"}.get(
                            field, "PROCESS_BINDING_MISMATCH")
                fail(code, f"invocation {field} mismatch: {role}")
        expected_executable = (("t-" if command["executable_kind"] == "tool"
                                else "a-") + command["executable_role"])
        if invocation["executable_id"] != expected_executable:
            fail("PROCESS_BINDING_MISMATCH", f"executable mismatch: {role}")
        if invocation["argv"] != command["argv"]:
            fail("ARGV_MISMATCH", f"argv mismatch: {role}")
        if parse_time(invocation["finished_at"]) < parse_time(invocation["started_at"]):
            fail("TIME_ORDER_INVALID", f"negative invocation duration: {role}")
        if invocation["stream_truncated"]:
            fail("STREAM_TRUNCATED", f"invocation stream truncated: {role}")
        if invocation["timed_out"] or invocation["signal"] is not None or \
           invocation["exit_code"] != 0:
            if role in {"RH09-H1", "RH07-H2"} and any(
                    marker in artifact_data[commands[role]["stdout_role"]] +
                    artifact_data[commands[role]["stderr_role"]]
                    for marker in SANITIZER_MARKERS):
                fail("SANITIZER_PRODUCT_FAILURE", "authenticated sanitizer failure")
            fail("TERMINATION_FIELDS_INCONSISTENT",
                 f"invocation termination invalid: {role}")
        stdout_id = "a-" + command["stdout_role"]
        stderr_id = "a-" + command["stderr_role"]
        if invocation["stdout_artifact_id"] != stdout_id:
            if role in {"RH09-H1", "RH07-H2"} and \
               invocation["stdout_artifact_id"] in {
                   "a-rh09-h1-stdout", "a-rh07-h2-stdout"}:
                fail("STREAM_ROLE_SWAP", "H1/H2 stdout roles swapped")
            if role == "ctest":
                fail("CTEST_STREAM_UNPROVEN", "CTest stdout unbound")
            fail("UNBOUND_EXTERNAL_STREAM", f"stdout mismatch: {role}")
        if invocation["stderr_artifact_id"] != stderr_id:
            fail("UNBOUND_EXTERNAL_STREAM", f"stderr mismatch: {role}")
        expected_outputs = ["a-" + value for value in command["output_roles"]]
        if any(value not in artifact_ids for value in
               invocation["output_artifact_ids"]):
            fail("DANGLING_ARTIFACT_REFERENCE", f"dangling output: {role}")
        if invocation["output_artifact_ids"] != expected_outputs:
            if role == "simulator":
                fail("SIMULATOR_OUTPUT_UNPROVEN", "simulator output missing")
            if role == "prepare-xbuild-source":
                fail("UPSTREAM_TREE_MANIFEST_MISSING", "source manifest output missing")
            fail("DANGLING_ARTIFACT_REFERENCE", f"output mismatch: {role}")
        expected_observation = stdout_id if role in {"RH09-H1", "RH07-H2"} else None
        if invocation["observation_artifact_id"] != expected_observation:
            fail("OBSERVATION_STDOUT_MISMATCH", f"observation alias mismatch: {role}")
        for artifact_id in [stdout_id, stderr_id, *expected_outputs]:
            if artifact_id not in artifact_ids:
                if role == "prepare-xbuild-source":
                    fail("UPSTREAM_TREE_MANIFEST_MISSING", "source manifest record missing")
                fail("DANGLING_ARTIFACT_REFERENCE", f"dangling artifact: {artifact_id}")
            reverse.add((artifact_id, invocation["invocation_id"],
                         artifact_ids[artifact_id]["role"]))

    for role, item in artifacts.items():
        owner = item.get("canonical_owner")
        if not isinstance(owner, dict):
            fail("EXTRA_ORPHAN_ARTIFACT", f"artifact owner absent: {role}")
        slot_key = (owner.get("kind"), owner.get("id"), owner.get("slot"))
        if slot_key in claimed_slots:
            fail("DUPLICATE_CANONICAL_OWNER_SLOT", f"owner slot repeated: {slot_key}")
        claimed_slots.add(slot_key)
        required_kind = expected[("artifact", role)]["required_owner_kind"]
        if owner.get("kind") != required_kind:
            fail("STREAM_ROLE_SWAP", f"owner kind mismatch: {role}")
        if required_kind == "invocation":
            expected_owner = next((value for value in invocations.values()
                if ("a-" + role) in [value["stdout_artifact_id"],
                    value["stderr_artifact_id"], *value["output_artifact_ids"]]), None)
            if expected_owner is None or owner != {
                "kind": "invocation", "id": expected_owner["invocation_id"],
                "slot": role}:
                fail("STREAM_ROLE_SWAP", f"owner/reverse mismatch: {role}")
        elif required_kind == "fixture":
            if owner != {"kind": "fixture", "id": "f-no-level-synthetic",
                         "slot": role}:
                fail("ROLE_OWNER_SLOT_MISMATCH", f"fixture owner mismatch: {role}")
        elif required_kind == "policy":
            if owner != {"kind": "policy", "id": policy["policy_id"],
                         "slot": "upstream_source_archive"}:
                fail("ROLE_OWNER_SLOT_MISMATCH", "archive policy owner mismatch")

    builds = exact_role_map(manifest["builds"],
        {role for kind, role in expected if kind == "build"}, "build")
    for role, build in builds.items():
        for reference in [build["cmake_cache_artifact_id"],
                          build["compile_commands_artifact_id"],
                          *build["input_artifact_ids"], *build["output_artifact_ids"]]:
            if reference not in artifact_ids:
                fail("DANGLING_ARTIFACT_REFERENCE", f"build dangling artifact: {reference}")

    fixtures = manifest["fixtures"]
    if len(fixtures) != 1:
        fail("MISSING_FIXTURE_ROLE", "one fixture required")
    fixture = fixtures[0]
    tracked_ids = {item["artifact_id"] for role, item in artifacts.items()
                   if role.startswith("fixture-tracked-")}
    fresh_ids = {item["artifact_id"] for role, item in artifacts.items()
                 if role.startswith("fixture-fresh-")}
    if set(fixture["tracked_artifact_ids"]) != tracked_ids:
        fail("RH10_TRACKED_OUTER_MANIFEST_MISSING", "tracked fixture refs incomplete")
    if set(fixture["fresh_artifact_ids"]) != fresh_ids:
        fail("REFERENCE_GRAPH_CLOSURE", "fresh fixture refs incomplete")
    pairs = [
        ("fixture-tracked-bundle-json", "fixture-fresh-bundle-json"),
        ("fixture-tracked-fixture-manifest", "fixture-fresh-fixture-manifest"),
        ("fixture-tracked-core-package", "fixture-fresh-core-package"),
        ("fixture-tracked-language-package", "fixture-fresh-language-package"),
    ]
    for tracked_role, fresh_role in pairs:
        if artifact_data[tracked_role] != artifact_data[fresh_role]:
            fail("RH10_FRESH_OUTER_MANIFEST_HASH_MISMATCH",
                 f"tracked/fresh differ: {tracked_role}")
    if fixture["tracked_directory_digest"] != fixture["fresh_directory_digest"]:
        fail("RH10_DIRECTORY_DIGEST_MISMATCH", "tracked/fresh digest differs")
    outer = strict_json(artifact_data["fixture-tracked-fixture-manifest"])
    expected_outer = {
        "schema": "cth3ds.runtime-core-test-fixture/v2",
        "payload_origin": "generated_synthetic",
        "contains_original_theme_hospital_data": False,
        "container_schema_claim": {"contains_user_game_data": True,
                                   "redistributable": False},
        "container_claim_scope": "TH3DSR1_container_safety_classification",
    }
    if outer.get("contains_original_theme_hospital_data") is True:
        fail("RH10_OUTER_PROVENANCE_FALSE", "outer provenance claims original data")
    if outer != expected_outer:
        fail("RH10_PROVENANCE_MISMATCH", "outer provenance shape differs")
    trace = strict_json(artifact_data["rh10-open-trace"])
    if trace != {"schema": "cth3ds.runtime-core-fixture-open-trace/v2",
                 "trace_mechanism": "cpython-audit-open",
                 "payload_origin": "generated_synthetic",
                 "output_root": str(roots["evidence_raw"] / "rh10-fresh"),
                 "input_opens": []}:
        fail("RH10_OPEN_TRACE_UNPROVEN", "generator input read set is not empty")
    for role in ("fixture-tracked-core-package",
                 "fixture-tracked-language-package"):
        embedded = extract_embedded_manifest(artifact_data[role])
        if embedded.get("provenance") != {
                "contains_user_game_data": True, "redistributable": False}:
            fail("RH10_CONTAINER_CLAIM_MISMATCH", f"container claim: {role}")

    observation_schema = strict_json(closure_data["observation-schema"][1])
    h1 = strict_json(artifact_data["rh09-h1-stdout"])
    h2 = strict_json(artifact_data["rh07-h2-stdout"])
    reject_forbidden_keys(h1)
    reject_forbidden_keys(h2)
    h1_derived, h2_derived, h1_ok, h2_ok = validate_observations(
        h1, h2, run_id, observation_schema,
        policy["gate_oracles"]["stable_states"])

    ctest_text = (artifact_data["ctest-stdout"] +
                  artifact_data["ctest-stderr"] +
                  artifact_data["ctest-log"]).decode(errors="replace")
    if "100% tests passed, 0 tests failed out of 3" not in ctest_text:
        fail("HOST_REGRESSION_COUNT_MISMATCH", "CTest 3/3 missing")
    cpp_text = (artifact_data["cpp-stdout"] +
                artifact_data["cpp-stderr"]).decode(errors="replace")
    if "Ran 105 tests; 0 failed" not in cpp_text:
        fail("HOST_REGRESSION_COUNT_MISMATCH", "C++ 105/105 missing")
    python_text = (artifact_data["python-stdout"] +
                   artifact_data["python-stderr"]).decode(errors="replace")
    python_counts = parse_unittest_counts(python_text)
    python_skip_reasons = parse_unittest_skip_reasons(python_text)
    expected_skips = policy["host_regression"]["expected_skipped"]
    if python_counts["failures"] or python_counts["errors"]:
        fail("HOST_REGRESSION_COUNT_MISMATCH", "Python failures or errors present")
    if len(python_skip_reasons) != python_counts["skipped"]:
        fail("HOST_REGRESSION_COUNT_MISMATCH",
             "verbose unittest skip reasons do not match summary count")
    allowed_skip_prefixes = tuple(
        policy["host_regression"]["allowed_skip_reason_prefixes"])
    unexpected_skip_reasons = [
        reason for reason in python_skip_reasons
        if not any(reason.startswith(prefix) for prefix in allowed_skip_prefixes)]
    if python_counts["skipped"] != expected_skips or unexpected_skip_reasons:
        fail("HOST_REGRESSION_SKIPPED",
             f"unexpected Python skips: observed={python_counts['skipped']} "
             f"expected={expected_skips} reasons={unexpected_skip_reasons}")
    for role in ("simulator-top-ppm", "simulator-bottom-ppm"):
        ppm = artifact_data[role]
        match = re.match(br"P6\s+(\d+)\s+(\d+)\s+255\s", ppm)
        if not match:
            fail("SIMULATOR_OUTPUT_UNPROVEN", f"invalid PPM header: {role}")
        width, height = map(int, match.groups())
        header = match.end()
        if len(ppm) != header + width * height * 3:
            fail("SIMULATOR_OUTPUT_UNPROVEN", f"invalid PPM length: {role}")
    trace_json = strict_json(artifact_data["simulator-trace-json"])
    if not isinstance(trace_json, dict) or not trace_json:
        fail("SIMULATOR_OUTPUT_UNPROVEN", "simulator trace invalid")
    observed_baseline = {
        "top": sha_bytes(artifact_data["simulator-top-ppm"]),
        "bottom": sha_bytes(artifact_data["simulator-bottom-ppm"]),
        "trace": sha_bytes(artifact_data["simulator-trace-json"]),
    }
    if observed_baseline != policy["simulator_semantic_baseline"]:
        fail("SIMULATOR_BASELINE_MISMATCH",
             f"simulator semantic bytes differ: {observed_baseline}")

    red_cache = artifact_data["red-cmake-cache"].decode(errors="strict")
    red_commands = strict_json(artifact_data["red-compile-commands"])
    if "CTH3DS_ENABLE_SANITIZERS:BOOL=ON" not in red_cache or \
       not isinstance(red_commands, list) or not red_commands or \
       not all("-fsanitize=address,undefined" in item.get("command", "")
               for item in red_commands if
               "test_h1_level_requires_package.cpp" in item.get("command", "") or
               "test_h2_transition_lease_escape.cpp" in item.get("command", "")):
        fail("SANITIZER_INSTRUMENTATION_UNPROVEN", "sanitizer flags missing")
    nm = artifact_data["h1-binary-nm-stdout"] + \
         artifact_data["h2-binary-nm-stdout"]
    if b"asan_" not in nm or b"ubsan_" not in nm:
        fail("SANITIZER_INSTRUMENTATION_UNPROVEN", "sanitizer runtime symbols missing")
    streams = artifact_data["rh09-h1-stdout"] + artifact_data["rh09-h1-stderr"] + \
              artifact_data["rh07-h2-stdout"] + artifact_data["rh07-h2-stderr"]
    if any(marker in streams for marker in SANITIZER_MARKERS):
        fail("SANITIZER_PRODUCT_FAILURE", "sanitizer marker in observer streams")

    upstream_manifest = strict_json(
        artifact_data["xbuild-upstream-source-tree-manifest"])
    integrated_manifest = strict_json(
        artifact_data["xbuild-integrated-source-tree-manifest"])
    for value, role, root_id in (
        (upstream_manifest, "upstream-snapshot", "source_upstream_snapshot"),
        (integrated_manifest, "integrated", "source_xbuild_integrated")):
        if set(value) != {"schema", "tree_role", "run_id", "source_root_id",
                         "file_count", "files", "tree_digest"} or \
           value["schema"] != "cth3ds.source-tree-manifest/v1" or \
           value["tree_role"] != role or value["source_root_id"] != root_id or \
           value["run_id"] != run_id:
            fail("SOURCE_TREE_MANIFEST_INVALID", f"source manifest shape: {role}")
        paths = [item["path"].encode() for item in value["files"]]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            fail("SOURCE_TREE_MANIFEST_INVALID", f"source path ordering: {role}")
        if any(set(item) != {"mode", "path", "bytes", "sha256"} or
               item["mode"] not in {"100644", "100755"} for item in value["files"]):
            fail("SOURCE_TREE_MANIFEST_INVALID", f"source file row: {role}")
    actual_upstream = source_tree(
        roots["source_upstream_snapshot"], policy["limits"]["max_source_files"],
        policy["limits"]["max_source_file_bytes"])
    actual_integrated = source_tree(
        roots["source_xbuild_integrated"], policy["limits"]["max_source_files"],
        policy["limits"]["max_source_file_bytes"])
    expected_upstream = policy["upstream_source"]
    if actual_upstream["file_count"] != expected_upstream["upstream_expected_file_count"]:
        fail("UPSTREAM_SOURCE_TREE_EXPANDED", "upstream source count changed")
    if actual_upstream["tree_digest"] != expected_upstream["upstream_expected_tree_digest"] or \
       upstream_manifest["files"] != actual_upstream["files"]:
        fail("UPSTREAM_SOURCE_TREE_TAMPERED", "upstream source digest changed")
    if actual_integrated["file_count"] != expected_upstream["integrated_expected_file_count"] or \
       actual_integrated["tree_digest"] != expected_upstream["integrated_expected_tree_digest"] or \
       integrated_manifest["files"] != actual_integrated["files"]:
        fail("INTEGRATED_SOURCE_TREE_TAMPERED", "integrated source digest changed")
    if len(artifact_data["xbuild-upstream-snapshot-archive"]) != \
       expected_upstream["archive_bytes"] or \
       sha_bytes(artifact_data["xbuild-upstream-snapshot-archive"]) != \
       expected_upstream["archive_sha256"]:
        fail("UPSTREAM_ARCHIVE_HASH_MISMATCH", "upstream archive differs")

    xcache = artifact_data["xbuild-cmake-cache"].decode(errors="replace")
    xcommands = strict_json(artifact_data["xbuild-compile-commands"])
    xgraph = artifact_data["xbuild-build-graph"].decode(errors="replace")
    symbols = artifact_data["xbuild-key-symbols"].decode(errors="replace")
    elf_headers = artifact_data["xbuild-elf-headers"].decode(errors="replace")
    disassembly = artifact_data["xbuild-allocator-call-disassembly"].decode(
        errors="replace")
    if "CMAKE_TOOLCHAIN_FILE:FILEPATH=/opt/devkitpro/cmake/3DS.cmake" not in xcache or \
       not isinstance(xcommands, list) or not xcommands or \
       "CorsixTH-3DS.elf" not in xgraph:
        fail("XBUILD_COMPILE_LINK_UNPROVEN", "xbuild graph incomplete")
    for needle in ("__ctru_linear_heap_size", "RuntimeSession::start(",
                   "AllocationLedger::allocate(", "linear_allocate(",
                   "regular_allocate(", "linearMemAlign", "memalign"):
        if needle not in symbols:
            fail("XBUILD_COMPILE_LINK_UNPROVEN", f"key symbol absent: {needle}")
    if "ELF32" not in elf_headers or "ARM" not in elf_headers:
        fail("XBUILD_COMPILE_LINK_UNPROVEN", "ELF header is not ARM ELF32")
    if not re.search(r"\bblx?\s+[0-9a-fA-F]+ <linearMemAlign>", disassembly) or \
       not re.search(r"\bblx?\s+[0-9a-fA-F]+ <memalign>", disassembly):
        fail("XBUILD_COMPILE_LINK_UNPROVEN", "allocator calls absent")
    required_elf_symbols = (
        "RuntimeSession::start(", "RuntimeSession::shutdown(",
        "RuntimeSession::enter_menu(", "RuntimeSession::enter_level(",
        "RuntimeSession::begin_save_load(", "RuntimeSession::finish_save_load(",
        "RuntimeSession::suspend(", "RuntimeSession::resume(",
        "BundleMount::open_bundle(", "ResourceManager::acquire(",
        "TransitionToken::~TransitionToken(",
    )
    missing_symbols = [needle for needle in required_elf_symbols if needle not in symbols]
    functions: dict[str, set[str]] = {}
    current: str | None = None
    for line in disassembly.splitlines():
        header = re.match(r"^[0-9a-fA-F]+ <(.+)>:$", line)
        if header:
            current = header.group(1)
            functions.setdefault(current, set())
            continue
        if current is not None:
            call = re.search(r"\b(?:b|bl|blx)\b[^<]*<(.+)>", line)
            if call and not re.search(r"\+0x[0-9a-fA-F]+$", call.group(1)):
                functions[current].add(call.group(1))
    production_entries = [name for name in functions
                          if "cth3ds::runtime_initialize(" in name]
    goals = {name for name in functions if "RuntimeSession::start(" in name}
    queue = [(entry, [entry]) for entry in production_entries]
    visited = set(production_entries)
    call_path: list[str] = []
    while queue:
        node, path = queue.pop(0)
        if node in goals:
            call_path = path
            break
        for target in sorted(functions.get(node, ())):
            if target not in visited:
                visited.add(target)
                queue.append((target, path + [target]))
    heap_symbol = re.search(
        r"(?m)^([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+([A-Za-z])\s+__ctru_linear_heap_size$",
        symbols)
    data_section = re.search(
        r"(?m)^\s*\[\s*\d+\]\s+\.data\s+\S+\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+",
        elf_headers)
    heap_value = None
    if heap_symbol and data_section:
        symbol_address = int(heap_symbol.group(1), 16)
        data_address = int(data_section.group(1), 16)
        data_offset = int(data_section.group(2), 16)
        position = data_offset + symbol_address - data_address
        elf_bytes = artifact_data["xbuild-final-elf"]
        if 0 <= position <= len(elf_bytes) - 4:
            heap_value = struct.unpack_from("<I", elf_bytes, position)[0]
    final_elf_proof = {
        "required_symbols_present": not missing_symbols,
        "missing_symbols": missing_symbols,
        "production_entry": production_entries,
        "runtime_session_call_path": call_path,
        "whole_archive_used": "--whole-archive" in xgraph,
        "heap_symbol_type": heap_symbol.group(2) if heap_symbol else None,
        "heap_value_bytes": heap_value,
        "pass": (not missing_symbols and bool(call_path) and
                 "--whole-archive" not in xgraph and heap_symbol is not None and
                 heap_symbol.group(2) == "D" and heap_value == 8388608),
    }
    if not final_elf_proof["pass"]:
        fail("FINAL_ELF_RUNTIME_CORE_UNPROVEN",
             f"mandatory final ELF proof failed: {final_elf_proof}")

    if not h1_ok:
        fail("RH09_RED_ORACLE_MISMATCH", "H1 does not exactly match frozen red oracle")
    if not h2_ok:
        fail("RH07_RED_ORACLE_MISMATCH", "H2 does not exactly match frozen red oracle")

    # All eighteen canonical fact checks are complete.  The derive phase records
    # authenticated inputs without gaining authority to write a final verdict.
    inputs = []
    def add_input(seal_id: str, basename: str, data: bytes, kind: str,
                  root_id: str, relative_path: str) -> None:
        sealed = f"sealed/{seal_id}/{basename}"
        if not args.derive and not args.case_evaluate:
            sealed = seal_bytes(seal, seal_id, basename, data)
        inputs.append({"seal_id": seal_id, "kind": kind, "root_id": root_id,
                       "relative_path": relative_path, "bytes": len(data),
                       "sha256": sha_bytes(data), "sealed_relative_path": sealed})

    add_input("policy", policy_path.name, policy_raw, "policy",
              "reviewer_bundle", policy_path.relative_to(
                  roots["reviewer_bundle"]).as_posix())
    add_input("producer-manifest", manifest_path.name, manifest_raw,
              "producer_manifest", "evidence_raw", "producer-manifest.json")
    for role, (item, data) in closure_data.items():
        add_input("ci-" + role, Path(item["relative_path"]).name, data,
                  "closure_input", "candidate", item["relative_path"])
    for role, item in artifacts.items():
        add_input(item["artifact_id"], Path(item["relative_path"]).name,
                  artifact_data[role], "artifact", item["root_id"],
                  item["relative_path"])
    for role, item in tools.items():
        data = bootstrap_read(Path(item["absolute_realpath"]),
                              require_single_link=False)
        add_input("tool-" + role, Path(item["absolute_realpath"]).name, data,
                  "tool", "system", item["absolute_realpath"])
        if role == "python":
            for index, dependency in enumerate(item["runtime_dependency_files"]):
                data = bootstrap_read(Path(dependency["absolute_realpath"]),
                                      require_single_link=False)
                if len(data) != dependency["bytes"] or \
                   sha_bytes(data) != dependency["sha256"]:
                    fail("TOOL_HASH_MISMATCH", "Python runtime dependency changed")
                add_input(f"python-dep-{index:03d}",
                          Path(dependency["absolute_realpath"]).name, data,
                          "tool_dependency", "system",
                          dependency["absolute_realpath"])
    _, head_commit, _ = run_git(git_path, candidate, "cat-file", "-p", head)
    _, head_tree, _ = run_git(git_path, candidate, "cat-file", "-p", tree)
    add_input("git-head-commit", head, head_commit, "git_object",
              "candidate_git", head)
    add_input("git-head-tree", tree, head_tree, "git_object",
              "candidate_git", tree)
    for index, row in enumerate(ancestry["commits"]):
        raw_commit = run_git(git_path, candidate, "--no-replace-objects",
                             "cat-file", "commit", row["oid"])[1]
        add_input(f"git-ancestry-{index:04d}", row["oid"], raw_commit,
                  "git_commit_object", "candidate_git", row["oid"])

    run_manifest = {
        "schema": "cth3ds.runtime-core-run-manifest/v5", "stage_id": "C3-R5",
        "run_id": run_id, "policy_id": policy["policy_id"],
        "policy_sha256": args.expected_policy_sha256,
        "candidate_identity": live_identity,
        "producer_manifest_sha256": sha_bytes(manifest_raw),
        "inputs": sorted(inputs, key=lambda item: item["seal_id"]),
        "source_trees": {
            "upstream": actual_upstream, "integrated": actual_integrated},
        "derived": {
            "h1": h1_derived, "h2": h2_derived,
            "heap_budget_bytes": 8388608,
            "runtime_core_link_proven": True,
            "raw_ancestry_closure_sha256": ancestry["closure_sha256"],
            "tool_implementation_identity_sha256": live_tool_identity["sha256"],
            "xbuild_input_closures": xbuild_closures,
            "final_elf_runtime_core_proof": final_elf_proof,
            "upstream_git_provenance": "NOT_PROVEN",
        },
    }
    run_raw = canonical(run_manifest)
    if args.derive:
        facts_root = args.facts_root.resolve()
        if facts_root.exists() and any(facts_root.iterdir()):
            fail("FACTS_ROOT_NOT_EMPTY", "facts root must be fresh and empty")
        facts_root.mkdir(parents=True, exist_ok=True)
        facts = {
            "schema": "cth3ds.runtime-core-derived-facts/v1",
            "stage_id": "C3-R5",
            "run_id": run_id,
            "policy_id": policy["policy_id"],
            "policy_sha256": args.expected_policy_sha256,
            "candidate_identity_live": live_identity,
            "producer_manifest_sha256": sha_bytes(manifest_raw),
            "run_manifest_sha256": sha_bytes(run_raw),
            "closure_facts": {
                "checks": {name: True for name in FACT_PROTOCOL_GATES},
                "policy_sha256": args.expected_policy_sha256,
                "producer_manifest_sha256": sha_bytes(manifest_raw),
                "input_count": len(inputs),
                "raw_ancestry_closure_sha256": ancestry["closure_sha256"],
                "tool_implementation_identity_sha256": live_tool_identity["sha256"],
                "xbuild_input_closures": xbuild_closures,
                "raw_evidence_relative_and_checksum_bound": True,
            },
            "host_facts": {"ctest_passed": 3, "ctest_failed": 0,
                           "ctest_total": 3,
                           "cpp_passed": 105, "cpp_failed": 0,
                           "cpp_total": 105, **{"python_" + key: value
                           for key, value in python_counts.items()},
                           "python_unexpected_skipped": 0},
            "simulator_facts": {
                "top_ppm_sha256": sha_bytes(artifact_data["simulator-top-ppm"]),
                "bottom_ppm_sha256": sha_bytes(artifact_data["simulator-bottom-ppm"]),
                "trace_sha256": sha_bytes(artifact_data["simulator-trace-json"]),
            },
            "sanitizer_facts": {
                "instrumentation": True, "runtime_symbols": True,
                "clean_streams": True,
            },
            "rh09_facts": {"observation": h1, "derived": h1_derived,
                           "red_oracle_match": h1_ok},
            "rh07_facts": {"observation": h2, "derived": h2_derived,
                           "red_oracle_match": h2_ok},
            "rh10_facts": {
                "synthetic_provenance": True,
                "tracked_directory_digest": fixture["tracked_directory_digest"],
                "fresh_directory_digest": fixture["fresh_directory_digest"],
            },
            "xbuild_facts": {
                "compile_link": True,
                "input_closures": xbuild_closures,
                "runtime_core_final_elf_proof": final_elf_proof,
                "elf_sha256": sha_bytes(artifact_data["xbuild-final-elf"]),
                "three_dsx_sha256": sha_bytes(artifact_data["xbuild-final-3dsx"]),
            },
            "upstream_snapshot_facts": {
                "bytes_closed": True,
                "archive_sha256": sha_bytes(
                    artifact_data["xbuild-upstream-snapshot-archive"]),
                "upstream_tree_digest": actual_upstream["tree_digest"],
                "integrated_tree_digest": actual_integrated["tree_digest"],
            },
            "product_boundary_facts": {
                "product_diff_zero": True,
                "product_fingerprint_v3": product_fp,
                "upstream_git_provenance": "NOT_PROVEN",
                "real_device_runtime": "NOT_PROVEN",
                "s70_real_device_memory": "NOT_PROVEN",
            },
        }
        reject_final_authority(run_manifest)
        reject_final_authority(facts)
        write_once(facts_root / "run-manifest.json", run_raw)
        facts_raw = canonical(facts)
        write_once(facts_root / "derived-facts.json", facts_raw)
        print(json.dumps({"derive": "PASS", "run_id": run_id,
                          "facts": str(facts_root / "derived-facts.json"),
                          "facts_sha256": sha_bytes(facts_raw),
                          "run_manifest_sha256": sha_bytes(run_raw)},
                         sort_keys=True, separators=(",", ":")))
        return 0

    # A matrix case evaluator has verdict authority only for its process exit.
    # It deliberately writes no seal-like artifact.  The canonical seal root
    # therefore stays empty until the receipt-gated finalizer runs.
    if any(seal.iterdir()):
        fail("CANONICAL_SEAL_RESERVED_EMPTY", "case evaluation seal root changed")
    print(json.dumps({"matrix_case_evaluation": "PASS", "c3": "PASS",
        "review": "ACCEPT_C3_EVIDENCE_PROTOCOL", "artifact_written": False},
        sort_keys=True, separators=(",", ":")))
    return 0


def verify_closure_fixture(args: argparse.Namespace) -> int:
    fixture = args.closure_fixture_root.resolve(strict=True)
    sums_path = fixture / "SHA256SUMS"
    if not sums_path.is_file():
        fail("CLOSURE_FIXTURE_REQUIRED_FILE_MISSING", "SHA256SUMS missing")
    sums_raw = bootstrap_read(sums_path, 32 * 1024 * 1024)
    if not args.expected_closure_fixture_sha256 or \
       sha_bytes(sums_raw) != args.expected_closure_fixture_sha256:
        fail("EXTERNAL_SHA256SUMS_DIGEST_MISMATCH",
             "fixture differs from external anchor")
    required = {"run-manifest.json", "derived-facts.json",
                "fixture-manifest.json", "result.json"}
    rows = sums_raw.decode("utf-8").splitlines()
    seen: set[str] = set()
    for row in rows:
        if not re.fullmatch(r"[0-9a-f]{64}  [^\x00]+", row):
            fail("FINAL_CHECKSUM_FORMAT", "invalid fixture checksum row")
        digest, relative = row.split("  ", 1)
        clean_relative(relative)
        if relative == "SHA256SUMS" or relative in seen:
            fail("FINAL_CHECKSUM_FORMAT", "duplicate/self fixture checksum")
        seen.add(relative)
        path = fixture / relative
        if not path.is_file() or sha_bytes(secure_read(
                fixture, relative, 268435456,
                require_single_link=False)) != digest:
            fail("FINAL_CHECKSUM_MISMATCH", f"fixture checksum mismatch: {relative}")
    actual = {path.relative_to(fixture).as_posix() for path in fixture.rglob("*")
              if path.is_file() and path.name != "SHA256SUMS"}
    if seen != actual:
        fail("FINAL_CHECKSUM_MISMATCH", "fixture checksum set is not exact")
    if not required.issubset(seen):
        fail("CLOSURE_FIXTURE_REQUIRED_FILE_MISSING", "fixture top-level file missing")
    manifest_raw = secure_read(fixture, "fixture-manifest.json", 268435456,
                               require_single_link=False)
    result_raw = secure_read(fixture, "result.json", 268435456,
                             require_single_link=False)
    run_raw = secure_read(fixture, "run-manifest.json", 268435456,
                          require_single_link=False)
    facts_raw = secure_read(fixture, "derived-facts.json", 268435456,
                            require_single_link=False)
    manifest = strict_json(manifest_raw, "CLOSURE_FIXTURE_SCHEMA_INVALID")
    result = strict_json(result_raw, "CLOSURE_FIXTURE_SCHEMA_INVALID")
    run_manifest = strict_json(run_raw, "CLOSURE_FIXTURE_SCHEMA_INVALID")
    facts = strict_json(facts_raw, "CLOSURE_FIXTURE_SCHEMA_INVALID")
    if not isinstance(manifest, dict) or not isinstance(result, dict) or \
       manifest.get("schema") != \
       "cth3ds.runtime-core-closure-test-fixture-manifest/v1" or \
       manifest.get("fixture_kind") != "CLOSURE_TEST_ONLY" or \
       result.get("schema") != "cth3ds.runtime-core-closure-test-result/v1":
        fail("CLOSURE_FIXTURE_SCHEMA_INVALID", "fixture type/schema invalid")
    schema_path = next((path for path in fixture.rglob("result.schema.json")
                        if path.is_file()), None)
    if schema_path is None:
        fail("SCHEMA_NOT_SEALED", "result schema missing from fixture")
    schema = strict_json(bootstrap_read(schema_path))
    validate_definition(manifest, schema, "closure_fixture_manifest",
                        "CLOSURE_FIXTURE_SCHEMA_INVALID")
    validate_definition(result, schema, "closure_fixture_result",
                        "CLOSURE_FIXTURE_SCHEMA_INVALID")
    role_codes = {
        "ci-consumer": "CONSUMER_NOT_SEALED",
        "policy": "POLICY_NOT_SEALED",
        "ci-observation-schema": "SCHEMA_NOT_SEALED",
        "ci-red-oracle": "ORACLE_NOT_SEALED",
    }
    inputs = run_manifest.get("inputs", [])
    by_id = {item.get("seal_id"): item for item in inputs
             if isinstance(item, dict)}
    for seal_id, code in role_codes.items():
        item = by_id.get(seal_id)
        relative = item.get("sealed_relative_path") if item else None
        if not relative or relative not in seen or not (fixture / relative).is_file():
            fail(code, f"fixture sealed role missing: {seal_id}")
    if manifest.get("review_session_id") != args.expected_review_session_id:
        fail("CLOSURE_FIXTURE_REVIEW_SESSION_MISMATCH", "review session differs")
    if manifest.get("canonical_run_id") != args.expected_canonical_run_id or \
       result.get("canonical_run_id") != args.expected_canonical_run_id:
        fail("CLOSURE_FIXTURE_RUN_ID_MISMATCH", "canonical run differs")
    identity = manifest.get("candidate_identity", {})
    if identity.get("commit") != args.expected_candidate_head or \
       identity.get("tree") != args.expected_candidate_tree or \
       identity.get("first_parent") != args.expected_candidate_parent:
        fail("CLOSURE_FIXTURE_CANDIDATE_MISMATCH", "candidate differs")
    if manifest.get("policy_id") != args.expected_fixture_policy_id or \
       manifest.get("policy_sha256") != args.expected_fixture_policy_sha256:
        fail("CLOSURE_FIXTURE_POLICY_MISMATCH", "policy differs")
    if manifest.get("run_manifest_sha256") != args.expected_run_manifest_sha256 or \
       manifest.get("derived_facts_sha256") != args.expected_derived_facts_sha256 or \
       sha_bytes(run_raw) != args.expected_run_manifest_sha256 or \
       sha_bytes(facts_raw) != args.expected_derived_facts_sha256:
        fail("CLOSURE_FIXTURE_FACTS_MISMATCH", "facts binding differs")
    if manifest.get("fixture_id") != result.get("fixture_id") or \
       manifest.get("review_session_id") != result.get("review_session_id") or \
       result.get("candidate_identity") != identity or \
       result.get("policy_sha256") != manifest.get("policy_sha256") or \
       result.get("run_manifest_sha256") != manifest.get("run_manifest_sha256") or \
       result.get("derived_facts_sha256") != manifest.get("derived_facts_sha256"):
        fail("CLOSURE_FIXTURE_FACTS_MISMATCH", "fixture internal binding differs")
    if manifest.get("single_use") is not True or \
       manifest.get("final_acceptance_eligible") is not False or \
       result.get("fixture_verdict") != "PASS" or result.get("c3") != "NOT_PROVEN" or \
       result.get("matrix_gate_status") != "NOT_RUN" or \
       result.get("review_verdict") != "REJECT_C3_EVIDENCE_PROTOCOL" or \
       result.get("final_acceptance_eligible") is not False or \
       result.get("failure_codes") != ["MATRIX_NOT_RUN"]:
        fail("CLOSURE_FIXTURE_FINAL_ACCEPT_FORBIDDEN",
             "fixture attempted to carry final authority")
    if len(inputs) != manifest.get("source_input_count"):
        fail("CLOSURE_FIXTURE_FACTS_MISMATCH", "fixture input count differs")
    state = args.fixture_consumption_state
    if state:
        state = state.resolve()
        if state.exists():
            fail("CLOSURE_FIXTURE_ALREADY_CONSUMED", "fixture already consumed")
        if args.consume_closure_fixture:
            state.parent.mkdir(parents=True, exist_ok=True)
            write_once(state, canonical({"fixture_id": manifest["fixture_id"],
                                         "review_session_id": manifest["review_session_id"]}))
    print(json.dumps({"closure_fixture": "PASS", "c3": "NOT_PROVEN",
        "matrix_gate_status": "NOT_RUN",
        "review_verdict": "REJECT_C3_EVIDENCE_PROTOCOL",
        "final_acceptance_eligible": False, "fixture_id": manifest["fixture_id"]},
        sort_keys=True, separators=(",", ":")))
    return 0


RECEIPT_FIELDS = {
    "schema", "stage_id", "review_session_id", "created_at",
    "canonical_run_id", "candidate_identity", "policy_id", "policy_sha256",
    "producer_manifest_sha256", "run_manifest_sha256", "facts_sha256",
    "matrix_sha256", "runner_sha256", "fact_consumer_sha256",
    "summary_sha256", "case_set_sha256", "case_count", "case_id_set",
    "passed", "failed", "cases", "closure_fixture", "matrix",
}
CASE_FIELDS = {
    "id", "mutation_sha256", "stdout_sha256", "stderr_sha256",
    "actual_exit", "actual_gate", "actual_product", "actual_review",
    "actual_failure_code", "expected_exit", "expected_gate",
    "expected_product", "expected_review", "expected_failure_code", "pass",
}


def live_identity_from_policy(candidate: Path, policy: dict[str, Any]) -> dict[str, Any]:
    git_path = next((item["absolute_realpath"] for item in
                     strict_json(bootstrap_read(
                         Path(next(row["absolute_realpath"] for row in policy["roots"]
                                   if row["root_id"] == "evidence_raw")) /
                         "producer-manifest.json"))["tools"]
                     if item["role"] == "git"), "/usr/bin/git")
    head = run_git(git_path, candidate, "rev-parse", "HEAD^{commit}")[1].decode().strip()
    tree = run_git(git_path, candidate, "rev-parse", "HEAD^{tree}")[1].decode().strip()
    parents = run_git(git_path, candidate, "show", "-s", "--format=%P", head)[1].decode().split()
    tracked_fp, tracked_count, _ = fingerprint(git_path, candidate, head)
    if parents != [BASE_COMMIT]:
        fail("GIT_TOPOLOGY", "finalizer candidate is not A0 single-parent")
    return {"commit": head, "tree": tree, "first_parent": BASE_COMMIT,
            "tracked_fingerprint_v3": tracked_fp,
            "tracked_entries": tracked_count}


def load_facts_bundle(facts_root: Path, expected_facts_sha256: str | None
                      ) -> tuple[bytes, dict[str, Any], bytes, dict[str, Any]]:
    facts_raw = bootstrap_read(facts_root / "derived-facts.json")
    if not expected_facts_sha256 or not HEX64.fullmatch(expected_facts_sha256):
        fail("EXPECTED_FACTS_DIGEST_REQUIRED", "external facts digest required")
    if sha_bytes(facts_raw) != expected_facts_sha256:
        fail("FACTS_DIGEST_MISMATCH", "derived facts differ from external digest")
    run_raw = bootstrap_read(facts_root / "run-manifest.json")
    facts = strict_json(facts_raw)
    run_manifest = strict_json(run_raw)
    reject_final_authority(facts)
    reject_final_authority(run_manifest)
    if facts.get("run_manifest_sha256") != sha_bytes(run_raw):
        fail("RECEIPT_CANONICAL_RUN_MISMATCH", "facts/run manifest digest mismatch")
    return facts_raw, facts, run_raw, run_manifest


def validate_policy_acceptance(policy: dict[str, Any], candidate: Path,
                               matrix_raw: bytes,
                               expected_matrix_sha256: str | None) -> None:
    if not expected_matrix_sha256 or not HEX64.fullmatch(expected_matrix_sha256):
        fail("EXPECTED_MATRIX_DIGEST_REQUIRED", "external matrix digest required")
    acceptance = policy.get("acceptance_inputs")
    if not isinstance(acceptance, dict):
        fail("POLICY_SCHEMA", "policy acceptance inputs missing")
    if sha_bytes(matrix_raw) != expected_matrix_sha256 or \
       acceptance.get("matrix_sha256") != expected_matrix_sha256:
        fail("MATRIX_HASH_MISMATCH", "matrix differs from frozen external digest")
    runner = candidate / acceptance.get("runner_relative_path", "")
    consumer = candidate / acceptance.get("fact_consumer_relative_path", "")
    schema = candidate / "tests/runtime_core_v2/result.schema.json"
    if sha_bytes(bootstrap_read(runner)) != acceptance.get("runner_sha256"):
        fail("RUNNER_HASH_MISMATCH", "runner differs from policy")
    consumer_sha = sha_bytes(bootstrap_read(consumer))
    if consumer_sha != acceptance.get("fact_consumer_sha256") or \
       consumer_sha != acceptance.get("finalizer_sha256"):
        fail("CONSUMER_HASH_MISMATCH", "consumer/finalizer differs from policy")
    if sha_bytes(bootstrap_read(schema)) != acceptance.get("result_schema_sha256"):
        fail("SCHEMA_HASH_MISMATCH", "result schema differs from policy")
    if acceptance.get("required_protocol_gate_ids") != REQUIRED_PROTOCOL_GATES or \
       acceptance.get("required_product_baseline") != REQUIRED_PRODUCT_BASELINE:
        fail("POLICY_SCHEMA", "frozen acceptance set differs")


def receipt_payload(receipt_path: Path) -> tuple[bytes, dict[str, Any]]:
    if not receipt_path.is_file():
        fail("MATRIX_RECEIPT_MISSING", "reviewer matrix receipt missing")
    raw = bootstrap_read(receipt_path)
    value = strict_json(raw)
    if not isinstance(value, dict) or not RECEIPT_FIELDS.issubset(value):
        fail("RECEIPT_REQUIRED_FIELD_MISSING", "receipt required field missing")
    if set(value) != RECEIPT_FIELDS:
        fail("NESTED_UNKNOWN_FIELD", "receipt has unknown field")
    return raw, value


def validate_receipt(receipt_raw: bytes, receipt: dict[str, Any],
                     expected_receipt_sha256: str | None,
                     policy: dict[str, Any], facts_raw: bytes,
                     facts: dict[str, Any], run_raw: bytes,
                     run_manifest: dict[str, Any], matrix_raw: bytes,
                     matrix_root: Path) -> None:
    if not expected_receipt_sha256 or not HEX64.fullmatch(expected_receipt_sha256):
        fail("EXPECTED_MATRIX_RECEIPT_DIGEST_REQUIRED",
             "external reviewer receipt digest required")
    if sha_bytes(receipt_raw) != expected_receipt_sha256:
        fail("MATRIX_RECEIPT_DIGEST_MISMATCH",
             "receipt differs from external reviewer digest")
    if receipt.get("canonical_run_id") != facts.get("run_id"):
        fail("RECEIPT_RUN_ID_MISMATCH", "receipt run differs")
    if receipt.get("candidate_identity") != facts.get("candidate_identity_live"):
        fail("RECEIPT_CANDIDATE_MISMATCH", "receipt candidate differs")
    if receipt.get("policy_id") != facts.get("policy_id") or \
       receipt.get("policy_sha256") != facts.get("policy_sha256"):
        fail("RECEIPT_POLICY_MISMATCH", "receipt policy differs")
    if receipt.get("producer_manifest_sha256") != \
            facts.get("producer_manifest_sha256") or \
       receipt.get("run_manifest_sha256") != sha_bytes(run_raw) or \
       receipt.get("facts_sha256") != sha_bytes(facts_raw):
        fail("RECEIPT_CANONICAL_RUN_MISMATCH", "receipt facts binding differs")
    acceptance = policy["acceptance_inputs"]
    if receipt.get("matrix_sha256") != sha_bytes(matrix_raw):
        fail("MATRIX_HASH_MISMATCH", "receipt matrix differs")
    if receipt.get("runner_sha256") != acceptance["runner_sha256"]:
        fail("RUNNER_HASH_MISMATCH", "receipt runner differs")
    if receipt.get("fact_consumer_sha256") != \
            acceptance["fact_consumer_sha256"]:
        fail("RECEIPT_CANONICAL_RUN_MISMATCH", "receipt consumer differs")
    fresh = policy.get("fresh_chain", {})
    if receipt.get("review_session_id") != fresh.get("review_session_id"):
        fail("RECEIPT_REVIEW_SESSION_MISMATCH", "receipt review session differs")
    fixture = receipt.get("closure_fixture")
    if not isinstance(fixture, dict) or set(fixture) != {
            "fixture_id", "fixture_manifest_sha256", "sha256s_sha256",
            "consumed_once", "final_acceptance_eligible"} or \
       not ID32.fullmatch(str(fixture.get("fixture_id", ""))) or \
       not HEX64.fullmatch(str(fixture.get("fixture_manifest_sha256", ""))) or \
       not HEX64.fullmatch(str(fixture.get("sha256s_sha256", ""))) or \
       fixture.get("consumed_once") is not True or \
       fixture.get("final_acceptance_eligible") is not False:
        fail("RECEIPT_CLOSURE_FIXTURE_MISMATCH", "receipt fixture binding invalid")
    matrix_binding = receipt.get("matrix")
    if matrix_binding != {"definition_sha256": sha_bytes(matrix_raw),
                          "total": receipt.get("case_count"),
                          "passed": receipt.get("passed"),
                          "failed": receipt.get("failed")}:
        fail("MATRIX_HASH_MISMATCH", "receipt matrix binding differs")
    summary_raw = bootstrap_read(matrix_root / "summary.json")
    case_set_raw = bootstrap_read(matrix_root / "case-set.json")
    if sha_bytes(summary_raw) != receipt.get("summary_sha256"):
        fail("MATRIX_SUMMARY_DIGEST_MISMATCH", "matrix summary digest differs")
    if sha_bytes(case_set_raw) != receipt.get("case_set_sha256"):
        fail("MATRIX_CASE_SET_DIGEST_MISMATCH", "case-set digest differs")
    summary = strict_json(summary_raw)
    case_set = strict_json(case_set_raw)
    cases = receipt.get("cases")
    if not isinstance(cases, list):
        fail("MATRIX_CASE_SET_INCOMPLETE", "receipt cases missing")
    if receipt.get("case_count") == 0 and cases == []:
        fail("MATRIX_EXECUTION_COUNT_MISMATCH", "zero matrix cases executed")
    expected_ids = [f"E{index:02d}" for index in range(1, 61)]
    ids = [item.get("id") for item in cases if isinstance(item, dict)]
    if ids != expected_ids or any(set(item) != CASE_FIELDS for item in cases
                                  if isinstance(item, dict)):
        fail("MATRIX_CASE_SET_INCOMPLETE", "case IDs/shape are not exact")
    if not isinstance(case_set, dict) or case_set.get("cases") != cases or \
       not isinstance(summary, dict) or summary.get("cases") != cases:
        fail("MATRIX_CASE_SET_INCOMPLETE", "summary/case-set rows differ")
    if receipt.get("case_count") != 60 or receipt.get("case_id_set") != "E01..E60" or \
       summary.get("total") != 60:
        fail("MATRIX_EXECUTION_COUNT_MISMATCH", "matrix execution count differs")
    if receipt.get("passed") != 60 or receipt.get("failed") != 0 or \
       summary.get("passed") != 60 or summary.get("failed") != 0 or \
       any(item.get("pass") is not True for item in cases):
        fail("MATRIX_CASE_FAILED", "one or more frozen cases failed")
    for item in cases:
        base = matrix_root / "cases" / item["id"]
        for name, field in (("mutation.json", "mutation_sha256"),
                            ("stdout", "stdout_sha256"),
                            ("stderr", "stderr_sha256")):
            path = base / name
            if not path.is_file() or sha_bytes(bootstrap_read(path)) != item[field]:
                fail("MATRIX_CASE_OUTPUT_MISMATCH",
                     f"case output digest differs: {item['id']}/{name}")


def deterministic_result(facts_raw: bytes, facts: dict[str, Any],
                         run_raw: bytes, receipt_raw: bytes) -> dict[str, Any]:
    checks = facts.get("closure_facts", {}).get("checks")
    if not isinstance(checks, dict) or set(checks) != set(FACT_PROTOCOL_GATES) or \
       any(checks[name] is not True for name in FACT_PROTOCOL_GATES):
        fail("FINAL_RESULT_DERIVATION_MISMATCH", "canonical facts are incomplete")
    if facts.get("rh09_facts", {}).get("red_oracle_match") is not True or \
       facts.get("rh07_facts", {}).get("red_oracle_match") is not True:
        fail("PRODUCT_VERDICT_MISMATCH", "red oracle facts do not match")
    gates = {name: "PASS" for name in REQUIRED_PROTOCOL_GATES}
    return {
        "schema": "cth3ds.runtime-core-result/v5", "stage_id": "C3-R5",
        "artifact_kind": "FINAL_REVIEW_SEAL",
        "review_session_id": strict_json(receipt_raw)["review_session_id"],
        "run_id": facts["run_id"], "policy_id": facts["policy_id"],
        "policy_sha256": facts["policy_sha256"],
        "candidate_identity": facts["candidate_identity_live"],
        "protocol_gates": gates,
        "product_verdicts": dict(REQUIRED_PRODUCT_BASELINE),
        "review_verdict": "ACCEPT_C3_EVIDENCE_PROTOCOL",
        "matrix_gate_status": "PASS", "matrix_passed": 60,
        "matrix_failed": 0, "final_acceptance_eligible": True,
        "failure_codes": list(REQUIRED_FAILURE_CODES),
        "run_manifest_sha256": sha_bytes(run_raw),
        "derived_facts_sha256": sha_bytes(facts_raw),
        "matrix_receipt_sha256": sha_bytes(receipt_raw),
    }


def write_tree_file(root: Path, relative: str, data: bytes) -> None:
    parts = clean_relative(relative)
    target = root.joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_once(target, data)


def source_input_bytes(item: dict[str, Any], roots: dict[str, Path],
                       candidate: Path, git_path: str) -> bytes:
    root_id = item["root_id"]
    relative = item["relative_path"]
    if root_id == "system":
        return bootstrap_read(Path(relative), require_single_link=False)
    if root_id == "candidate_git":
        return run_git(git_path, candidate, "cat-file", "-p", relative)[1]
    if root_id not in roots:
        fail("SEALED_INPUT_CLOSURE", f"unknown input root: {root_id}")
    return secure_read(roots[root_id], relative, 268435456,
                       require_single_link=root_id != "reviewer_bundle")


def finalize(args: argparse.Namespace) -> int:
    if args.matrix_receipt is None:
        fail("MATRIX_RECEIPT_MISSING", "reviewer matrix receipt missing")
    if not args.expected_matrix_receipt_sha256:
        fail("EXPECTED_MATRIX_RECEIPT_DIGEST_REQUIRED",
             "external reviewer receipt digest required")
    candidate = args.candidate_root.resolve(strict=True)
    policy_raw = bootstrap_read(args.policy.resolve(strict=True))
    if not args.expected_policy_sha256 or sha_bytes(policy_raw) != args.expected_policy_sha256:
        fail("POLICY_HASH_MISMATCH", "policy differs from external digest")
    policy = strict_json(policy_raw)
    matrix_raw = bootstrap_read(args.matrix.resolve(strict=True))
    validate_policy_acceptance(policy, candidate, matrix_raw,
                               args.expected_matrix_sha256)
    canonical_seal = Path(next(row["absolute_realpath"] for row in policy["roots"]
                               if row["root_id"] == "seal"))
    if canonical_seal.resolve(strict=True) == args.seal_root.resolve() or \
       any(canonical_seal.iterdir()):
        fail("CANONICAL_SEAL_RESERVED_EMPTY",
             "canonical pre-matrix seal must remain empty")
    facts_raw, facts, run_raw, run_manifest = load_facts_bundle(
        args.facts_root.resolve(strict=True), args.expected_facts_sha256)
    evidence_root = Path(next(
        row["absolute_realpath"] for row in policy["roots"]
        if row["root_id"] == "evidence_raw"))
    manifest_path = evidence_root / "producer-manifest.json"
    manifest_raw = bootstrap_read(manifest_path)
    manifest = strict_json(manifest_raw)
    reject_final_authority(manifest)
    live = live_identity_from_policy(candidate, policy)
    if manifest.get("policy_id") != policy.get("policy_id") or \
       manifest.get("policy_sha256") != args.expected_policy_sha256:
        fail("POLICY_BINDING_MISMATCH", "producer policy binding differs")
    if manifest.get("candidate_identity") != live:
        fail("MANIFEST_CANDIDATE_BINDING_MISMATCH", "manifest/live candidate differs")
    if facts.get("candidate_identity_live") != live or \
       run_manifest.get("candidate_identity") != live:
        fail("RESULT_CANDIDATE_BINDING_MISMATCH", "facts/live candidate differs")
    if facts.get("policy_id") != policy.get("policy_id") or \
       facts.get("policy_sha256") != args.expected_policy_sha256 or \
       run_manifest.get("policy_id") != policy.get("policy_id") or \
       run_manifest.get("policy_sha256") != args.expected_policy_sha256:
        fail("RESULT_MANIFEST_BINDING_MISMATCH", "facts/run policy differs")
    if facts.get("producer_manifest_sha256") != sha_bytes(manifest_raw) or \
       run_manifest.get("producer_manifest_sha256") != sha_bytes(manifest_raw):
        fail("RECEIPT_CANONICAL_RUN_MISMATCH", "producer digest differs")
    receipt_raw, receipt = receipt_payload(args.matrix_receipt.resolve())
    validate_receipt(receipt_raw, receipt,
                     args.expected_matrix_receipt_sha256, policy, facts_raw,
                     facts, run_raw, run_manifest, matrix_raw,
                     args.matrix_root.resolve(strict=True))
    if args.closure_fixture_root is None or \
       not args.expected_closure_fixture_sha256:
        fail("CLOSURE_FIXTURE_REQUIRED_FILE_MISSING",
             "finalizer requires externally anchored closure fixture")
    fixture_binding = receipt["closure_fixture"]
    if args.expected_closure_fixture_sha256 != \
       fixture_binding["sha256s_sha256"]:
        fail("EXTERNAL_SHA256SUMS_DIGEST_MISMATCH",
             "receipt and fixture anchor differ")
    fixture_root = args.closure_fixture_root.resolve(strict=True)
    if sha_bytes(bootstrap_read(fixture_root / "fixture-manifest.json")) != \
       fixture_binding["fixture_manifest_sha256"]:
        fail("RECEIPT_CLOSURE_FIXTURE_MISMATCH",
             "fixture manifest differs from receipt")
    args.expected_review_session_id = receipt["review_session_id"]
    args.expected_canonical_run_id = facts["run_id"]
    args.expected_candidate_head = facts["candidate_identity_live"]["commit"]
    args.expected_candidate_tree = facts["candidate_identity_live"]["tree"]
    args.expected_candidate_parent = facts["candidate_identity_live"]["first_parent"]
    args.expected_fixture_policy_id = facts["policy_id"]
    args.expected_fixture_policy_sha256 = facts["policy_sha256"]
    args.expected_run_manifest_sha256 = sha_bytes(run_raw)
    args.expected_derived_facts_sha256 = sha_bytes(facts_raw)
    args.fixture_consumption_state = None
    args.consume_closure_fixture = False
    verify_closure_fixture(args)
    result = deterministic_result(facts_raw, facts, run_raw, receipt_raw)
    schema_raw = bootstrap_read(candidate / "tests/runtime_core_v2/result.schema.json")
    schema = strict_json(schema_raw)
    validate_definition(run_manifest, schema, "run_manifest", "RUN_MANIFEST_SCHEMA")
    validate_definition(facts, schema, "derived_facts", "FACTS_SCHEMA")
    validate_definition(receipt, schema, "matrix_receipt", "RECEIPT_SCHEMA")
    validate_schema(result, schema, "RESULT_SCHEMA")
    seal = args.seal_root.resolve()
    if seal.exists() and any(seal.iterdir()):
        fail("SEAL_NOT_EMPTY", "final seal root must be fresh and empty")
    seal.mkdir(parents=True, exist_ok=True)
    roots = {row["root_id"]: Path(row["absolute_realpath"])
             for row in policy["roots"]}
    git_path = next(item["absolute_realpath"] for item in manifest["tools"]
                    if item["role"] == "git")
    for item in run_manifest["inputs"]:
        data = source_input_bytes(item, roots, candidate, git_path)
        if len(data) != item["bytes"] or sha_bytes(data) != item["sha256"]:
            fail("SEALED_INPUT_CLOSURE", f"input changed: {item['seal_id']}")
        write_tree_file(seal, item["sealed_relative_path"], data)
    write_tree_file(seal, "reviewer/matrix.json", matrix_raw)
    write_tree_file(seal, "reviewer/matrix-receipt.json", receipt_raw)
    for fixture_path in sorted((path for path in fixture_root.rglob("*")
                                if path.is_file()),
                               key=lambda path: path.relative_to(fixture_root).as_posix()):
        write_tree_file(seal, "reviewer/closure-fixture/" +
                        fixture_path.relative_to(fixture_root).as_posix(),
                        bootstrap_read(fixture_path, require_single_link=False))
    for name in ("summary.json", "case-set.json"):
        write_tree_file(seal, "reviewer/" + name,
                        bootstrap_read(args.matrix_root / name))
    for case in receipt["cases"]:
        for name in ("mutation.json", "stdout", "stderr"):
            write_tree_file(seal, f"reviewer/cases/{case['id']}/{name}",
                            bootstrap_read(args.matrix_root / "cases" /
                                           case["id"] / name))
    write_once(seal / "run-manifest.json", run_raw)
    write_once(seal / "derived-facts.json", facts_raw)
    result_raw = canonical(result)
    write_once(seal / "result.json", result_raw)
    paths = sorted((path for path in seal.rglob("*") if path.is_file()),
                   key=lambda path: path.relative_to(seal).as_posix())
    sums = "".join(f"{sha_bytes(path.read_bytes())}  {path.relative_to(seal).as_posix()}\n"
                   for path in paths).encode()
    write_once(seal / "SHA256SUMS", sums)
    verify_final_file_closure(seal)
    print(json.dumps({"c3": "PASS", "review": result["review_verdict"],
                      "result": str(seal / "result.json"),
                      "seal_root_sha256": sha_bytes(sums),
                      "matrix_receipt_sha256": sha_bytes(receipt_raw)},
                     sort_keys=True, separators=(",", ":")))
    return 0


def verify_final_file_closure(seal: Path) -> set[str]:
    sums_raw = bootstrap_read(seal / "SHA256SUMS", 32 * 1024 * 1024)
    rows = sums_raw.decode("utf-8").splitlines()
    seen: set[str] = set()
    for row in rows:
        if not re.fullmatch(r"[0-9a-f]{64}  [^\x00]+", row):
            fail("FINAL_CHECKSUM_FORMAT", "invalid final checksum row")
        digest, relative = row.split("  ", 1)
        clean_relative(relative)
        if relative == "SHA256SUMS" or relative in seen:
            fail("FINAL_CHECKSUM_FORMAT", "duplicate/self checksum row")
        seen.add(relative)
        path = seal / relative
        if not path.is_file() or sha_bytes(secure_read(seal, relative, 268435456,
                                                       require_single_link=False)) != digest:
            fail("FINAL_CHECKSUM_MISMATCH", f"checksum mismatch: {relative}")
    actual = {path.relative_to(seal).as_posix() for path in seal.rglob("*")
              if path.is_file() and path != seal / "SHA256SUMS"}
    if seen != actual or rows != sorted(rows, key=lambda row: row.split("  ", 1)[1]):
        fail("SEALED_INPUT_CLOSURE", "final checksum set is not exact")
    return seen


def verify_final(args: argparse.Namespace) -> int:
    seal_probe = args.seal_root.resolve(strict=True)
    fixture_manifest = seal_probe / "fixture-manifest.json"
    if fixture_manifest.is_file():
        try:
            fixture_value = strict_json(bootstrap_read(fixture_manifest))
        except EvidenceError:
            fixture_value = {}
        if fixture_value.get("fixture_kind") == "CLOSURE_TEST_ONLY":
            fail("FINAL_ACCEPTANCE_FIXTURE_FORBIDDEN",
                 "closure-test fixture cannot be verified as a final seal")
    if not args.expected_seal_root_sha256:
        fail("EXPECTED_SEAL_DIGEST_REQUIRED", "external seal root digest required")
    if not args.expected_matrix_receipt_sha256:
        fail("EXPECTED_MATRIX_RECEIPT_DIGEST_REQUIRED",
             "external reviewer receipt digest required")
    seal = args.seal_root.resolve(strict=True)
    sums_raw = bootstrap_read(seal / "SHA256SUMS", 32 * 1024 * 1024)
    if sha_bytes(sums_raw) != args.expected_seal_root_sha256:
        fail("SEAL_ROOT_DIGEST_MISMATCH", "seal differs from external digest")
    paths = verify_final_file_closure(seal)
    required = {"run-manifest.json", "derived-facts.json", "result.json",
                "reviewer/matrix.json", "reviewer/matrix-receipt.json",
                "reviewer/summary.json", "reviewer/case-set.json"}
    if "reviewer/matrix.json" not in paths:
        fail("MATRIX_BYTES_MISSING", "frozen matrix bytes missing")
    if not required.issubset(paths):
        fail("SEALED_INPUT_CLOSURE", "required final files missing")
    run_raw = secure_read(seal, "run-manifest.json", 268435456,
                          require_single_link=False)
    facts_raw = secure_read(seal, "derived-facts.json", 268435456,
                            require_single_link=False)
    result_raw = secure_read(seal, "result.json", 268435456,
                             require_single_link=False)
    receipt_raw = secure_read(seal, "reviewer/matrix-receipt.json", 268435456,
                              require_single_link=False)
    matrix_raw = secure_read(seal, "reviewer/matrix.json", 268435456,
                             require_single_link=False)
    run_manifest = strict_json(run_raw)
    facts = strict_json(facts_raw)
    result = strict_json(result_raw)
    receipt = strict_json(receipt_raw)
    if not isinstance(receipt, dict) or not RECEIPT_FIELDS.issubset(receipt):
        fail("RECEIPT_REQUIRED_FIELD_MISSING", "receipt required field missing")
    policy_paths = [path for path in paths if path.startswith("sealed/policy/")]
    schema_paths = [path for path in paths if path.startswith("sealed/ci-result-schema/")]
    manifest_paths = [path for path in paths if path.startswith("sealed/producer-manifest/")]
    consumer_paths = [path for path in paths if path.startswith("sealed/ci-consumer/")]
    runner_paths = [path for path in paths if path.startswith(
        "sealed/ci-adversarial-matrix-runner/")]
    if len(policy_paths) != 1 or len(schema_paths) != 1 or \
       len(manifest_paths) != 1 or len(consumer_paths) != 1 or \
       len(runner_paths) != 1:
        fail("SCHEMA_NOT_SEALED", "sealed policy/schema missing")
    policy_raw = secure_read(seal, policy_paths[0], 268435456,
                             require_single_link=False)
    schema_raw = secure_read(seal, schema_paths[0], 268435456,
                             require_single_link=False)
    policy = strict_json(policy_raw)
    schema = strict_json(schema_raw)
    manifest = strict_json(secure_read(seal, manifest_paths[0], 268435456,
                                       require_single_link=False))
    acceptance = policy.get("acceptance_inputs", {})
    if sha_bytes(matrix_raw) != acceptance.get("matrix_sha256"):
        fail("MATRIX_HASH_MISMATCH", "sealed matrix differs from policy")
    if sha_bytes(secure_read(seal, runner_paths[0], 268435456,
                             require_single_link=False)) != acceptance.get("runner_sha256"):
        fail("RUNNER_HASH_MISMATCH", "sealed runner differs from policy")
    if sha_bytes(secure_read(seal, consumer_paths[0], 268435456,
                             require_single_link=False)) != acceptance.get("fact_consumer_sha256"):
        fail("CONSUMER_HASH_MISMATCH", "sealed consumer differs from policy")
    if sha_bytes(schema_raw) != acceptance.get("result_schema_sha256"):
        fail("SCHEMA_HASH_MISMATCH", "sealed result schema differs from policy")
    if manifest.get("policy_id") != policy.get("policy_id") or \
       manifest.get("policy_sha256") != facts.get("policy_sha256"):
        fail("POLICY_BINDING_MISMATCH", "sealed producer policy binding differs")
    if manifest.get("candidate_identity") != facts.get("candidate_identity_live"):
        fail("MANIFEST_CANDIDATE_BINDING_MISMATCH",
             "sealed producer candidate differs from canonical facts")
    expected_gates = set(REQUIRED_PROTOCOL_GATES)
    if not isinstance(result, dict) or set(result.get("protocol_gates", {})) != expected_gates:
        fail("PROTOCOL_GATE_SET_MISMATCH", "final gate set is not exact")
    validate_definition(run_manifest, schema, "run_manifest", "RUN_MANIFEST_SCHEMA")
    validate_definition(facts, schema, "derived_facts", "FACTS_SCHEMA")
    validate_schema(result, schema, "RESULT_SCHEMA")
    if sha_bytes(receipt_raw) != args.expected_matrix_receipt_sha256:
        fail("MATRIX_RECEIPT_DIGEST_MISMATCH", "sealed receipt differs externally")
    if receipt.get("candidate_identity") != facts.get("candidate_identity_live"):
        fail("RECEIPT_CANDIDATE_MISMATCH", "receipt candidate differs")
    if receipt.get("canonical_run_id") != facts.get("run_id"):
        fail("RECEIPT_RUN_ID_MISMATCH", "receipt run differs")
    if receipt.get("policy_id") != facts.get("policy_id") or \
       receipt.get("policy_sha256") != facts.get("policy_sha256"):
        fail("RECEIPT_POLICY_MISMATCH", "receipt policy differs")
    validate_receipt(receipt_raw, receipt, args.expected_matrix_receipt_sha256,
                     policy, facts_raw, facts, run_raw, run_manifest, matrix_raw,
                     seal / "reviewer")
    validate_definition(receipt, schema, "matrix_receipt", "RECEIPT_SCHEMA")
    fixture_root = seal / "reviewer/closure-fixture"
    fixture_binding = receipt["closure_fixture"]
    if not fixture_root.is_dir() or \
       sha_bytes(bootstrap_read(fixture_root / "SHA256SUMS")) != \
       fixture_binding["sha256s_sha256"] or \
       sha_bytes(bootstrap_read(fixture_root / "fixture-manifest.json")) != \
       fixture_binding["fixture_manifest_sha256"]:
        fail("RECEIPT_CLOSURE_FIXTURE_MISMATCH",
             "sealed fixture differs from receipt")
    args.closure_fixture_root = fixture_root
    args.expected_closure_fixture_sha256 = fixture_binding["sha256s_sha256"]
    args.expected_review_session_id = receipt["review_session_id"]
    args.expected_canonical_run_id = facts["run_id"]
    args.expected_candidate_head = facts["candidate_identity_live"]["commit"]
    args.expected_candidate_tree = facts["candidate_identity_live"]["tree"]
    args.expected_candidate_parent = facts["candidate_identity_live"]["first_parent"]
    args.expected_fixture_policy_id = facts["policy_id"]
    args.expected_fixture_policy_sha256 = facts["policy_sha256"]
    args.expected_run_manifest_sha256 = sha_bytes(run_raw)
    args.expected_derived_facts_sha256 = sha_bytes(facts_raw)
    args.fixture_consumption_state = None
    args.consume_closure_fixture = False
    verify_closure_fixture(args)
    expected = deterministic_result(facts_raw, facts, run_raw, receipt_raw)
    if result.get("candidate_identity") != facts.get("candidate_identity_live"):
        fail("RESULT_CANDIDATE_BINDING_MISMATCH", "result candidate differs")
    if result.get("run_id") != facts.get("run_id") or \
       result.get("policy_id") != facts.get("policy_id") or \
       result.get("policy_sha256") != facts.get("policy_sha256") or \
       result.get("run_manifest_sha256") != sha_bytes(run_raw):
        fail("RESULT_MANIFEST_BINDING_MISMATCH", "result manifest binding differs")
    if result.get("product_verdicts") != REQUIRED_PRODUCT_BASELINE:
        fail("PRODUCT_VERDICT_MISMATCH", "product verdict differs from facts")
    if result.get("failure_codes") != REQUIRED_FAILURE_CODES:
        fail("PRODUCT_FAILURE_CODE_MISMATCH", "failure codes differ from oracle")
    if result.get("review_verdict") == "ACCEPT_C3_EVIDENCE_PROTOCOL" and \
       any(value != "PASS" for value in result["protocol_gates"].values()):
        fail("FINAL_REVIEW_INCONSISTENT", "ACCEPT has a non-PASS gate")
    if result_raw != canonical(expected):
        fail("FINAL_RESULT_DERIVATION_MISMATCH", "result differs from replay")
    print(json.dumps({"verify_seal": "PASS",
                      "seal_root_sha256": sha_bytes(sums_raw),
                      "matrix_receipt_sha256": sha_bytes(receipt_raw),
                      "review": expected["review_verdict"]},
                     sort_keys=True, separators=(",", ":")))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--derive", action="store_true")
    result.add_argument("--finalize", action="store_true")
    result.add_argument("--matrix-evaluate", action="store_true")
    result.add_argument("--case-evaluate", action="store_true")
    result.add_argument("--verify-matrix-seal", action="store_true")
    result.add_argument("--verify-closure-fixture", action="store_true")
    result.add_argument("--verify-seal", action="store_true")
    result.add_argument("--seal-root", type=Path, required=True)
    result.add_argument("--facts-root", type=Path)
    result.add_argument("--expected-facts-sha256")
    result.add_argument("--matrix", type=Path)
    result.add_argument("--expected-matrix-sha256")
    result.add_argument("--matrix-root", type=Path)
    result.add_argument("--matrix-receipt", type=Path)
    result.add_argument("--expected-matrix-receipt-sha256")
    result.add_argument("--expected-seal-root-sha256")
    result.add_argument("--candidate-root", type=Path)
    result.add_argument("--evidence-root", type=Path)
    result.add_argument("--policy", type=Path)
    result.add_argument("--expected-policy-sha256")
    result.add_argument("--test-rename-artifact", default="")
    result.add_argument("--closure-fixture-root", type=Path)
    result.add_argument("--expected-closure-fixture-sha256")
    result.add_argument("--expected-review-session-id")
    result.add_argument("--expected-canonical-run-id")
    result.add_argument("--expected-candidate-head")
    result.add_argument("--expected-candidate-tree")
    result.add_argument("--expected-candidate-parent")
    result.add_argument("--expected-fixture-policy-id")
    result.add_argument("--expected-fixture-policy-sha256")
    result.add_argument("--expected-run-manifest-sha256")
    result.add_argument("--expected-derived-facts-sha256")
    result.add_argument("--fixture-consumption-state", type=Path)
    result.add_argument("--consume-closure-fixture", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.verify_closure_fixture:
            required = (args.closure_fixture_root,
                        args.expected_closure_fixture_sha256,
                        args.expected_review_session_id,
                        args.expected_canonical_run_id,
                        args.expected_candidate_head, args.expected_candidate_tree,
                        args.expected_candidate_parent,
                        args.expected_fixture_policy_id,
                        args.expected_fixture_policy_sha256,
                        args.expected_run_manifest_sha256,
                        args.expected_derived_facts_sha256)
            if not all(required):
                fail("CLI_REQUIRED_ARGUMENT", "closure fixture arguments missing")
            return verify_closure_fixture(args)
        if args.finalize:
            required = (args.candidate_root, args.facts_root, args.policy,
                        args.expected_policy_sha256, args.matrix,
                        args.expected_matrix_sha256, args.matrix_root)
            if not all(required):
                fail("CLI_REQUIRED_ARGUMENT", "finalize arguments missing")
            return finalize(args)
        if args.verify_matrix_seal:
            _, result = verify_checksums(args.seal_root.resolve(strict=True))
            if result["review_verdict"] != "ACCEPT_C3_EVIDENCE_PROTOCOL":
                fail("FINAL_REVIEW_REJECTED", "sealed result is not accepted")
            print(json.dumps({"verify_matrix_seal": "PASS",
                "sha256s_sha256": sha_bytes(
                    (args.seal_root / "SHA256SUMS").read_bytes())},
                sort_keys=True, separators=(",", ":")))
            return 0
        if args.verify_seal:
            return verify_final(args)
        if not all((args.candidate_root, args.evidence_root, args.policy,
                    args.expected_policy_sha256)):
            fail("CLI_REQUIRED_ARGUMENT", "normal mode arguments missing")
        if args.derive and not args.facts_root:
            fail("CLI_REQUIRED_ARGUMENT", "derive requires --facts-root")
        if args.matrix_evaluate:
            fail("CANONICAL_SEAL_RESERVED_EMPTY",
                 "legacy pre-matrix seal evaluator is disabled")
        if not args.derive and not args.case_evaluate:
            fail("CLI_REQUIRED_ARGUMENT", "select --derive or --case-evaluate")
        return consume(args)
    except EvidenceError as error:
        payload = {"c3": "FAIL" if error.code in {
            "SANITIZER_PRODUCT_FAILURE", "RH10_OUTER_PROVENANCE_FALSE"}
            else "NOT_PROVEN",
            "gate": "FAIL" if error.code in {
                "SANITIZER_PRODUCT_FAILURE", "RH10_OUTER_PROVENANCE_FALSE"}
            else "NOT_PROVEN",
            "product": "FAIL" if error.code in {
                "SANITIZER_PRODUCT_FAILURE", "RH10_OUTER_PROVENANCE_FALSE"}
            else "NOT_PROVEN",
            "review": "REJECT_C3_EVIDENCE_PROTOCOL",
            "failure_code": error.code, "detail": str(error)}
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")),
              file=sys.stderr)
        return 2
    except Exception as error:
        print(json.dumps({"c3": "NOT_PROVEN", "gate": "NOT_PROVEN",
            "product": "NOT_PROVEN", "review": "REJECT_C3_EVIDENCE_PROTOCOL",
            "failure_code": "UNEXPECTED_CONSUMER_ERROR", "detail": repr(error)},
            sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
