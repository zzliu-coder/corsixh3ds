#!/usr/bin/env python3
"""Sole executable Python authority for Runtime Core verification.

The shell wrapper only creates or rechecks the locked environment and starts
this fixed file.  Worker modules are loaded from this verified source closure
and receive a private, in-memory VerifiedInvocation instance.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import pathlib
import re
import site
import stat
import subprocess
import sys
import tempfile
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


EXIT_REJECTED = 2
EXIT_CLI = 64
LOCK_SHA256 = "0bec73ce08a019ea3b7a78429f75d03e074d25c0599c8e5a770f25cbbe93bf37"
BASE_COMMIT = "8e9df167da524c2a8bdc3296227544d559dc70dc"
BASE_TREE = "a38772f45c5a2e33c3f082cd34c93185ce26e9f8"
REJECTED_CANDIDATE = "0637cc8d64a3152ae27bee344806ae9aec58592b"
AUTHORITY_KEY = "e0_r11_validation_change_authority"
DEPENDENCIES = {
    "attrs": "25.3.0",
    "jsonschema": "4.25.1",
    "jsonschema-specifications": "2025.9.1",
    "referencing": "0.36.2",
    "rpds-py": "0.27.1",
    "typing-extensions": "4.14.1",
}
FORBIDDEN_ENV = (
    "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "PYTHONSTARTUP",
    "PYTHONINSPECT", "VIRTUAL_ENV", "CTH3DS_VERIFIER_CANONICAL",
    "CTH3DS_VERIFIER_LOCK_SHA256", "CTH3DS_VERIFIER_PYTHON_DISPATCH",
)
SOURCE_FILES = {
    "wrapper": "scripts/run_verifier_python.sh",
    "driver": "scripts/verifier_driver.py",
    "producer": "scripts/verify_runtime_core_v2.py",
    "consumer": "scripts/consume_runtime_core_v2.py",
    "runner": "tests/runtime_core_v2/evidence_protocol_adversarial.py",
    "review_policy_schema": "tests/runtime_core_v2/review-policy.schema.json",
    "result_schema": "tests/runtime_core_v2/result.schema.json",
    "manifest_schema": "tests/runtime_core_v2/evidence-manifest.schema.json",
    "observation_schema": "tests/runtime_core_v2/observation.schema.json",
    "generator": "tests/runtime_core_v2/generate_no_level_fixture.py",
    "integrator": "tools/integrate_corsixth.py",
    "embed_platform": "tools/embed_platform_lua.py",
    "host_python_runner": "scripts/run_host_python_suite.py",
    "host_python_manifest": "tests/host-python-suite.json",
    "lock": "requirements/verifier.lock",
    "bundle_builder": "scripts/build_verifier_input_bundle.py",
    "bundle_schema": "tests/runtime_core_v2/input-bundle.schema.json",
    "wheelhouse_manifest": "requirements/verifier-wheelhouse-manifest.json",
}
PUBLIC_VERBS = ("check-env", "protocol-self-test", "fresh-chain")
INTERNAL_VERBS = (
    "_host-unittest", "_case-evaluate",
    "_closure-verify", "_finalize-probe", "_seal-verify-probe",
    "_fresh-probe",
)
_SENTINEL = object()

CONTENT_DETERMINISTIC = "CONTENT_DETERMINISTIC"
CANONICAL_SEMANTIC = "CANONICAL_SEMANTIC"
RUN_PROVENANCE = "RUN_PROVENANCE"
EVIDENCE_PROJECTION_VERSION = "cth3ds.evidence-canonical-projection/v1"
EVIDENCE_FIELD_CLASSES = {
    "validation.r8_receipt": CONTENT_DETERMINISTIC,
    "validation.candidate_tree": CONTENT_DETERMINISTIC,
    "validation.candidate_tracked_fingerprint_v3": CONTENT_DETERMINISTIC,
    "validation.product_fingerprint": CONTENT_DETERMINISTIC,
    "validation.selected_python_ids": CONTENT_DETERMINISTIC,
    "validation.old3ds_devkitarm_cross_build.three_dsx_sha256": CONTENT_DETERMINISTIC,
    "validation.input_bundle": CONTENT_DETERMINISTIC,
    "validation.authority_suite.python_3_9_25.log_sha256": CANONICAL_SEMANTIC,
    "validation.authority_suite.python_3_14_6.log_sha256": CANONICAL_SEMANTIC,
    "validation.host_python_suites.python_3_9_25.receipt_sha256": CANONICAL_SEMANTIC,
    "validation.host_python_suites.python_3_14_6.receipt_sha256": CANONICAL_SEMANTIC,
    "validation.protocol_self_test.verified_invocation_sha256": RUN_PROVENANCE,
    "validation.protocol_self_test.result_sha256": CANONICAL_SEMANTIC,
    "validation.linux_four_lane.gcc_debug.summary_sha256": CANONICAL_SEMANTIC,
    "validation.linux_four_lane.gcc_release.summary_sha256": CANONICAL_SEMANTIC,
    "validation.linux_four_lane.gcc_sanitized.summary_sha256": CANONICAL_SEMANTIC,
    "validation.linux_four_lane.clang_debug.summary_sha256": CANONICAL_SEMANTIC,
    "validation.official_fresh_chain.verified_invocation_sha256": RUN_PROVENANCE,
    "validation.official_fresh_chain.receipt_sha256": CANONICAL_SEMANTIC,
    "validation.official_fresh_chain.final_seal_sha256s_sha256": CANONICAL_SEMANTIC,
    "validation.official_fresh_chain.result_file_sha256": CANONICAL_SEMANTIC,
    "validation.official_fresh_chain.derived_facts_sha256": CANONICAL_SEMANTIC,
    "validation.old3ds_devkitarm_cross_build.elf_sha256": CANONICAL_SEMANTIC,
    "validation.old3ds_devkitarm_cross_build.runtime_archive_sha256": CANONICAL_SEMANTIC,
    "validation.old3ds_devkitarm_cross_build.link_proof_sha256": CANONICAL_SEMANTIC,
}
RUN_PROVENANCE_KEYS = {
    "review_session_id", "session_root", "session_root_realpath", "bundle_root",
    "bundle_root_realpath", "verified_invocation_sha256", "recorded_at_utc",
    "started_at", "ended_at", "duration", "duration_seconds", "elapsed",
    "elapsed_seconds", "cwd_realpath", "device", "inode",
}


def evidence_field_class(field: str) -> str:
    try:
        return EVIDENCE_FIELD_CLASSES[field]
    except KeyError as error:
        raise RuntimeError("EVIDENCE_FIELD_UNCLASSIFIED: %s" % field) from error


def require_evidence_field_class(field: str, claimed: str) -> None:
    actual = evidence_field_class(field)
    if claimed != actual:
        raise RuntimeError("EVIDENCE_FIELD_CLASS_MISMATCH: %s claimed=%s actual=%s" %
                           (field, claimed, actual))


def normalize_provenance_string(value: str, roots: Mapping[str, str]) -> str:
    normalized = value
    for token, source in sorted(roots.items(), key=lambda item: len(item[1]), reverse=True):
        if not source or not pathlib.Path(source).is_absolute():
            raise RuntimeError("CANONICAL_ROOT_MAP_INVALID: %s" % token)
        normalized = normalized.replace(source.rstrip("/"), "<%s>" % token)
    normalized = re.sub(r"\b[0-9a-f]{32}\b", "<SESSION_ID>", normalized)
    normalized = re.sub(r"\b\d+(?:\.\d+)?(?:ms|s)\b", "<ELAPSED>", normalized)
    normalized = re.sub(
        r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b",
        "<TIMESTAMP>", normalized)
    return normalized


def canonical_semantic_projection(value: Any,
                                  roots: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        result = {}
        for key in sorted(value):
            if key in RUN_PROVENANCE_KEYS:
                continue
            result[key] = canonical_semantic_projection(value[key], roots)
        return result
    if isinstance(value, list):
        return [canonical_semantic_projection(item, roots) for item in value]
    if isinstance(value, str):
        return normalize_provenance_string(value, roots)
    return value


def canonical_semantic_digest(value: Any, roots: Mapping[str, str]) -> str:
    projection = {"schema": EVIDENCE_PROJECTION_VERSION,
                  "value": canonical_semantic_projection(value, roots)}
    return sha_bytes(canonical(projection))


def compare_evidence(field: str, left: Any, right: Any,
                     left_roots: Mapping[str, str],
                     right_roots: Mapping[str, str]) -> Dict[str, Any]:
    field_class = evidence_field_class(field)
    raw_left = sha_bytes(canonical(left))
    raw_right = sha_bytes(canonical(right))
    if field_class == CONTENT_DETERMINISTIC:
        equal = raw_left == raw_right
        return {"field": field, "class": field_class, "status": "PASS" if equal else "FAIL",
                "left_raw_sha256": raw_left, "right_raw_sha256": raw_right,
                "canonical_semantic_sha256": None}
    if field_class == RUN_PROVENANCE:
        return {"field": field, "class": field_class, "status": "RECORDED",
                "left_raw_sha256": raw_left, "right_raw_sha256": raw_right,
                "canonical_semantic_sha256": None}
    left_semantic = canonical_semantic_digest(left, left_roots)
    right_semantic = canonical_semantic_digest(right, right_roots)
    return {"field": field, "class": field_class,
            "status": "PASS" if left_semantic == right_semantic else "FAIL",
            "left_raw_sha256": raw_left, "right_raw_sha256": raw_right,
            "left_canonical_semantic_sha256": left_semantic,
            "right_canonical_semantic_sha256": right_semantic,
            "projection_version": EVIDENCE_PROJECTION_VERSION}


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("utf-8")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def authority_path_lines(paths: Sequence[str]) -> bytes:
    return ("\n".join(paths) + "\n").encode("utf-8")


def validate_authority_object(authority: Any) -> Dict[str, Any]:
    required = {
        "schema", "owner", "baseline", "authorized_diff_count",
        "authorized_diff_lines_sha256", "authorized_diff_exact",
        "review_policy_schema_role", "product_boundary", "candidate_constraints",
    }
    if not isinstance(authority, dict) or set(authority) != required:
        raise RuntimeError("VALIDATION_AUTHORITY_OBJECT_INVALID")
    paths = authority["authorized_diff_exact"]
    if not isinstance(paths, list) or not paths or \
            not all(isinstance(item, str) for item in paths):
        raise RuntimeError("VALIDATION_AUTHORITY_PATH_SET_INVALID")
    for item in paths:
        pure = pathlib.PurePosixPath(item)
        if pure.is_absolute() or ".." in pure.parts or item != pure.as_posix():
            raise RuntimeError("VALIDATION_AUTHORITY_PATH_INVALID")
    if paths != sorted(set(paths), key=lambda item: item.encode("utf-8")):
        raise RuntimeError("VALIDATION_AUTHORITY_PATH_SET_INVALID")
    if authority["authorized_diff_count"] != len(paths):
        raise RuntimeError("VALIDATION_AUTHORITY_PATH_COUNT_MISMATCH")
    if authority["authorized_diff_lines_sha256"] != sha_bytes(authority_path_lines(paths)):
        raise RuntimeError("VALIDATION_AUTHORITY_PATH_DIGEST_MISMATCH")
    baseline = authority["baseline"]
    product = authority["product_boundary"]
    if not isinstance(baseline, dict) or set(baseline) != {"commit", "tree"} or \
            not all(re.fullmatch(r"[0-9a-f]{40}", baseline.get(key, ""))
                    for key in ("commit", "tree")):
        raise RuntimeError("VALIDATION_AUTHORITY_BASELINE_INVALID")
    if not isinstance(product, dict) or set(product) != {"entry_count", "sha256"} or \
            not isinstance(product.get("entry_count"), int) or product["entry_count"] < 1 or \
            not re.fullmatch(r"[0-9a-f]{64}", product.get("sha256", "")):
        raise RuntimeError("VALIDATION_AUTHORITY_PRODUCT_INVALID")
    role = authority["review_policy_schema_role"]
    constraints = authority["candidate_constraints"]
    if not isinstance(role, dict) or set(role) != {
            "json_pointer", "required_keywords", "forbidden_keywords"} or \
            not isinstance(constraints, dict) or set(constraints) != {
            "sole_parent", "clean", "repair_commits"}:
        raise RuntimeError("VALIDATION_AUTHORITY_CONTRACT_INVALID")
    return json.loads(canonical(authority))


def authority_binding_from_dag_bytes(dag_raw: bytes) -> Dict[str, Any]:
    try:
        dag = json.loads(dag_raw.decode("utf-8"))
    except Exception as error:
        raise RuntimeError("VALIDATION_AUTHORITY_DAG_INVALID") from error
    if not isinstance(dag, dict) or AUTHORITY_KEY not in dag:
        raise RuntimeError("VALIDATION_AUTHORITY_MISSING")
    authority = validate_authority_object(dag[AUTHORITY_KEY])
    return {
        "schema": "cth3ds.validation-authority-projection/v1",
        "dag_input_role": "execution_dag",
        "dag_input_sha256": sha_bytes(dag_raw),
        "dag_authority_json_pointer": "/" + AUTHORITY_KEY,
        "authority_canonical_sha256": sha_bytes(canonical(authority)),
        "authorized_diff_count": authority["authorized_diff_count"],
        "authorized_diff_lines_sha256": authority["authorized_diff_lines_sha256"],
        "authorized_diff_exact": authority["authorized_diff_exact"],
        "projection": authority,
    }


def validate_authority_binding(binding: Any, dag_raw: bytes) -> Dict[str, Any]:
    if not isinstance(binding, dict) or \
            binding.get("dag_input_sha256") != sha_bytes(dag_raw):
        raise RuntimeError("VALIDATION_AUTHORITY_DAG_HASH_MISMATCH")
    expected = authority_binding_from_dag_bytes(dag_raw)
    if binding != expected:
        raise RuntimeError("VALIDATION_AUTHORITY_BUNDLE_PROJECTION_MISMATCH")
    return expected


def pointer_get(value: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise RuntimeError("VALIDATION_AUTHORITY_POINTER_INVALID")
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise RuntimeError("VALIDATION_AUTHORITY_POINTER_INVALID")
        current = current[token]
    return current


def validate_schema_role(schema: Any, authority: Mapping[str, Any]) -> None:
    role = authority["review_policy_schema_role"]
    node = pointer_get(schema, role["json_pointer"])
    missing = set(role["required_keywords"]) - set(node) if isinstance(node, dict) else set()
    forbidden = set(role["forbidden_keywords"]) & set(node) if isinstance(node, dict) else set()
    if not isinstance(node, dict) or missing or forbidden or node.get("type") != "array" or \
            not isinstance(node.get("items"), dict) or node["items"].get("type") != "string" or \
            node.get("uniqueItems") is not True:
        raise RuntimeError("VALIDATION_AUTHORITY_SCHEMA_ROLE_MISMATCH")


def verify_policy_authority_projection(authority: Mapping[str, Any],
                                       policy: Mapping[str, Any]) -> None:
    if policy.get("validation_change_authority") != authority:
        raise RuntimeError("VALIDATION_AUTHORITY_POLICY_PROJECTION_MISMATCH")
    if policy.get("product_boundary", {}).get("allowlist_exact") != \
            authority["authorized_diff_exact"]:
        raise RuntimeError("VALIDATION_AUTHORITY_PRODUCER_PROJECTION_MISMATCH")


def bundle_tree_digest(root: pathlib.Path) -> Tuple[str, int]:
    root = root.absolute()
    resolved_root = root.resolve(strict=True)
    rows: List[Dict[str, Any]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = pathlib.Path(current)
        for name in sorted([*directories, *files], key=lambda item: item.encode("utf-8")):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                if os.path.isabs(target):
                    raise RuntimeError("BUNDLE_ABSOLUTE_SYMLINK: %s" % relative)
                resolved = (path.parent / target).resolve(strict=True)
                try:
                    resolved.relative_to(resolved_root)
                except ValueError as error:
                    raise RuntimeError("BUNDLE_SYMLINK_ESCAPE: %s" % relative) from error
                # Symlink permission bits are not semantic and differ by host
                # (Darwin commonly reports 0755; Linux reports 0777).  Match
                # the bundle producer's portable canonical representation.
                rows.append({"path": relative, "kind": "symlink", "target": target,
                             "mode": "0777"})
                if name in directories:
                    directories.remove(name)
            elif stat.S_ISDIR(info.st_mode):
                rows.append({"path": relative, "kind": "directory",
                             "mode": "%04o" % stat.S_IMODE(info.st_mode)})
            elif stat.S_ISREG(info.st_mode):
                rows.append({"path": relative, "kind": "file", "bytes": info.st_size,
                             "sha256": sha_file(path),
                             "mode": "%04o" % stat.S_IMODE(info.st_mode)})
            else:
                raise RuntimeError("BUNDLE_SPECIAL_FILE: %s" % relative)
    rows.sort(key=lambda row: row["path"].encode("utf-8"))
    return sha_bytes(canonical(rows)), len(rows)


class BundleGuard:
    """Resolve and re-hash immutable inputs without consulting provenance."""

    def __init__(self, root: pathlib.Path) -> None:
        lexical = root.absolute()
        if lexical.is_symlink() or not lexical.is_dir():
            raise RuntimeError("INPUT_BUNDLE_ROOT_INVALID")
        self.root = lexical.resolve(strict=True)
        self.manifest_path = self.root / "manifest.json"
        self.sums_path = self.root / "SHA256SUMS"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        schema_path = pathlib.Path(__file__).resolve().parents[1] / \
            SOURCE_FILES["bundle_schema"]
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        import jsonschema
        jsonschema.Draft202012Validator(schema).validate(self.manifest)
        self.inputs = {row["role"]: row for row in self.manifest["inputs"]}
        if len(self.inputs) != len(self.manifest["inputs"]):
            raise RuntimeError("INPUT_BUNDLE_DUPLICATE_ROLE")
        self._verify_global_modes_and_links()
        self.verify("bundle-open", tuple(self.inputs))
        self._verify_sums()
        self.authority_binding = self._verify_validation_authority()

    def _confined(self, relative: str) -> pathlib.Path:
        candidate = pathlib.PurePosixPath(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RuntimeError("INPUT_BUNDLE_RELATIVE_PATH_INVALID: %s" % relative)
        path = self.root / pathlib.Path(*candidate.parts)
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise RuntimeError("INPUT_BUNDLE_REALPATH_ESCAPE: %s" % relative) from error
        return path

    def _verify_global_modes_and_links(self) -> None:
        roots = [self.root]
        for current, directories, files in os.walk(self.root, topdown=True,
                                                   followlinks=False):
            current_path = pathlib.Path(current)
            if current_path != self.root:
                roots.append(current_path)
            for name in list(directories):
                path = current_path / name
                if path.is_symlink():
                    self._confined(path.relative_to(self.root).as_posix())
                    directories.remove(name)
            for name in files:
                path = current_path / name
                relative = path.relative_to(self.root).as_posix()
                if path.is_symlink():
                    self._confined(relative)
                elif stat.S_IMODE(path.stat().st_mode) != 0o444:
                    raise RuntimeError("INPUT_BUNDLE_FILE_MODE_INVALID: %s" % relative)
        for path in roots:
            if not path.is_symlink() and stat.S_IMODE(path.stat().st_mode) != 0o555:
                raise RuntimeError("INPUT_BUNDLE_DIRECTORY_MODE_INVALID: %s" % path)

    def _verify_sums(self) -> None:
        for line in self.sums_path.read_text(encoding="utf-8").splitlines():
            try:
                expected, relative = line.split("  ", 1)
            except ValueError as error:
                raise RuntimeError("INPUT_BUNDLE_SHA256SUMS_INVALID") from error
            path = self._confined(relative)
            if not path.is_file() or sha_file(path) != expected:
                raise RuntimeError("INPUT_BUNDLE_SHA256SUMS_MISMATCH: %s" % relative)

    def _verify_validation_authority(self) -> Dict[str, Any]:
        binding = self.manifest.get("validation_change_authority")
        dag_item = self.inputs.get("execution_dag")
        if not isinstance(binding, dict) or dag_item is None or \
                binding.get("dag_input_sha256") != dag_item.get("sha256_or_tree_digest"):
            raise RuntimeError("VALIDATION_AUTHORITY_DAG_HASH_MISMATCH")
        dag_path = self._confined(dag_item["bundle_relative_path"])
        dag_raw = dag_path.read_bytes()
        if sha_bytes(dag_raw) != binding.get("dag_input_sha256"):
            raise RuntimeError("VALIDATION_AUTHORITY_DAG_HASH_MISMATCH")
        expected = validate_authority_binding(binding, dag_raw)
        identity = self.manifest.get("candidate_identity", {})
        if identity.get("parents") != [binding["projection"]["baseline"]["commit"]]:
            raise RuntimeError("VALIDATION_AUTHORITY_CANDIDATE_BINDING_MISMATCH")
        candidate_bundle = self._confined(
            self.inputs["candidate_transport"]["bundle_relative_path"])
        process = subprocess.run(
            ["/usr/bin/git", "bundle", "list-heads", str(candidate_bundle)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"})
        heads = process.stdout.decode("utf-8", errors="strict").splitlines()
        if process.returncode != 0 or heads != [str(identity.get("head")) + " HEAD"]:
            raise RuntimeError("CANDIDATE_BUNDLE_REFSET_INVALID")
        return expected

    def path(self, role: str) -> pathlib.Path:
        if role not in self.inputs:
            raise RuntimeError("INPUT_BUNDLE_ROLE_MISSING: %s" % role)
        return self._confined(self.inputs[role]["bundle_relative_path"])

    def verify(self, stage: str, roles: Iterable[str]) -> Dict[str, Any]:
        checked = []
        for role in roles:
            item = self.inputs.get(role)
            if item is None:
                raise RuntimeError("INPUT_BUNDLE_ROLE_MISSING: %s" % role)
            path = self._confined(item["bundle_relative_path"])
            if item["kind"] == "file":
                actual = sha_file(path)
                count = path.stat().st_size
            else:
                actual, count = bundle_tree_digest(path)
            if actual != item["sha256_or_tree_digest"]:
                raise RuntimeError("INPUT_BUNDLE_HASH_MISMATCH: %s" % role)
            if count != item["byte_size_or_tree_entry_count"]:
                raise RuntimeError("INPUT_BUNDLE_SIZE_MISMATCH: %s" % role)
            checked.append({"role": role, "bundle_relative_path":
                            item["bundle_relative_path"], "sha256_or_tree_digest": actual})
        return {"schema": "cth3ds.bundle-stage-rehash/v1", "stage": stage,
                "bundle_root": str(self.root), "checked": checked,
                "manifest_sha256": sha_file(self.manifest_path),
                "sha256sums_sha256": sha_file(self.sums_path)}


def metadata(path: pathlib.Path) -> Dict[str, Any]:
    lexical = path.absolute()
    resolved = lexical.resolve(strict=True)
    info = lexical.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError("SOURCE_NOT_REGULAR: %s" % lexical)
    return {
        "path": str(lexical), "realpath": str(resolved),
        "device": info.st_dev, "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode), "nlink": info.st_nlink,
        "bytes": info.st_size, "sha256": sha_file(resolved),
    }


def run_git_bytes(repo: pathlib.Path, *args: str) -> bytes:
    safe_repo = repo.resolve(strict=True)
    result = subprocess.run(
        ["/usr/bin/git", "-c", "safe.directory=" + str(safe_repo),
         "-C", str(safe_repo), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
    )
    if result.returncode != 0:
        raise RuntimeError("GIT_IDENTITY_FAILED: %s" % result.stderr.decode(errors="replace"))
    return result.stdout


def run_git(repo: pathlib.Path, *args: str) -> str:
    return run_git_bytes(repo, *args).decode("utf-8", errors="strict").strip()


def installed_dependencies(env_root: pathlib.Path) -> List[Dict[str, Any]]:
    rows = []
    root = env_root.resolve(strict=True)
    for name, expected in sorted(DEPENDENCIES.items()):
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise RuntimeError("DEPENDENCY_MISSING: %s" % name) from error
        if distribution.version != expected:
            raise RuntimeError(
                "DEPENDENCY_VERSION_MISMATCH: %s=%s expected=%s" %
                (name, distribution.version, expected))
        files = []
        for entry in distribution.files or ():
            relative = pathlib.PurePosixPath(str(entry))
            if relative.suffix == ".pyc" or "__pycache__" in relative.parts:
                continue
            path = pathlib.Path(distribution.locate_file(entry)).resolve(strict=True)
            try:
                env_relative = path.relative_to(root).as_posix()
            except ValueError as error:
                raise RuntimeError("DEPENDENCY_PATH_ESCAPE: %s" % path) from error
            if not path.is_file():
                raise RuntimeError("DEPENDENCY_FILE_NOT_REGULAR: %s" % path)
            files.append({"path": env_relative, "bytes": path.stat().st_size,
                          "sha256": sha_file(path)})
        files.sort(key=lambda row: row["path"].encode("utf-8"))
        rows.append({
            "name": name, "version": expected, "file_count": len(files),
            "installed_files_sha256": sha_bytes(canonical(files)),
        })
    return rows


def tracked_closure(repo: pathlib.Path) -> Dict[str, Any]:
    raw = run_git_bytes(repo, "ls-files", "-s", "-z")
    entries = raw.split(b"\0")
    return {"algorithm": "git-ls-files-stage-z-sha256/v1",
            "entry_count": sum(bool(item) for item in entries),
            "sha256": sha_bytes(raw)}


def marker_basis(repo: pathlib.Path, env_root: pathlib.Path) -> Dict[str, Any]:
    lock = repo / "requirements/verifier.lock"
    driver = repo / "scripts/verifier_driver.py"
    wrapper = repo / "scripts/run_verifier_python.sh"
    dispatch = env_root / "bin/cth3ds-verifier-python"
    venv_cfg = env_root / "pyvenv.cfg"
    bundled_cfg = env_root / ".cth3ds-bundled-runtime.json"
    cfg = venv_cfg if venv_cfg.is_file() else bundled_cfg
    if not cfg.is_file() or cfg.is_symlink():
        raise RuntimeError("RUNTIME_CONFIGURATION_MISSING")
    exe = pathlib.Path(sys.executable).absolute()
    implementation = exe.resolve(strict=True)
    dispatch_info = dispatch.lstat()
    return {
        "schema": "cth3ds.verifier-environment-marker-basis/v2",
        "environment_realpath": str(env_root.resolve(strict=True)),
        "lock": {"path": str(lock.resolve(strict=True)), "sha256": sha_file(lock)},
        "driver": {"path": str(driver.absolute()),
                   "realpath": str(driver.resolve(strict=True)),
                   "sha256": sha_file(driver)},
        "wrapper": {"path": str(wrapper.resolve(strict=True)),
                    "sha256": sha_file(wrapper)},
        "dispatch": {
            "path": str(dispatch.absolute()), "realpath": str(dispatch.resolve(strict=True)),
            "sha256": sha_file(dispatch), "device": dispatch_info.st_dev,
            "inode": dispatch_info.st_ino, "mode": stat.S_IMODE(dispatch_info.st_mode),
            "nlink": dispatch_info.st_nlink, "bytes": dispatch_info.st_size,
        },
        "python": {
            "executable": str(exe), "implementation_realpath": str(implementation),
            "sha256": sha_file(implementation), "version": sys.version,
            "cache_tag": sys.implementation.cache_tag,
            "prefix": str(pathlib.Path(sys.prefix).resolve(strict=True)),
            "base_prefix": str(pathlib.Path(sys.base_prefix).resolve(strict=True)),
            "isolated": sys.flags.isolated,
            "user_site_enabled": bool(site.ENABLE_USER_SITE),
        },
        "runtime_configuration": {"path": str(cfg.absolute()),
                                  "kind": "venv" if cfg == venv_cfg else "bundled-runtime",
                                  "sha256": sha_file(cfg)},
        "dependencies": installed_dependencies(env_root),
    }


class VerifiedAuthorityProjection:
    __slots__ = ("_record", "_binding", "_sentinel")

    def __init__(self, record: Mapping[str, Any], binding: Mapping[str, Any],
                 sentinel: object) -> None:
        if sentinel is not _SENTINEL:
            raise TypeError("VerifiedAuthorityProjection is driver-owned")
        self._record = json.loads(canonical(record))
        self._binding = json.loads(canonical(binding))
        self._sentinel = sentinel


class VerifiedInvocation:
    __slots__ = ("_record", "_digest", "_sentinel")

    def __init__(self, record: Mapping[str, Any], sentinel: object) -> None:
        if sentinel is not _SENTINEL:
            raise TypeError("VerifiedInvocation is constructed only by audit_invocation")
        self._record = dict(record)
        self._digest = sha_bytes(canonical(self._record))
        self._sentinel = sentinel

    @property
    def record(self) -> Dict[str, Any]:
        return json.loads(canonical(self._record))

    @property
    def digest(self) -> str:
        return self._digest

    @property
    def repo(self) -> pathlib.Path:
        return pathlib.Path(self._record["repository"]["realpath"])

    @property
    def driver(self) -> pathlib.Path:
        return pathlib.Path(self._record["source_closure"]["driver"]["path"])

    @property
    def python(self) -> pathlib.Path:
        return pathlib.Path(self._record["python"]["executable"])

    def input_bundle(self, root: pathlib.Path) -> BundleGuard:
        self.require(("fresh-chain", "_fresh-probe"))
        return BundleGuard(root)

    def validation_authority(self, guard: BundleGuard) -> VerifiedAuthorityProjection:
        self.require(("fresh-chain", "_fresh-probe"))
        if not isinstance(guard, BundleGuard):
            raise RuntimeError("VALIDATION_AUTHORITY_BUNDLE_GUARD_REQUIRED")
        return VerifiedAuthorityProjection(
            guard.authority_binding["projection"], guard.authority_binding, _SENTINEL)

    def require_validation_authority(self, value: Any) -> Dict[str, Any]:
        self.require(("fresh-chain", "_fresh-probe"))
        if not isinstance(value, VerifiedAuthorityProjection) or \
                value._sentinel is not _SENTINEL:
            raise RuntimeError("VALIDATION_AUTHORITY_VERIFIED_PROJECTION_REQUIRED")
        return json.loads(canonical(value._record))

    def validation_authority_binding(self, value: Any) -> Dict[str, Any]:
        self.require_validation_authority(value)
        return json.loads(canonical(value._binding))

    def verify_candidate_authority(self, value: Any,
                                   repo: pathlib.Path) -> Dict[str, Any]:
        authority = self.require_validation_authority(value)
        repo = repo.resolve(strict=True)
        head = run_git(repo, "rev-parse", "HEAD^{commit}")
        parents = run_git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
        baseline = authority["baseline"]
        if parents != [baseline["commit"]] or \
                run_git(repo, "rev-parse", baseline["commit"] + "^{tree}") != baseline["tree"]:
            raise RuntimeError("CANDIDATE_PARENT_MISMATCH")
        if run_git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("CANDIDATE_DIRTY")
        rows = run_git(repo, "diff", "--name-status", "--no-renames",
                       baseline["commit"], head, "--").splitlines()
        if any(not row.startswith(("A\t", "M\t")) for row in rows):
            raise RuntimeError("VALIDATION_AUTHORITY_DIFF_MODE_MISMATCH")
        paths = sorted((row.split("\t", 1)[1] for row in rows),
                       key=lambda item: item.encode("utf-8"))
        if paths != authority["authorized_diff_exact"]:
            raise RuntimeError("VALIDATION_AUTHORITY_DIFF_SET_MISMATCH")
        if sha_bytes(authority_path_lines(paths)) != \
                authority["authorized_diff_lines_sha256"]:
            raise RuntimeError("VALIDATION_AUTHORITY_PATH_DIGEST_MISMATCH")
        schema = json.loads((repo / SOURCE_FILES["review_policy_schema"]).read_text(
            encoding="utf-8"))
        validate_schema_role(schema, authority)
        return {"head": head, "parents": parents, "diff_paths": paths,
                "diff_lines_sha256": authority["authorized_diff_lines_sha256"]}

    def verify_policy_authority(self, value: Any,
                                policy: Mapping[str, Any]) -> None:
        authority = self.require_validation_authority(value)
        verify_policy_authority_projection(authority, policy)

    def compare_evidence(self, field: str, left: Any, right: Any,
                         left_roots: Mapping[str, str],
                         right_roots: Mapping[str, str]) -> Dict[str, Any]:
        self.require(("protocol-self-test", "fresh-chain", "_fresh-probe"))
        return compare_evidence(field, left, right, left_roots, right_roots)

    def require_evidence_class(self, field: str, claimed: str) -> None:
        self.require(("protocol-self-test", "fresh-chain", "_fresh-probe"))
        require_evidence_field_class(field, claimed)

    def evidence_contract(self) -> Dict[str, Any]:
        self.require(("protocol-self-test", "fresh-chain", "_fresh-probe"))
        return {"schema": "cth3ds.evidence-field-classification/v1",
                "projection_version": EVIDENCE_PROJECTION_VERSION,
                "classes": dict(sorted(EVIDENCE_FIELD_CLASSES.items()))}

    def require(self, operations: Iterable[str]) -> None:
        if self._sentinel is not _SENTINEL:
            raise RuntimeError("VERIFIED_INVOCATION_INVALID")
        if self._record["operation"] not in set(operations):
            raise RuntimeError("VERIFIED_INVOCATION_OPERATION_FORBIDDEN")

    def child_command(self, verb: str, args: Sequence[str]) -> List[str]:
        if verb not in INTERNAL_VERBS:
            raise RuntimeError("INTERNAL_VERB_NOT_ALLOWLISTED")
        if any(item in ("-c", "-m", "--") for item in args):
            raise RuntimeError("INTERNAL_ARGUMENT_SHAPE_FORBIDDEN")
        evidence = self.repo / "artifacts/verification/verifier-python/internal"
        return [str(self.python), "-I", str(self.driver), "--evidence-dir",
                str(evidence), verb, *list(args)]

    def validate_child_command(self, command: Sequence[str], verb: str,
                               args: Sequence[str]) -> None:
        if list(command) != self.child_command(verb, args):
            raise RuntimeError("INTERNAL_CHILD_COMMAND_MISMATCH")


def audit_invocation(operation: str) -> VerifiedInvocation:
    driver_lexical = pathlib.Path(sys.argv[0]).absolute()
    driver_real = pathlib.Path(__file__).resolve(strict=True)
    repo = driver_real.parents[1]
    if driver_lexical.resolve(strict=True) != driver_real:
        raise RuntimeError("DRIVER_PATH_MISMATCH")
    env_root = pathlib.Path(sys.prefix).resolve(strict=True)
    expected_executable = (env_root / "bin/python").absolute()
    if pathlib.Path(sys.executable).absolute() != expected_executable:
        raise RuntimeError("PYTHON_LEXICAL_PATH_MISMATCH")
    bundled_cfg = env_root / ".cth3ds-bundled-runtime.json"
    is_bundled_runtime = bundled_cfg.is_file() and not bundled_cfg.is_symlink()
    if (not is_bundled_runtime and sys.prefix == sys.base_prefix) or not sys.flags.isolated:
        raise RuntimeError("PREFIX_OR_ISOLATION_MISMATCH")
    if is_bundled_runtime:
        try:
            pathlib.Path(sys.base_prefix).resolve(strict=True).relative_to(env_root)
            for value in sys.path:
                if value:
                    pathlib.Path(value).resolve().relative_to(env_root)
        except ValueError as exc:
            raise RuntimeError("BUNDLED_RUNTIME_PATH_ESCAPE") from exc
    if site.ENABLE_USER_SITE:
        raise RuntimeError("USER_SITE_ENABLED")
    present = [name for name in FORBIDDEN_ENV if name in os.environ]
    if present:
        raise RuntimeError("FORBIDDEN_PYTHON_ENV: %s" % ",".join(present))
    lock = repo / "requirements/verifier.lock"
    if sha_file(lock) != LOCK_SHA256:
        raise RuntimeError("LOCK_DIGEST_MISMATCH")
    dispatch = env_root / "bin/cth3ds-verifier-python"
    info = dispatch.lstat()
    if not stat.S_ISREG(info.st_mode) or dispatch.is_symlink() or info.st_nlink != 1:
        raise RuntimeError("DISPATCH_SHAPE_MISMATCH")
    marker = env_root / ".cth3ds-verifier-environment.json"
    if not marker.is_file() or marker.is_symlink():
        raise RuntimeError("PREFIX_OR_MARKER_MISMATCH")
    marker_bytes = marker.read_bytes()
    recorded_basis = json.loads(marker_bytes.decode("utf-8"))
    canonical_marker = (json.dumps(recorded_basis, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if marker_bytes != canonical_marker:
        raise RuntimeError("MARKER_BYTE_CANONICALIZATION_MISMATCH")
    current_basis = marker_basis(repo, env_root)
    if recorded_basis != current_basis:
        raise RuntimeError("MARKER_OR_INSTALLED_FILE_MISMATCH")
    head = run_git(repo, "rev-parse", "HEAD^{commit}")
    tree = run_git(repo, "rev-parse", "HEAD^{tree}")
    parents = run_git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    baseline_commit = run_git(repo, "rev-parse", "%s^{commit}" % BASE_COMMIT)
    baseline_tree = run_git(repo, "rev-parse", "%s^{tree}" % BASE_COMMIT)
    if baseline_commit != BASE_COMMIT:
        raise RuntimeError("BASELINE_COMMIT_MISMATCH")
    if baseline_tree != BASE_TREE:
        raise RuntimeError("BASELINE_TREE_MISMATCH")
    status_text = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if status_text:
        raise RuntimeError("EXECUTING_REPOSITORY_NOT_CLEAN")
    ancestry = run_git(repo, "rev-list", "HEAD").splitlines()
    if REJECTED_CANDIDATE in ancestry:
        raise RuntimeError("REJECTED_CANDIDATE_IN_ANCESTRY")
    sources = {role: metadata(repo / relative)
               for role, relative in sorted(SOURCE_FILES.items())}
    sys_path = [str(pathlib.Path(value).resolve()) if value else value
                for value in sys.path]
    python_lexical = pathlib.Path(sys.executable).absolute()
    python_lstat = python_lexical.lstat()
    python_implementation = python_lexical.resolve(strict=True)
    implementation_stat = python_implementation.stat()
    record = {
        "schema": "cth3ds.verified-invocation/v1",
        "security_scope": "fail-closed official flow; no same-process hostile-code claim",
        "operation": operation, "invocation_id": uuid.uuid4().hex,
        "repository": {
            "path": str(repo.absolute()), "realpath": str(repo.resolve(strict=True)),
            "clean": True, "head": head, "tree": tree, "parents": parents,
            "tracked_closure": tracked_closure(repo),
        },
        "baseline_identity": {"commit": baseline_commit, "tree": baseline_tree},
        "source_closure": sources,
        "python": {
            "executable": str(python_lexical),
            "lexical_lstat_type": ("symlink" if stat.S_ISLNK(python_lstat.st_mode)
                                    else "regular" if stat.S_ISREG(python_lstat.st_mode)
                                    else "other"),
            "lexical_device": python_lstat.st_dev, "lexical_inode": python_lstat.st_ino,
            "implementation_realpath": str(python_implementation),
            "implementation_device": implementation_stat.st_dev,
            "implementation_inode": implementation_stat.st_ino,
            "implementation_bytes": implementation_stat.st_size,
            "implementation_sha256": sha_file(python_implementation),
            "version": sys.version, "cache_tag": sys.implementation.cache_tag,
            "prefix": str(env_root),
            "base_prefix": str(pathlib.Path(sys.base_prefix).resolve(strict=True)),
            "isolated": sys.flags.isolated, "user_site_enabled": bool(site.ENABLE_USER_SITE),
            "sys_path": sys_path, "sys_path_sha256": sha_bytes(canonical(sys_path)),
        },
        "environment": {"forbidden_present": [], "python_no_user_site": os.environ.get("PYTHONNOUSERSITE")},
        "venv": {
            "root": str(env_root),
            "environment_kind": "bundled-runtime" if is_bundled_runtime else "venv",
            "runtime_configuration": current_basis["runtime_configuration"],
            "marker": metadata(marker), "dispatch": metadata(dispatch),
        },
        "dependencies": current_basis["dependencies"],
    }
    return VerifiedInvocation(record, _SENTINEL)


class ClosedParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print("CLI_CONTRACT: %s" % message, file=sys.stderr)
        raise SystemExit(EXIT_CLI)


def add_path(parser: argparse.ArgumentParser, name: str, required: bool = True) -> None:
    parser.add_argument(name, type=pathlib.Path, required=required)


def parser() -> ClosedParser:
    root = ClosedParser(allow_abbrev=False, add_help=False)
    root.add_argument("--evidence-dir", type=pathlib.Path, required=True)
    sub = root.add_subparsers(dest="verb", required=True, parser_class=ClosedParser)
    check = sub.add_parser("check-env", allow_abbrev=False, add_help=False)
    protocol = sub.add_parser("protocol-self-test", allow_abbrev=False, add_help=False)
    add_path(protocol, "--session-root")
    add_path(protocol, "--result")
    fresh = sub.add_parser("fresh-chain", allow_abbrev=False, add_help=False)
    add_path(fresh, "--input-bundle")
    fresh.add_argument("--expected-candidate-head", required=True)
    fresh.add_argument("--expected-candidate-tree", required=True)
    add_path(fresh, "--session-root")

    host = sub.add_parser("_host-unittest", allow_abbrev=False, add_help=False)
    add_path(host, "--repo")
    add_path(host, "--output")
    case = sub.add_parser("_case-evaluate", allow_abbrev=False, add_help=False)
    for option in ("--request", "--output"):
        add_path(case, option)
    closure = sub.add_parser("_closure-verify", allow_abbrev=False, add_help=False)
    for option in ("--request", "--output"):
        add_path(closure, option)
    finalize = sub.add_parser("_finalize-probe", allow_abbrev=False, add_help=False)
    for option in ("--request", "--output"):
        add_path(finalize, option)
    seal = sub.add_parser("_seal-verify-probe", allow_abbrev=False, add_help=False)
    for option in ("--request", "--output"):
        add_path(seal, option)
    probe = sub.add_parser("_fresh-probe", allow_abbrev=False, add_help=False)
    for option in ("--request", "--output"):
        add_path(probe, option)
    return root


def reject_argv(argv: Sequence[str]) -> None:
    if not argv or "--" in argv:
        raise SystemExit(EXIT_CLI)
    seen = set()
    value_options = {
        "--evidence-dir", "--session-root", "--result", "--input-bundle",
        "--expected-candidate-head", "--expected-candidate-tree",
        "--repo", "--output", "--tool", "--request",
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("-c", "-m") or token.startswith("--="):
            raise SystemExit(EXIT_CLI)
        if token.startswith("--"):
            if "=" in token:
                raise SystemExit(EXIT_CLI)
            if token in seen:
                raise SystemExit(EXIT_CLI)
            seen.add(token)
            if token not in value_options:
                raise SystemExit(EXIT_CLI)
            index += 2
        else:
            index += 1


def load_module(role: str, path: pathlib.Path):
    name = "cth3ds_verified_%s" % role
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("SOURCE_IMPORT_FAILED: %s" % role)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: pathlib.Path, value: Any, require_absent: bool = True) -> None:
    path = path.absolute()
    if require_absent and path.exists():
        raise RuntimeError("AUTHORITATIVE_OUTPUT_PREEXISTS")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".%s." % path.name,
                                              dir=str(path.parent))
    temp_path = pathlib.Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical(value)); handle.flush(); os.fsync(handle.fileno())
        reread = json.loads(temp_path.read_text(encoding="utf-8"))
        if reread != value:
            raise RuntimeError("AUTHORITATIVE_OUTPUT_REREAD_MISMATCH")
        os.replace(str(temp_path), str(path))
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_environment_audit(evidence: pathlib.Path, invocation: Optional[VerifiedInvocation],
                            error: Optional[BaseException] = None) -> None:
    evidence.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "cth3ds.verifier-environment-audit/v2",
        "scope": "ENVIRONMENT_ONLY",
        "status": "PASS" if error is None else "FAIL",
        "verified_invocation": invocation.record if invocation else None,
        "verified_invocation_sha256": invocation.digest if invocation else None,
        "failure_code": None if error is None else str(error).split(":", 1)[0],
        "detail": None if error is None else str(error),
        "recorded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    target = evidence / "environment-audit.json"
    atomic_json(target, payload, require_absent=False)


def validate_hex(value: str, length: int, label: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        raise RuntimeError("%s_INVALID" % label)


def run_protocol(invocation: VerifiedInvocation, args: argparse.Namespace) -> int:
    invocation.require(("protocol-self-test",))
    if args.result.exists():
        raise RuntimeError("AUTHORITATIVE_OUTPUT_PREEXISTS")
    runner = load_module("runner", invocation.repo / SOURCE_FILES["runner"])
    producer = load_module("producer", invocation.repo / SOURCE_FILES["producer"])
    consumer = load_module("consumer", invocation.repo / SOURCE_FILES["consumer"])
    with tempfile.TemporaryDirectory(prefix="cth3ds-protocol-result-",
                                     dir=str(args.result.absolute().parent)) as temporary:
        temp_result = pathlib.Path(temporary) / "result.json"
        code = runner.protocol_self_test_closed(
            invocation, producer, consumer, args.session_root, temp_result)
        if code != 0:
            raise RuntimeError("PROTOCOL_SELF_TEST_FAILED")
        result = json.loads(temp_result.read_text(encoding="utf-8"))
        counts = {key: result.get(key) for key in ("total", "passed", "failed", "skipped")}
        if counts != {"total": 33, "passed": 33, "failed": 0, "skipped": 0}:
            raise RuntimeError("PROTOCOL_SELF_TEST_COUNT_MISMATCH")
        if result.get("verified_invocation_sha256") != invocation.digest:
            raise RuntimeError("VERIFIED_INVOCATION_BINDING_MISMATCH")
        atomic_json(args.result, result)
    return 0


def require_fresh_candidate_identity(invocation: VerifiedInvocation,
                                     args: argparse.Namespace) -> None:
    if args.expected_candidate_head != invocation.record["repository"]["head"] or \
       args.expected_candidate_tree != invocation.record["repository"]["tree"]:
        raise RuntimeError("EXECUTING_CANDIDATE_IDENTITY_MISMATCH")
    parents = invocation.record["repository"]["parents"]
    if parents != [BASE_COMMIT]:
        raise RuntimeError("CANDIDATE_PARENT_MISMATCH")
    parent_tree = run_git(invocation.repo, "rev-parse", "%s^{tree}" % parents[0])
    if parent_tree != BASE_TREE:
        raise RuntimeError("CANDIDATE_PARENT_TREE_MISMATCH")


def run_fresh(invocation: VerifiedInvocation, args: argparse.Namespace) -> int:
    invocation.require(("fresh-chain",))
    validate_hex(args.expected_candidate_head, 40, "CANDIDATE_HEAD")
    validate_hex(args.expected_candidate_tree, 40, "CANDIDATE_TREE")
    require_fresh_candidate_identity(invocation, args)
    guard = invocation.input_bundle(args.input_bundle)
    manifest_identity = guard.manifest["candidate_identity"]
    if manifest_identity["head"] != args.expected_candidate_head or \
            manifest_identity["tree"] != args.expected_candidate_tree or \
            manifest_identity["parents"] != [BASE_COMMIT]:
        raise RuntimeError("INPUT_BUNDLE_CANDIDATE_IDENTITY_MISMATCH")
    authority = invocation.validation_authority(guard)
    invocation.verify_candidate_authority(authority, invocation.repo)
    runner = load_module("runner", invocation.repo / SOURCE_FILES["runner"])
    producer = load_module("producer", invocation.repo / SOURCE_FILES["producer"])
    consumer = load_module("consumer", invocation.repo / SOURCE_FILES["consumer"])
    request = {
        "bundle_root": guard.root,
        "expected_candidate_head": args.expected_candidate_head,
        "expected_candidate_tree": args.expected_candidate_tree,
        "session_root": args.session_root,
        "_validation_change_authority": authority,
    }
    code = runner.fresh_chain_closed(invocation, producer, consumer, request)
    if code != 0:
        failure_path = args.session_root / "00-preflight/durable-failure.json"
        if not failure_path.is_file():
            raise RuntimeError("DURABLE_FRESH_FAILURE_MISSING")
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        raise RuntimeError("%s: stage=%s role=%s bundle=%s errno=%s detail=%s" % (
            failure.get("failure_code", "FRESH_CHAIN_FAILURE"),
            failure.get("stage"), failure.get("input_role"),
            failure.get("bundle_root"), failure.get("errno"), failure.get("detail")))
    result_path = args.session_root / "90-final-audit/fresh-chain-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    required = {
        "initial_entry_count": 0, "semantic_verify": "PASS",
        "construction_self_verification": "PASS",
    }
    if any(result.get(key) != value for key, value in required.items()):
        raise RuntimeError("FRESH_CHAIN_RESULT_MISMATCH")
    for key, expected in (("matrix", (60, 60)), ("base_acceptance", (32, 32)),
                          ("r4_acceptance", (22, 22)),
                          ("composed_acceptance", (54, 54))):
        row = result.get(key, {})
        if (row.get("passed"), row.get("total")) != expected:
            raise RuntimeError("FRESH_CHAIN_COUNT_MISMATCH: %s" % key)
    if result.get("verified_invocation_sha256") != invocation.digest:
        raise RuntimeError("VERIFIED_INVOCATION_BINDING_MISMATCH")
    return 0


def internal_result(invocation: VerifiedInvocation, verb: str,
                    output: pathlib.Path, body: Mapping[str, Any]) -> int:
    payload = {"schema": "cth3ds.verifier-internal-result/v1",
               "scope": "INTERNAL_NON_FINAL", "verb": verb,
               "final_acceptance_eligible": False,
               "verified_invocation_sha256": invocation.digest,
               "body": dict(body)}
    atomic_json(output, payload)
    return 0


def run_internal(invocation: VerifiedInvocation, args: argparse.Namespace) -> int:
    invocation.require((args.verb,))
    if args.verb == "_host-unittest":
        repo = args.repo.resolve(strict=True)
        expected_repo = invocation.record["repository"]
        if run_git(repo, "rev-parse", "HEAD^{commit}") != expected_repo["head"] or \
                run_git(repo, "rev-parse", "HEAD^{tree}") != expected_repo["tree"] or \
                run_git(repo, "status", "--porcelain=v1", "--untracked-files=no"):
            raise RuntimeError("HOST_UNITTEST_REPO_IDENTITY_MISMATCH")
        runner = repo / SOURCE_FILES["host_python_runner"]
        manifest = repo / SOURCE_FILES["host_python_manifest"]
        if sha_file(runner) != invocation.record["source_closure"]["host_python_runner"]["sha256"] or \
                sha_file(manifest) != invocation.record["source_closure"]["host_python_manifest"]["sha256"]:
            raise RuntimeError("HOST_UNITTEST_SOURCE_CLOSURE_MISMATCH")
        suite_output = args.output.with_suffix(args.output.suffix + ".suite.json")
        process = subprocess.run(
            [str(invocation.python), "-I", str(runner),
             "--repo", str(repo), "--manifest", str(manifest),
             "--output", str(suite_output)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        sys.stdout.buffer.write(process.stdout)
        sys.stderr.buffer.write(process.stderr)
        if process.returncode != 0 or not suite_output.is_file():
            raise RuntimeError("HOST_UNITTEST_FAILED")
        summary = json.loads(suite_output.read_text(encoding="utf-8"))
        expected = invocation.record
        if summary.get("verdict") != "PASS" or \
                summary.get("candidate", {}).get("commit") != expected["repository"]["head"] or \
                summary.get("candidate", {}).get("tree") != expected["repository"]["tree"] or \
                summary.get("interpreter", {}).get("implementation_sha256") != expected["python"]["implementation_sha256"] or \
                summary.get("manifest", {}).get("sha256") != expected["source_closure"]["host_python_manifest"]["sha256"]:
            raise RuntimeError("HOST_UNITTEST_RECEIPT_BINDING_MISMATCH")
        return internal_result(invocation, args.verb, args.output, summary)
    request = json.loads(args.request.read_text(encoding="utf-8"))
    if request.get("schema") != "cth3ds.verifier-internal-request/v1":
        raise RuntimeError("INTERNAL_REQUEST_SCHEMA_MISMATCH")
    runner = load_module("runner", invocation.repo / SOURCE_FILES["runner"])
    producer = load_module("producer", invocation.repo / SOURCE_FILES["producer"])
    consumer = load_module("consumer", invocation.repo / SOURCE_FILES["consumer"])
    try:
        body = runner.internal_probe_closed(invocation, producer, consumer,
                                            args.verb, request)
        code = int(body.pop("_exit_code", 0))
        internal_result(invocation, args.verb, args.output, body)
        return code
    except Exception as error:
        failure = getattr(error, "code", "UNEXPECTED_CONSUMER_ERROR")
        product_failure = failure in {
            "SANITIZER_PRODUCT_FAILURE", "RH10_OUTER_PROVENANCE_FALSE"}
        payload = {
            "c3": "FAIL" if product_failure else "NOT_PROVEN",
            "gate": "FAIL" if product_failure else "NOT_PROVEN",
            "product": "FAIL" if product_failure else "NOT_PROVEN",
            "review": "REJECT_C3_EVIDENCE_PROTOCOL",
            "failure_code": failure, "detail": str(error),
        }
        internal_result(invocation, args.verb, args.output, {
            "status": "FAIL", "failure": payload})
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")),
              file=sys.stderr)
        return EXIT_REJECTED


def main(argv: Optional[Sequence[str]] = None) -> int:
    actual = list(sys.argv[1:] if argv is None else argv)
    reject_argv(actual)
    args = parser().parse_args(actual)
    evidence = args.evidence_dir.absolute()
    invocation = None
    try:
        invocation = audit_invocation(args.verb)
        write_environment_audit(evidence, invocation)
        if args.verb == "check-env":
            print(json.dumps({"environment": "PASS", "scope": "ENVIRONMENT_ONLY",
                              "verified_invocation_sha256": invocation.digest}, sort_keys=True))
            return 0
        if args.verb == "protocol-self-test":
            return run_protocol(invocation, args)
        if args.verb == "fresh-chain":
            return run_fresh(invocation, args)
        return run_internal(invocation, args)
    except SystemExit:
        raise
    except Exception as error:
        try:
            write_environment_audit(evidence, invocation, error)
        except Exception:
            pass
        print("VERIFIER_REJECTED: %s" % error, file=sys.stderr)
        return EXIT_REJECTED


if __name__ == "__main__":
    raise SystemExit(main())
