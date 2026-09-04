#!/bin/false
# Invoke protocol self-test and Fresh Chain through scripts/run_verifier_python.sh.
"""Run the frozen 60-case C3 adversarial evidence-protocol matrix."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
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

def require_verified_invocation(context: Any, operations: tuple[str, ...]) -> None:
    if context is None or context.__class__.__name__ != "VerifiedInvocation":
        raise RuntimeError("VERIFIED_INVOCATION_REQUIRED")
    context.require(operations)

MATRIX_SHA256 = "8b7cf0d8e3b3702e9aa3c32aff9d1ed3e363ceab52699539251975a61985060f"
BASE_CASES_SHA256 = "45f7bda680a10c159e70ce15b9389eb7cafc419001af542583fdd5353d319d7f"
R4_CASES_SHA256 = "a4a7160e0dc762599d13a4df721d0d156e2daeea6ce6b8b4226c16f3a4d5dc64"
DAG_SHA256 = "e5339faa3d173e8c11f157980b206447987f75727c841cdd2afc0cc5e875df76"
CLOSURE_CASES = {"E48", "E49", "E50", "E51", "E60"}
ACTIVE_JOURNAL: Optional[Path] = None
ACTIVE_INVOCATION: Any = None
ACTIVE_STAGE = "not-started"
ACTIVE_INPUT_ROLE: Optional[str] = None
AUTHORITY_NEGATIVE_CASES = {
    "missing-one": ("r4.n00_validation_authority",
                    {"VALIDATION_AUTHORITY_PATH_COUNT_MISMATCH"}),
    "extra-one": ("r4.n00_validation_authority",
                  {"VALIDATION_AUTHORITY_PATH_COUNT_MISMATCH"}),
    "same-count-replacement": ("r4.n00_validation_authority",
                               {"VALIDATION_AUTHORITY_PATH_DIGEST_MISMATCH"}),
    "schema-cardinality": ("r4.n00_validation_authority",
                           {"VALIDATION_AUTHORITY_SCHEMA_ROLE_MISMATCH"}),
    "producer-projection": ("r4.n10_policy",
                            {"VALIDATION_AUTHORITY_PRODUCER_PROJECTION_MISMATCH"}),
    "builder-projection": ("bundle-construction",
                           {"VALIDATION_AUTHORITY_BUILDER_PROJECTION_MISMATCH"}),
    "old-bd-bundle-replay": ("r4.n00_validation_authority",
                             {"VALIDATION_AUTHORITY_DAG_HASH_MISMATCH"}),
    "candidate-dirty-or-wrong-parent": ("r4.n00_validation_authority",
        {"CANDIDATE_DIRTY", "CANDIDATE_PARENT_MISMATCH"}),
}


def authority_negative_observation(case_id: str, callback,
                                   evidence_root: Path) -> dict[str, Any]:
    if case_id not in AUTHORITY_NEGATIVE_CASES:
        raise RuntimeError("AUTHORITY_NEGATIVE_CASE_UNKNOWN")
    stage, expected_codes = AUTHORITY_NEGATIVE_CASES[case_id]
    try:
        callback()
        exit_code, code = 0, "PASS"
    except Exception as error:
        exit_code = 2
        code = str(error).split(":", 1)[0]
    policy = evidence_root / "10-policy"
    journal = evidence_root / "00-preflight/execution-journal.jsonl"
    passed = exit_code == 2 and code in expected_codes and \
        not policy.exists() and not journal.exists()
    return {"id": case_id, "pass": passed, "earliest_stage": stage,
            "exit_code": exit_code, "failure_code": code,
            "policy_created": policy.exists(), "journal_created": journal.exists()}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def writable(root: Path) -> None:
    for path in root.rglob("*"):
        try:
            mode = 0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644
            path.chmod(mode)
        except FileNotFoundError:
            pass
    root.chmod(0o755)


def replace_prefix(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [replace_prefix(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: replace_prefix(item, old, new)
                for key, item in value.items()}
    return value


def artifact_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["role"]: item for item in manifest["artifacts"]}


def roots(policy: dict[str, Any]) -> dict[str, Path]:
    return {item["root_id"]: Path(item["absolute_realpath"])
            for item in policy["roots"]}


def artifact_path(policy: dict[str, Any], manifest: dict[str, Any],
                  role: str) -> Path:
    item = artifact_map(manifest)[role]
    return roots(policy)[item["root_id"]] / item["relative_path"]


def refresh(policy: dict[str, Any], manifest: dict[str, Any], role: str) -> None:
    item = artifact_map(manifest)[role]
    path = artifact_path(policy, manifest, role)
    data = path.read_bytes()
    item["bytes"] = len(data)
    item["sha256"] = sha(data)


def clone_case(canonical_root: Path, policy_source: Path, case_root: Path,
               candidate: Path, include_seal: bool) -> tuple[dict[str, Any], dict[str, Any], Path]:
    source_policy = load(policy_source)
    old_root = str(canonical_root)
    old_reviewer_root = str(policy_source.parent.resolve(strict=True))
    case_root.mkdir(parents=True)
    case_root = case_root.resolve(strict=True)
    for name in ("evidence_raw", "build_host", "build_red",
                 "source_upstream_snapshot", "source_xbuild_integrated",
                 "build_xbuild"):
        shutil.copytree(canonical_root / name, case_root / name,
                        copy_function=shutil.copy2)
    shutil.copytree(policy_source.parent, case_root / "reviewer_bundle",
                    copy_function=shutil.copy2)
    if include_seal:
        shutil.copytree(canonical_root / "seal", case_root / "seal",
                        copy_function=shutil.copy2)
    else:
        (case_root / "seal").mkdir()
    writable(case_root)
    policy = replace_prefix(source_policy, old_root, str(case_root))
    policy = replace_prefix(policy, old_reviewer_root,
                            str(case_root / "reviewer_bundle"))
    for row in policy["roots"]:
        if row["root_id"] == "candidate":
            row["absolute_realpath"] = str(candidate)
    manifest_path = case_root / "evidence_raw/producer-manifest.json"
    manifest = replace_prefix(load(manifest_path), old_root, str(case_root))
    manifest = replace_prefix(manifest, old_reviewer_root,
                              str(case_root / "reviewer_bundle"))
    trace_path = case_root / "evidence_raw/rh10-open-trace.json"
    trace = replace_prefix(load(trace_path), old_root, str(case_root))
    trace = replace_prefix(trace, old_reviewer_root,
                           str(case_root / "reviewer_bundle"))
    trace_path.write_bytes(canonical(trace))
    trace_role = artifact_map(manifest)["rh10-open-trace"]
    trace_role["bytes"] = len(trace_path.read_bytes())
    trace_role["sha256"] = sha(trace_path.read_bytes())
    policy_path = case_root / "reviewer_bundle/review-policy.json"
    policy_path.write_bytes(canonical(policy))
    manifest["policy_sha256"] = sha(policy_path.read_bytes())
    manifest_path.write_bytes(canonical(manifest))
    return policy, manifest, policy_path


def commit_fixture_mutation(candidate_source: Path, temp: Path,
                            mutator) -> Path:
    clone = temp / "candidate"
    subprocess.run(["git", "clone", "--no-local", str(candidate_source), str(clone)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "checkout", "--detach", candidate_source.name],
                   cwd=clone, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # clone defaults to the source branch HEAD; retain it.
    base = subprocess.run(["git", "rev-parse", "HEAD^"], cwd=clone,
                          check=True, stdout=subprocess.PIPE).stdout.decode().strip()
    mutator(clone)
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(["git", "reset", "--soft", base], cwd=clone, check=True)
    subprocess.run(["git", "-c", "user.name=C3 Matrix",
                    "-c", "user.email=c3-matrix@example.invalid",
                    "commit", "-m", "matrix mutation"],
                   cwd=clone, check=True, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE)
    return clone


def update_candidate_identity(policy: dict[str, Any], manifest: dict[str, Any],
                              candidate: Path, verifier, consumer_module) -> None:
    head = verifier.git(candidate, "rev-parse", "HEAD^{commit}").decode().strip()
    tree = verifier.git(candidate, "rev-parse", "HEAD^{tree}").decode().strip()
    fp, entries = verifier.fingerprint(candidate, head)
    git_path = next(row["absolute_realpath"] for row in manifest["tools"]
                    if row["role"] == "git")
    ancestry = verifier.reviewer_ancestry_commitment(
        consumer_module, candidate, head, git_path)
    policy["candidate_identity"].update({
        "expected_commit": head, "expected_tree": tree,
        "expected_candidate_fingerprint": fp,
        "expected_candidate_entries": entries,
        "ancestry": ancestry,
    })
    manifest["candidate_identity"].update({
        "commit": head, "tree": tree, "tracked_fingerprint_v3": fp,
        "tracked_entries": entries,
    })


def mutate_observation(policy, manifest, role, fn, raw: Optional[bytes] = None):
    path = artifact_path(policy, manifest, role)
    if raw is None:
        value = load(path)
        fn(value)
        path.write_bytes(canonical(value))
    else:
        path.write_bytes(raw)
    refresh(policy, manifest, role)


def mutate(case_id: str, policy: dict[str, Any], manifest: dict[str, Any],
           policy_path: Path, candidate: Path, case_root: Path, verifier,
           consumer_module, temp: Path) -> tuple[Path, Optional[str], Optional[str]]:
    test_hook = None
    pass_hash = None
    artifacts = artifact_map(manifest)
    invocations = {item["role"]: item for item in manifest["invocations"]}
    builds = manifest["builds"]
    tools = manifest["tools"]

    if case_id == "E01":
        mutate_observation(policy, manifest, "rh09-h1-stdout",
                           lambda value: value.update({"status": "PASS"}))
    elif case_id == "E02":
        mutate_observation(policy, manifest, "rh09-h1-stdout",
                           lambda value: value.update({"observations": {}}))
    elif case_id == "E03":
        mutate_observation(policy, manifest, "rh07-h2-stdout",
            lambda value: value["observations"].update(
                {"transaction_generation_residue": 1}))
    elif case_id == "E04":
        path = artifact_path(policy, manifest, "rh09-h1-stdout")
        raw = path.read_bytes().replace(b'"declared_level_count":0',
                                        b'"declared_level_count":NaN', 1)
        mutate_observation(policy, manifest, "rh09-h1-stdout", lambda _: None, raw)
    elif case_id == "E05":
        path = artifact_path(policy, manifest, "rh09-h1-stdout")
        raw = path.read_bytes().replace(
            b'"stage_id":"C3"', b'"stage_id":"C3","stage_id":"C3"', 1)
        mutate_observation(policy, manifest, "rh09-h1-stdout", lambda _: None, raw)
    elif case_id == "E06":
        policy["candidate_identity"]["expected_commit"] = "bad"
    elif case_id == "E07":
        policy["candidate_identity"]["expected_commit"] = "0" * 40
        policy["candidate_identity"]["expected_tree"] = "1" * 40
    elif case_id == "E08":
        policy["candidate_identity"]["expected_candidate_fingerprint"] = "0" * 64
    elif case_id == "E09":
        policy["product_boundary"]["expected_product_fingerprint"] = "0" * 64
    elif case_id == "E10":
        marker = candidate / ".c3-matrix-e10"
        marker.write_text("untracked\n")
        return candidate, str(marker), None
    elif case_id == "E11":
        clone = commit_fixture_mutation(candidate, temp,
            lambda root: (root / "outside-allowlist.txt").write_text("x\n"))
        for row in policy["roots"]:
            if row["root_id"] == "candidate":
                row["absolute_realpath"] = str(clone)
        update_candidate_identity(policy, manifest, clone, verifier, consumer_module)
        candidate = clone
    elif case_id == "E12":
        path = artifact_path(policy, manifest, "xbuild-upstream-snapshot-archive")
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
    elif case_id == "E13":
        path = artifact_path(policy, manifest, "fixture-fresh-bundle-json")
        outside = case_root / "outside-bundle.json"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    elif case_id == "E14":
        invocations["cpp"]["stream_truncated"] = True
    elif case_id == "E15":
        tools[0]["sha256_after"] = "0" * 64
    elif case_id == "E16":
        mutate_observation(policy, manifest, "rh09-h1-stdout",
                           lambda value: value.update({"run_id": "f" * 32}))
    elif case_id == "E17":
        invocations["cpp"]["finished_at"] = "2000-01-01T00:00:00Z"
    elif case_id == "E18":
        path = artifact_path(policy, manifest, "rh09-h1-stderr")
        path.write_text("ERROR: AddressSanitizer: heap-use-after-free\n"
                        "SUMMARY: AddressSanitizer: heap-use-after-free\n")
        refresh(policy, manifest, "rh09-h1-stderr")
        invocations["RH09-H1"]["exit_code"] = 1
    elif case_id == "E19":
        for role in ("h1-binary-nm-stdout", "h2-binary-nm-stdout"):
            path = artifact_path(policy, manifest, role)
            path.write_text("")
            refresh(policy, manifest, role)
    elif case_id == "E20":
        pass
    elif case_id == "E21":
        extra = dict(builds[0])
        extra["build_id"] = "b-extra"
        extra["role"] = "undeclared-build"
        builds.append(extra)
    elif case_id == "E22":
        builds[0]["unknown_nested_key"] = True
    elif case_id == "E23":
        invocations["cpp"]["stdout_artifact_id"] = "a-external-unbound"
    elif case_id == "E24":
        extra = dict(builds[0])
        extra["build_id"] = "b-duplicate"
        builds.append(extra)
    elif case_id == "E25":
        manifest["builds"] = builds[1:]
    elif case_id == "E26":
        extra = dict(tools[0])
        extra["tool_id"] = "t-duplicate"
        tools.append(extra)
    elif case_id == "E27":
        extra = dict(tools[0])
        extra["tool_id"] = "t-extra"
        extra["role"] = "undeclared-tool"
        tools.append(extra)
    elif case_id == "E28":
        manifest["tools"] = tools[1:]
    elif case_id == "E29":
        extra = dict(manifest["artifacts"][0])
        extra["artifact_id"] = "a-duplicate-role"
        manifest["artifacts"].append(extra)
    elif case_id == "E30":
        extra = dict(manifest["artifacts"][0])
        extra.update({"artifact_id": "a-orphan", "role": "undeclared-artifact"})
        extra.pop("canonical_owner", None)
        manifest["artifacts"].append(extra)
    elif case_id == "E31":
        manifest["artifacts"] = [item for item in manifest["artifacts"]
            if item["role"] != "xbuild-upstream-source-tree-manifest"]
    elif case_id == "E32":
        extra = dict(manifest["invocations"][0])
        extra["invocation_id"] = "i-duplicate"
        manifest["invocations"].append(extra)
    elif case_id == "E33":
        extra = dict(manifest["invocations"][0])
        extra["invocation_id"] = "i-extra"
        extra["role"] = "undeclared-invocation"
        manifest["invocations"].append(extra)
    elif case_id == "E34":
        manifest["invocations"] = manifest["invocations"][1:]
    elif case_id == "E35":
        a = invocations["RH09-H1"]["stdout_artifact_id"]
        invocations["RH09-H1"]["stdout_artifact_id"] = \
            invocations["RH07-H2"]["stdout_artifact_id"]
        invocations["RH07-H2"]["stdout_artifact_id"] = a
    elif case_id == "E36":
        target = roots(policy)["source_xbuild_integrated"] / "CMakeLists.txt"
        target.write_bytes(target.read_bytes() + b"\n# matrix tamper\n")
    elif case_id == "E37":
        invocations["simulator"]["output_artifact_ids"][0] = \
            "a-syntactically-valid-missing"
    elif case_id == "E38":
        manifest["artifacts"][1]["canonical_owner"] = \
            dict(manifest["artifacts"][0]["canonical_owner"])
    elif case_id == "E39":
        fresh = roots(policy)["evidence_raw"] / "rh10-fresh"
        outside = case_root / "outside-fresh"
        shutil.move(fresh, outside)
        fresh.symlink_to(outside, target_is_directory=True)
    elif case_id == "E40":
        test_hook = "cpp-stdout"
    elif case_id == "E41":
        clone = temp / "candidate"
        subprocess.run(["git", "clone", "--no-local", str(candidate), str(clone)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        target = clone / "scripts/consume_runtime_core_v2.py"
        target.write_bytes(target.read_bytes() + b"\n# replaced\n")
        for row in policy["roots"]:
            if row["root_id"] == "candidate":
                row["absolute_realpath"] = str(clone)
        candidate = clone
    elif case_id == "E42":
        pass_hash = sha(canonical(policy))
        policy["created_at"] = "2000-01-01T00:00:00Z"
    elif case_id == "E43":
        clone = temp / "candidate"
        subprocess.run(["git", "clone", "--no-local", str(candidate), str(clone)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        target = clone / "tests/runtime_core_v2/observation.schema.json"
        target.write_bytes(target.read_bytes() + b" ")
        for row in policy["roots"]:
            if row["root_id"] == "candidate":
                row["absolute_realpath"] = str(clone)
        candidate = clone
    elif case_id == "E44":
        clone = temp / "candidate"
        subprocess.run(["git", "clone", "--no-local", str(candidate), str(clone)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        target = clone / "docs/runtime-core-v2-red-oracle.md"
        target.write_bytes(target.read_bytes() + b"\nchanged\n")
        for row in policy["roots"]:
            if row["root_id"] == "candidate":
                row["absolute_realpath"] = str(clone)
        candidate = clone
    elif case_id == "E45":
        invocations["ctest"]["stdout_artifact_id"] = "a-missing-ctest-stream"
    elif case_id == "E46":
        invocations["simulator"]["output_artifact_ids"] = \
            invocations["simulator"]["output_artifact_ids"][:-1]
    elif case_id == "E47":
        upstream = roots(policy)["source_upstream_snapshot"]
        (upstream / "matrix-extra.txt").write_text("expanded\n")
        value = verifier.source_tree(upstream, manifest["run_id"],
                                     "upstream-snapshot",
                                     "source_upstream_snapshot")
        path = artifact_path(policy, manifest,
                             "xbuild-upstream-source-tree-manifest")
        path.write_bytes(canonical(value))
        refresh(policy, manifest, "xbuild-upstream-source-tree-manifest")
    elif case_id in {"E48", "E49", "E50", "E51", "E60"}:
        # Closure mutations are applied after cloning a canonical seal.
        seal = roots(policy)["seal"]
        if not (seal / "run-manifest.json").is_file():
            # Preserve a complete 60-row diagnostic when E20 could not create
            # the prerequisite canonical seal. The verifier will fail closed.
            return candidate, None, None
        run = load(seal / "run-manifest.json")
        if case_id == "E48":
            run["inputs"] = [item for item in run["inputs"]
                             if item["seal_id"] != "ci-consumer"]
        elif case_id == "E49":
            run["inputs"] = [item for item in run["inputs"]
                             if item["seal_id"] != "policy"]
        elif case_id == "E50":
            run["inputs"] = [item for item in run["inputs"]
                             if item["seal_id"] != "ci-observation-schema"]
        elif case_id == "E51":
            run["inputs"] = [item for item in run["inputs"]
                             if item["seal_id"] != "ci-red-oracle"]
        if case_id != "E60":
            (seal / "run-manifest.json").write_bytes(canonical(run))
            result = load(seal / "result.json")
            result["run_manifest_sha256"] = sha(
                (seal / "run-manifest.json").read_bytes())
            (seal / "result.json").write_bytes(canonical(result))
            checksum_rows = []
            for path in sorted([p for p in seal.rglob("*")
                                if p.is_file() and p.name != "SHA256SUMS"],
                               key=lambda p: p.relative_to(seal).as_posix()):
                checksum_rows.append(
                    f"{sha(path.read_bytes())}  {path.relative_to(seal).as_posix()}\n")
            (seal / "SHA256SUMS").write_text("".join(checksum_rows))
        else:
            (seal / "result.json").write_bytes(
                (seal / "result.json").read_bytes() + b" ")
    elif case_id == "E52":
        manifest["artifacts"] = [item for item in manifest["artifacts"]
            if item["role"] != "fixture-tracked-fixture-manifest"]
    elif case_id == "E53":
        path = artifact_path(policy, manifest,
                             "fixture-fresh-fixture-manifest")
        path.write_bytes(path.read_bytes() + b" ")
    elif case_id == "E54":
        fixture_relative = \
            "tests/runtime_core_v2/fixtures/no-level/fixture-manifest.json"

        def outer_true(root: Path) -> None:
            path = root / fixture_relative
            value = load(path)
            value["contains_original_theme_hospital_data"] = True
            path.write_bytes(canonical(value))
        clone = commit_fixture_mutation(candidate, temp, outer_true)
        if fixture_relative not in policy["product_boundary"]["allowlist_exact"]:
            policy["product_boundary"]["allowlist_exact"].append(fixture_relative)
        for row in policy["roots"]:
            if row["root_id"] == "candidate":
                row["absolute_realpath"] = str(clone)
        candidate = clone
        tracked_path = clone / "tests/runtime_core_v2/fixtures/no-level/fixture-manifest.json"
        fresh_path = artifact_path(policy, manifest,
                                   "fixture-fresh-fixture-manifest")
        fresh_path.write_bytes(tracked_path.read_bytes())
        artifacts["fixture-tracked-fixture-manifest"]["bytes"] = \
            tracked_path.stat().st_size
        artifacts["fixture-tracked-fixture-manifest"]["sha256"] = \
            sha(tracked_path.read_bytes())
        refresh(policy, manifest, "fixture-fresh-fixture-manifest")
        update_candidate_identity(policy, manifest, clone, verifier, consumer_module)
        digest = verifier.fixture_digest(
            clone / "tests/runtime_core_v2/fixtures/no-level")
        manifest["fixtures"][0]["tracked_directory_digest"] = digest
        manifest["fixtures"][0]["fresh_directory_digest"] = digest
    elif case_id == "E55":
        invocations["cpp"]["argv"].append("--changed")
    elif case_id == "E56":
        invocations["cpp"]["cwd_root_id"] = "build_host"
    elif case_id == "E57":
        invocations["cpp"]["environment_profile_id"] = "python-regression-v1"
    elif case_id == "E58":
        invocations["cpp"]["signal"] = 9
        invocations["cpp"]["exit_code"] = 0
        invocations["cpp"]["timed_out"] = False
    elif case_id == "E59":
        invocations["RH07-H2"]["observation_artifact_id"] = \
            "a-simulator-trace-json"

    policy_path.write_bytes(canonical(policy))
    manifest["policy_sha256"] = sha(policy_path.read_bytes())
    (case_root / "evidence_raw/producer-manifest.json").write_bytes(
        canonical(manifest))
    return candidate, None, pass_hash


def replace_file(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".r3-new")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def update_json(path: Path, mutator) -> dict[str, Any]:
    value = load(path)
    mutator(value)
    replace_file(path, canonical(value))
    return value


def source_input_bytes(item: dict[str, Any], policy: dict[str, Any],
                       candidate: Path) -> bytes:
    root_id = item["root_id"]
    relative = item["relative_path"]
    if root_id == "system":
        return Path(relative).read_bytes()
    if root_id == "candidate_git":
        return subprocess.run(["git", "cat-file", "-p", relative], cwd=candidate,
                              check=True, stdout=subprocess.PIPE).stdout
    root = roots(policy)[root_id]
    return (root / relative).read_bytes()


def prepare_closure_fixture(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-closure-fixture", action="store_true")
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--canonical-facts-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--expected-policy-sha256", required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--expected-matrix-sha256", required=True)
    parser.add_argument("--review-session-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    candidate = args.candidate_root.resolve(strict=True)
    facts_root = args.canonical_facts_root.resolve(strict=True)
    policy_raw = args.policy.resolve(strict=True).read_bytes()
    if sha(policy_raw) != args.expected_policy_sha256:
        raise RuntimeError("policy hash mismatch")
    policy = json.loads(policy_raw)
    if policy.get("fresh_chain", {}).get("review_session_id") != args.review_session_id:
        raise RuntimeError("review session mismatch")
    matrix_raw = args.matrix.resolve(strict=True).read_bytes()
    if sha(matrix_raw) != args.expected_matrix_sha256 or \
       args.expected_matrix_sha256 != MATRIX_SHA256:
        raise RuntimeError("matrix hash mismatch")
    run_raw = (facts_root / "run-manifest.json").read_bytes()
    facts_raw = (facts_root / "derived-facts.json").read_bytes()
    run_manifest = json.loads(run_raw)
    facts = json.loads(facts_raw)
    if facts.get("run_manifest_sha256") != sha(run_raw):
        raise RuntimeError("facts/run manifest mismatch")
    output = args.out.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("closure fixture output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    for item in run_manifest["inputs"]:
        data = source_input_bytes(item, policy, candidate)
        if len(data) != item["bytes"] or sha(data) != item["sha256"]:
            raise RuntimeError("closure source input changed: " + item["seal_id"])
        target = output / item["sealed_relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (output / "run-manifest.json").write_bytes(run_raw)
    (output / "derived-facts.json").write_bytes(facts_raw)
    fixture_id = uuid.uuid4().hex
    fixture_manifest = {
        "schema": "cth3ds.runtime-core-closure-test-fixture-manifest/v1",
        "stage_id": "C3-R5", "fixture_kind": "CLOSURE_TEST_ONLY",
        "fixture_id": fixture_id, "review_session_id": args.review_session_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="microseconds").replace("+00:00", "Z"),
        "canonical_run_id": facts["run_id"],
        "candidate_identity": facts["candidate_identity_live"],
        "policy_id": facts["policy_id"], "policy_sha256": facts["policy_sha256"],
        "producer_manifest_sha256": facts["producer_manifest_sha256"],
        "run_manifest_sha256": sha(run_raw),
        "derived_facts_sha256": sha(facts_raw), "matrix_sha256": MATRIX_SHA256,
        "runner_sha256": sha(Path(__file__).resolve().read_bytes()),
        "fact_consumer_sha256": sha(
            (candidate / "scripts/consume_runtime_core_v2.py").read_bytes()),
        "source_input_count": len(run_manifest["inputs"]),
        "single_use": True, "final_acceptance_eligible": False,
    }
    result = {
        "schema": "cth3ds.runtime-core-closure-test-result/v1",
        "stage_id": "C3-R5", "artifact_kind": "CLOSURE_TEST_ONLY",
        "fixture_id": fixture_id, "review_session_id": args.review_session_id,
        "canonical_run_id": facts["run_id"],
        "candidate_identity": facts["candidate_identity_live"],
        "policy_sha256": facts["policy_sha256"],
        "run_manifest_sha256": sha(run_raw),
        "derived_facts_sha256": sha(facts_raw), "fixture_verdict": "PASS",
        "c3": "NOT_PROVEN", "matrix_gate_status": "NOT_RUN",
        "review_verdict": "REJECT_C3_EVIDENCE_PROTOCOL",
        "final_acceptance_eligible": False, "failure_codes": ["MATRIX_NOT_RUN"],
    }
    (output / "fixture-manifest.json").write_bytes(canonical(fixture_manifest))
    (output / "result.json").write_bytes(canonical(result))
    rows = [f"{sha(path.read_bytes())}  {path.relative_to(output).as_posix()}\n"
            for path in sorted((path for path in output.rglob("*") if path.is_file()),
                               key=lambda path: path.relative_to(output).as_posix())]
    (output / "SHA256SUMS").write_text("".join(rows), encoding="utf-8")
    print(json.dumps({"closure_fixture": "PREPARED", "fixture_id": fixture_id,
                      "sha256s_sha256": sha((output / "SHA256SUMS").read_bytes())},
                     sort_keys=True, separators=(",", ":")))
    return 0


def closure_verify_command(candidate: Path, fixture: Path, digest: str,
                           review_session_id: str, facts: dict[str, Any],
                           run_sha: str, facts_sha: str, policy_sha: str,
                           consume_state: Optional[Path] = None) -> list[str]:
    identity = facts["candidate_identity_live"]
    command = ["IN_PROCESS", str(candidate / "scripts/consume_runtime_core_v2.py"),
        "--verify-closure-fixture", "--seal-root", str(fixture),
        "--closure-fixture-root", str(fixture),
        "--expected-closure-fixture-sha256", digest,
        "--expected-review-session-id", review_session_id,
        "--expected-canonical-run-id", facts["run_id"],
        "--expected-candidate-head", identity["commit"],
        "--expected-candidate-tree", identity["tree"],
        "--expected-candidate-parent", identity["first_parent"],
        "--expected-fixture-policy-id", facts["policy_id"],
        "--expected-fixture-policy-sha256", policy_sha,
        "--expected-run-manifest-sha256", run_sha,
        "--expected-derived-facts-sha256", facts_sha]
    if consume_state is not None:
        command += ["--fixture-consumption-state", str(consume_state),
                    "--consume-closure-fixture"]
    return command


def mutate_closure_fixture(case_id: str, fixture: Path) -> tuple[str, str]:
    run_path = fixture / "run-manifest.json"
    result_path = fixture / "result.json"
    manifest_path = fixture / "fixture-manifest.json"
    if case_id != "E60":
        seal_id = {"E48": "ci-consumer", "E49": "policy",
                   "E50": "ci-observation-schema", "E51": "ci-red-oracle"}[case_id]
        run = load(run_path)
        item = next(item for item in run["inputs"] if item["seal_id"] == seal_id)
        target = fixture / item["sealed_relative_path"]
        target.unlink()
        parent = target.parent
        if not any(parent.iterdir()):
            parent.rmdir()
        run["inputs"] = [row for row in run["inputs"] if row["seal_id"] != seal_id]
        run_path.write_bytes(canonical(run))
        result = load(result_path)
        result["run_manifest_sha256"] = sha(run_path.read_bytes())
        result_path.write_bytes(canonical(result))
        manifest = load(manifest_path)
        manifest["run_manifest_sha256"] = sha(run_path.read_bytes())
        manifest["source_input_count"] = len(run["inputs"])
        manifest_path.write_bytes(canonical(manifest))
        rows = [f"{sha(path.read_bytes())}  {path.relative_to(fixture).as_posix()}\n"
                for path in sorted((path for path in fixture.rglob("*") if path.is_file()
                                    and path.name != "SHA256SUMS"),
                                   key=lambda path: path.relative_to(fixture).as_posix())]
        (fixture / "SHA256SUMS").write_text("".join(rows), encoding="utf-8")
    digest = sha((fixture / "SHA256SUMS").read_bytes())
    run_sha = sha(run_path.read_bytes())
    if case_id == "E60":
        result_path.write_bytes(result_path.read_bytes() + b" ")
    return digest, run_sha


def recompute_final_sums(seal: Path) -> str:
    sums = seal / "SHA256SUMS"
    sums.unlink(missing_ok=True)
    rows = []
    for path in sorted((item for item in seal.rglob("*") if item.is_file()),
                       key=lambda item: item.relative_to(seal).as_posix()):
        rows.append(f"{sha(path.read_bytes())}  {path.relative_to(seal).as_posix()}\n")
    sums.write_text("".join(rows), encoding="utf-8")
    return sha(sums.read_bytes())


def detach_control_files(seal: Path) -> None:
    """Keep large sealed inputs linked; make verifier control files independent."""
    for relative in ("run-manifest.json", "derived-facts.json", "result.json",
                     "SHA256SUMS"):
        path = seal / relative
        replace_file(path, path.read_bytes())
    for path in sorted(item for item in (seal / "reviewer").rglob("*")
                       if item.is_file()):
        replace_file(path, path.read_bytes())


def refresh_receipt_collections(seal: Path, receipt: dict[str, Any],
                                cases: list[dict[str, Any]], total: int,
                                passed: int, failed: int) -> None:
    case_set_path = seal / "reviewer/case-set.json"
    summary_path = seal / "reviewer/summary.json"
    case_set = load(case_set_path)
    summary = load(summary_path)
    case_set["cases"] = cases
    summary["cases"] = cases
    summary["total"] = total
    summary["passed"] = passed
    summary["failed"] = failed
    if "matrix" in summary:
        summary["matrix"].update({"total": total, "passed": passed,
                                  "failed": failed})
    replace_file(case_set_path, canonical(case_set))
    replace_file(summary_path, canonical(summary))
    receipt["cases"] = cases
    receipt["case_count"] = total
    receipt["passed"] = passed
    receipt["failed"] = failed
    if "matrix" in receipt:
        receipt["matrix"].update({"total": total, "passed": passed,
                                  "failed": failed})
    receipt["case_set_sha256"] = sha(case_set_path.read_bytes())
    receipt["summary_sha256"] = sha(summary_path.read_bytes())


def mutate_result_case(case_id: str, seal: Path) -> None:
    receipt_path = seal / "reviewer/matrix-receipt.json"
    result_path = seal / "result.json"
    manifest_path = seal / "sealed/producer-manifest/producer-manifest.json"
    runner_path = seal / (
        "sealed/ci-adversarial-matrix-runner/evidence_protocol_adversarial.py")
    receipt = load(receipt_path)
    if case_id == "R3P03":
        refresh_receipt_collections(seal, receipt, [], 0, 0, 0)
    elif case_id == "R3P04":
        cases = receipt["cases"]
        cases[36]["pass"] = False
        refresh_receipt_collections(seal, receipt, cases, 60, 59, 1)
    elif case_id == "R3P05":
        case_set_path = seal / "reviewer/case-set.json"
        case_set = load(case_set_path)
        case_set["cases"] = [row for row in case_set["cases"] if row["id"] != "E37"]
        replace_file(case_set_path, canonical(case_set))
        receipt["case_set_sha256"] = sha(case_set_path.read_bytes())
    elif case_id == "R3P06":
        cases = receipt["cases"]
        cases[36] = dict(cases[35])
        refresh_receipt_collections(seal, receipt, cases, 60, 60, 0)
    elif case_id == "R3P07":
        receipt["canonical_run_id"] = "f" * 32
    elif case_id == "R3P08":
        receipt["candidate_identity"]["commit"] = "f" * 40
    elif case_id == "R3P09":
        receipt["policy_id"] = "c3-" + "f" * 32
        receipt["policy_sha256"] = "f" * 64
    elif case_id == "R3P10":
        receipt["producer_manifest_sha256"] = "f" * 64
    elif case_id == "R3P11":
        matrix_path = seal / "reviewer/matrix.json"
        replace_file(matrix_path, matrix_path.read_bytes() + b" ")
        receipt["matrix_sha256"] = sha(matrix_path.read_bytes())
    elif case_id == "R3P12":
        replace_file(runner_path, runner_path.read_bytes() + b"\n# drift\n")
        receipt["runner_sha256"] = sha(runner_path.read_bytes())
    elif case_id == "R3P13":
        path = seal / "reviewer/summary.json"
        replace_file(path, path.read_bytes() + b" ")
    elif case_id == "R3P14":
        path = seal / "reviewer/case-set.json"
        replace_file(path, path.read_bytes() + b" ")
    elif case_id == "R3P15":
        path = seal / "reviewer/cases/E12/stderr"
        replace_file(path, path.read_bytes() + b"changed\n")
    elif case_id == "R3P16":
        update_json(result_path, lambda value: value.update(
            {"protocol_gates": {"GIT_TOPOLOGY": "PASS"}}))
    elif case_id == "R3P17":
        def arbitrary(value):
            gates = value["protocol_gates"]
            gates["ARBITRARY_GATE"] = gates.pop("UPSTREAM_SNAPSHOT_BYTES")
        update_json(result_path, arbitrary)
    elif case_id == "R3P18":
        update_json(manifest_path, lambda value: value["candidate_identity"].update(
            {"commit": "f" * 40}))
    elif case_id == "R3P19":
        update_json(result_path, lambda value: value["candidate_identity"].update(
            {"commit": "f" * 40}))
    elif case_id == "R3P20":
        update_json(result_path, lambda value: value.update({"run_id": "f" * 32}))
    elif case_id == "R3P21":
        update_json(result_path, lambda value: value["product_verdicts"].update(
            {"RH09_PRODUCT": "PASS"}))
    elif case_id == "R3P22":
        update_json(result_path, lambda value: value.update(
            {"failure_codes": value["failure_codes"][:1]}))
    elif case_id == "R3P23":
        update_json(result_path, lambda value: value["protocol_gates"].update(
            {"HOST_REGRESSION": "NOT_PROVEN"}))
    elif case_id == "R3P24":
        update_json(result_path, lambda value: value.update(
            {"matrix_receipt_sha256": "f" * 64}))
    elif case_id == "R3P26":
        receipt["passed"] = 59
        receipt["failed"] = 1
    elif case_id == "R3P28":
        update_json(result_path, lambda value: value["candidate_identity"].update(
            {"tree": "f" * 40}))
    elif case_id == "R3P29":
        run_path = seal / "run-manifest.json"
        update_json(run_path, lambda value: value.update({"run_id": "f" * 32}))
        update_json(result_path, lambda value: value.update(
            {"run_manifest_sha256": sha(run_path.read_bytes())}))
    elif case_id == "R3P30":
        (seal / "reviewer/matrix.json").unlink()
    elif case_id == "R3P31":
        update_json(manifest_path, lambda value: value.update(
            {"policy_id": "c3-" + "f" * 32}))
    elif case_id == "R3P32":
        receipt.pop("summary_sha256", None)
    if case_id in {"R3P03", "R3P04", "R3P05", "R3P06", "R3P07", "R3P08",
                   "R3P09", "R3P10", "R3P11", "R3P12", "R3P26", "R3P32"}:
        replace_file(receipt_path, canonical(receipt))


def result_provenance_cases(invocation: Any, consumer_module: Any,
                            argv: list[str]) -> int:
    require_verified_invocation(invocation, ("fresh-chain", "_finalize-probe",
                                              "_seal-verify-probe"))
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--result-provenance-cases", action="store_true")
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--canonical-run-root", type=Path, required=True)
    parser.add_argument("--canonical-facts", type=Path, required=True)
    parser.add_argument("--expected-facts-sha256", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--expected-policy-sha256", required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--expected-matrix-sha256", required=True)
    parser.add_argument("--matrix-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--seal-root", type=Path, required=True)
    parser.add_argument("--expected-seal-sha256", required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--execution-journal", type=Path)
    args = parser.parse_args(argv)
    definitions = load(args.cases)["cases"]
    output = args.out.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("R3 acceptance output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    consumer = args.candidate_root.resolve(strict=True) / "scripts/consume_runtime_core_v2.py"
    base_finalize = ["IN_PROCESS", str(consumer), "--finalize",
        "--candidate-root", str(args.candidate_root), "--facts-root",
        str(args.canonical_facts.parent), "--expected-facts-sha256",
        args.expected_facts_sha256, "--policy", str(args.policy),
        "--expected-policy-sha256", args.expected_policy_sha256,
        "--matrix", str(args.matrix), "--expected-matrix-sha256",
        args.expected_matrix_sha256, "--matrix-root", str(args.matrix_root)]
    results = []
    with tempfile.TemporaryDirectory(
            prefix="cth3ds-r3-provenance-", dir=output.parent) as temporary:
        temp_root = Path(temporary)
        for definition in definitions:
            case_id = definition["id"]
            case_dir = output / case_id
            case_dir.mkdir()
            if case_id in {"R3P02", "R3P25"}:
                command = base_finalize + ["--seal-root", str(temp_root / case_id / "seal")]
                if case_id == "R3P25":
                    command += ["--matrix-receipt", str(args.receipt)]
            else:
                fixture = temp_root / case_id / "seal"
                shutil.copytree(args.seal_root, fixture, copy_function=os.link)
                detach_control_files(fixture)
                if case_id != "R3P01" and case_id != "R3P27":
                    mutate_result_case(case_id, fixture)
                mutated_receipt = fixture / "reviewer/matrix-receipt.json"
                expected_receipt = (args.expected_receipt_sha256
                                    if case_id == "R3P26"
                                    else sha(mutated_receipt.read_bytes()))
                mutated_seal_sha = recompute_final_sums(fixture)
                expected_seal = (args.expected_seal_sha256
                                 if case_id in {"R3P28", "R3P29"}
                                 else mutated_seal_sha)
                command = ["IN_PROCESS", str(consumer), "--verify-seal",
                           "--seal-root", str(fixture),
                           "--expected-matrix-receipt-sha256", expected_receipt]
                if case_id != "R3P27":
                    command += ["--expected-seal-root-sha256", expected_seal]
            started = utc_now()
            if "--finalize" in command:
                process = run_child_probe(invocation, "_finalize-probe", {
                    "schema": "cth3ds.verifier-internal-request/v1",
                    "argv": command[2:]}, case_dir)
            else:
                process = run_child_probe(invocation, "_seal-verify-probe", {
                    "schema": "cth3ds.verifier-internal-request/v1",
                    "argv": command[2:]}, case_dir)
            command = list(process.args)
            (case_dir / "stdout").write_bytes(process.stdout)
            (case_dir / "stderr").write_bytes(process.stderr)
            if args.execution_journal:
                append_journal(args.execution_journal, "r4.n80_base_acceptance.case",
                    ["r4.n70_semantic_verify"], command, started, utc_now(),
                    process.returncode, process.stdout, process.stderr, case_dir)
            payload = None
            lines = process.stderr.decode(errors="replace").strip().splitlines()
            if lines:
                try:
                    payload = json.loads(lines[-1])
                except json.JSONDecodeError:
                    pass
            code = payload.get("failure_code") if payload else None
            passed = (process.returncode == definition["expected_exit"] and
                      code == definition["expected_failure_code"])
            results.append({"id": case_id, "name": definition["name"],
                            "actual_exit": process.returncode,
                            "actual_failure_code": code,
                            "expected_exit": definition["expected_exit"],
                            "expected_failure_code": definition["expected_failure_code"],
                            "pass": passed})
    passed = sum(row["pass"] for row in results)
    summary = {"schema": "cth3ds.runtime-core-r3-acceptance-result/v1",
               "total": len(results), "passed": passed,
               "failed": len(results) - passed, "cases": results}
    (output / "summary.json").write_bytes(canonical(summary))
    print(json.dumps({"passed": passed, "total": len(results),
                      "summary": str(output / "summary.json")},
                     sort_keys=True, separators=(",", ":")))
    return 0 if passed == len(results) else 2


class FreshChainError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="microseconds").replace("+00:00", "Z")


def tree_digest(root: Path) -> str:
    if not root.exists():
        return sha(b"")
    rows = []
    root = root.resolve(strict=True)
    for path in sorted(root.rglob("*"),
                       key=lambda item: item.relative_to(root).as_posix().encode()):
        relative = path.relative_to(root).as_posix()
        if unicodedata.normalize("NFC", relative) != relative:
            raise FreshChainError("SAFE_PATH_INVALID", f"non-NFC path: {relative!r}")
        info = path.lstat()
        mode = oct(stat.S_IMODE(info.st_mode))
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            resolved = path.resolve(strict=True)
            if root not in [resolved, *resolved.parents]:
                raise FreshChainError("XBUILD_INPUT_CLOSURE_MISMATCH",
                                      f"symlink escapes root: {relative}")
            rows.append(f"L\0{mode}\0{relative}\0{target}\n")
        elif stat.S_ISDIR(info.st_mode):
            rows.append(f"D\0{mode}\0{relative}\n")
        elif stat.S_ISREG(info.st_mode):
            rows.append(f"F\0{mode}\0{relative}\0{info.st_size}\0{sha(path.read_bytes())}\n")
        else:
            raise FreshChainError("XBUILD_INPUT_CLOSURE_MISMATCH",
                                  f"unsupported node: {relative}")
    return sha("".join(rows).encode())


def no_symlink_chain(path: Path) -> bool:
    return not any(row["is_symlink"] for row in
                   canonical_path_descriptor("path", path)["existing_ancestors"])


def paths_overlap(left: Path, right: Path) -> bool:
    left_descriptor = canonical_path_descriptor("left", left)
    right_descriptor = canonical_path_descriptor("right", right)
    return path_relation(left_descriptor, right_descriptor) is not None


def _path_contract_error(detail: str) -> FreshChainError:
    return FreshChainError("PATH_CONTRACT_INVALID", detail)


def _case_variant(name: str) -> Optional[str]:
    for index, character in enumerate(name):
        if character.isalpha():
            replacement = character.lower() if character.isupper() else character.upper()
            return name[:index] + replacement + name[index + 1:]
    return None


def _case_insensitive_volume_key(path: Path, resolved: str,
                                 ancestors: list[dict[str, Any]]) -> Optional[str]:
    for row in reversed(ancestors):
        current = Path(row["lexical_absolute_normalized"])
        alias_name = _case_variant(current.name)
        if not alias_name or not current.parent.is_dir():
            continue
        try:
            actual_names = {entry.name for entry in os.scandir(current.parent)}
            alias = current.parent / alias_name
            if alias_name not in actual_names and os.path.lexists(alias) and \
                    os.path.samefile(current, alias):
                return unicodedata.normalize("NFC", resolved).casefold()
        except (FileNotFoundError, NotADirectoryError, OSError):
            continue
    return None


def canonical_path_descriptor(label: str, value: Any,
                              raw_spelling: Optional[str] = None) -> dict[str, Any]:
    try:
        if not isinstance(label, str) or not label:
            raise ValueError("path label must be non-empty")
        if isinstance(value, Path):
            path_text = str(value)
        elif isinstance(value, str):
            path_text = value
        else:
            raise TypeError("path must be a string or Path")
        raw = path_text if raw_spelling is None else raw_spelling
        if not isinstance(raw, str) or not raw or "\x00" in raw or "\x00" in path_text:
            raise ValueError("path spelling is empty or contains NUL")
        lexical_text = os.path.abspath(os.path.normpath(path_text))
        lexical_nfc = unicodedata.normalize("NFC", lexical_text)
        lexical = Path(lexical_nfc)
        if not lexical.is_absolute() or not lexical.anchor:
            raise ValueError("path cannot be normalized as absolute")

        nearest = lexical
        missing_parts: list[str] = []
        while not os.path.lexists(nearest):
            if nearest == nearest.parent:
                raise FileNotFoundError("no existing path prefix")
            missing_parts.insert(0, nearest.name)
            nearest = nearest.parent
        nearest_resolved = nearest.resolve(strict=True)
        resolved = nearest_resolved.joinpath(*missing_parts)
        resolved_text = unicodedata.normalize("NFC", os.path.normpath(str(resolved)))

        ancestors: list[dict[str, Any]] = []
        current = Path(lexical.anchor)
        lexical_parts = lexical.parts[1:]
        candidates = [current]
        for part in lexical_parts:
            current = current / part
            candidates.append(current)
        for candidate in candidates:
            if not os.path.lexists(candidate):
                break
            lstat_value = candidate.lstat()
            is_symlink = stat.S_ISLNK(lstat_value.st_mode)
            resolved_candidate = candidate.resolve(strict=True)
            stat_value = resolved_candidate.stat()
            ancestors.append({
                "lexical_absolute_normalized": str(candidate),
                "resolved": unicodedata.normalize("NFC", str(resolved_candidate)),
                "is_symlink": is_symlink,
                "symlink_target": os.readlink(candidate) if is_symlink else None,
                "lstat_device": lstat_value.st_dev,
                "lstat_inode": lstat_value.st_ino,
                "target_device": stat_value.st_dev,
                "target_inode": stat_value.st_ino,
            })

        full_exists = lexical.exists()
        node = None
        if full_exists:
            node_stat = lexical.stat()
            node_lstat = lexical.lstat()
            node = {"device": node_stat.st_dev, "inode": node_stat.st_ino,
                    "lstat_device": node_lstat.st_dev,
                    "lstat_inode": node_lstat.st_ino,
                    "is_symlink": stat.S_ISLNK(node_lstat.st_mode)}
        nearest_stat = nearest_resolved.stat()
        descriptor = {
            "label": label,
            "raw_spelling": raw,
            "lexical_absolute_normalized": lexical_text,
            "unicode_nfc": lexical_nfc,
            "resolved_existing_prefix": resolved_text,
            "exists": full_exists,
            "node": node,
            "nearest_existing_ancestor": {
                "lexical": str(nearest), "resolved": str(nearest_resolved),
                "device": nearest_stat.st_dev, "inode": nearest_stat.st_ino,
            },
            "existing_ancestors": ancestors,
            "casefold_key": None,
        }
        descriptor["casefold_key"] = _case_insensitive_volume_key(
            lexical, resolved_text, ancestors)
        return descriptor
    except FreshChainError:
        raise
    except Exception as error:
        raise _path_contract_error("%s: %s" % (label, error)) from error


def _bounded_relation(left: str, right: str) -> Optional[str]:
    if left == right:
        return "SAME_PATH"
    separator = os.sep
    left_prefix = left.rstrip(separator) + separator
    right_prefix = right.rstrip(separator) + separator
    if right.startswith(left_prefix):
        return "RIGHT_DESCENDS_FROM_LEFT"
    if left.startswith(right_prefix):
        return "RIGHT_ANCESTOR_OF_LEFT"
    return None


def path_relation(input_descriptor: dict[str, Any],
                  output_descriptor: dict[str, Any]) -> Optional[dict[str, Any]]:
    if any(row["is_symlink"] for row in output_descriptor["existing_ancestors"]):
        return {"subtype": "OUTPUT_SYMLINK_ANCESTOR", "samefile": False}
    samefile = False
    if input_descriptor["exists"] and output_descriptor["exists"]:
        try:
            samefile = os.path.samefile(
                input_descriptor["lexical_absolute_normalized"],
                output_descriptor["lexical_absolute_normalized"])
        except OSError as error:
            raise _path_contract_error("samefile: %s" % error) from error
    if samefile:
        return {"subtype": "SAMEFILE_ALIAS", "samefile": True}
    input_value = input_descriptor["resolved_existing_prefix"]
    output_value = output_descriptor["resolved_existing_prefix"]
    if input_descriptor.get("casefold_key") is not None and \
            output_descriptor.get("casefold_key") is not None:
        input_value = input_descriptor["casefold_key"]
        output_value = output_descriptor["casefold_key"]
    relation = _bounded_relation(input_value, output_value)
    if relation == "SAME_PATH":
        subtype = "RESOLVED_ALIAS"
    elif relation == "RIGHT_DESCENDS_FROM_LEFT":
        subtype = "OUTPUT_DESCENDS_FROM_INPUT"
    elif relation == "RIGHT_ANCESTOR_OF_LEFT":
        subtype = "OUTPUT_ANCESTOR_OF_INPUT"
    else:
        return None
    return {"subtype": subtype, "samefile": samefile}


def fresh_derived_output_paths(session: Path) -> dict[str, Path]:
    relative_paths = (
        "00-preflight", "00-preflight/candidate-head.bundle",
        "00-preflight/bundle-verify.git", "00-preflight/candidate-detached",
        "00-preflight/bundle-rehash", "00-preflight/stage-diagnostics",
        "00-preflight/execution-journal.jsonl", "00-preflight/input-identity.json",
        "00-preflight/path-separation.json", "10-policy", "20-canonical-run",
        "20-canonical-run/evidence_raw", "20-canonical-run/build_host",
        "20-canonical-run/build_red", "20-canonical-run/source_upstream_snapshot",
        "20-canonical-run/source_xbuild_integrated", "20-canonical-run/build_xbuild",
        "20-canonical-run/seal", "30-facts", "40-closure-fixture", "45-anchors",
        "50-matrix", "60-final-seal", "70-verification", "80-acceptance",
        "90-final-audit", "90-final-audit/h2-exact20", "90-final-audit/h2-plain-build",
    )
    return {"session/" + relative: session / relative for relative in relative_paths}


def validate_precreation_paths(input_domains: dict[str, Any],
                               output_domains: dict[str, Any],
                               derived_outputs: Optional[dict[str, Any]] = None,
                               raw_spellings: Optional[dict[str, str]] = None
                               ) -> dict[str, Any]:
    raw_spellings = raw_spellings or {}
    input_descriptors = {name: canonical_path_descriptor(
        name, value, raw_spellings.get(name)) for name, value in sorted(input_domains.items())}
    output_descriptors = {name: canonical_path_descriptor(
        name, value, raw_spellings.get(name)) for name, value in sorted(output_domains.items())}
    derived_descriptors = {name: canonical_path_descriptor(
        name, value, raw_spellings.get(name)) for name, value in
        sorted((derived_outputs or {}).items())}

    for output_name, output_descriptor in output_descriptors.items():
        for input_name, input_descriptor in input_descriptors.items():
            relation = path_relation(input_descriptor, output_descriptor)
            if relation is not None:
                detail = {"subtype": relation["subtype"],
                          "input": input_name, "output": output_name,
                          "samefile": relation["samefile"],
                          "conflicting_realpaths": [
                              input_descriptor["resolved_existing_prefix"],
                              output_descriptor["resolved_existing_prefix"]],
                          "no_stage_started": True}
                raise FreshChainError("INPUT_OUTPUT_OVERLAP",
                                      canonical(detail).decode().strip())
    output_names = sorted(output_descriptors)
    for index, left_name in enumerate(output_names):
        for right_name in output_names[index + 1:]:
            relation = path_relation(output_descriptors[left_name],
                                     output_descriptors[right_name])
            if relation is not None:
                detail = {"subtype": "OUTPUT_OUTPUT_" + relation["subtype"],
                          "input": left_name, "output": right_name,
                          "samefile": relation["samefile"],
                          "conflicting_realpaths": [
                              output_descriptors[left_name]["resolved_existing_prefix"],
                              output_descriptors[right_name]["resolved_existing_prefix"]],
                          "no_stage_started": True}
                raise FreshChainError("INPUT_OUTPUT_OVERLAP",
                                      canonical(detail).decode().strip())

    if output_descriptors:
        owner = output_descriptors[output_names[0]]["resolved_existing_prefix"]
        owner_casefold = output_descriptors[output_names[0]].get("casefold_key")
        for name, descriptor in derived_descriptors.items():
            derived = descriptor["resolved_existing_prefix"]
            if owner_casefold is not None and descriptor.get("casefold_key") is not None:
                derived = descriptor["casefold_key"]
                owner_value = owner_casefold
            else:
                owner_value = owner
            if _bounded_relation(owner_value, derived) not in {
                    "SAME_PATH", "RIGHT_DESCENDS_FROM_LEFT"}:
                raise _path_contract_error("derived output escapes owner: %s" % name)
    return {"schema": "cth3ds.precreation-path-separation/v1", "status": "PASS",
            "inputs": input_descriptors, "outputs": output_descriptors,
            "derived_outputs": derived_descriptors}


def normalize_candidate_transport(kind: str, source: Path, destination: Path,
                                  expected_sha256: Optional[str]) -> dict[str, Any]:
    source = source.resolve(strict=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    bundle = destination.parent / "candidate-head.bundle"
    if kind == "detached-repo":
        status = subprocess.check_output(
            ["/usr/bin/git", "-C", str(source), "status", "--porcelain=v1",
             "--untracked-files=all"])
        if status:
            raise FreshChainError("CANDIDATE_DIRTY", "candidate transport is dirty")
        head = subprocess.check_output(
            ["/usr/bin/git", "-C", str(source), "rev-parse", "HEAD^{commit}"],
            text=True).strip()
        subprocess.run(["/usr/bin/git", "-C", str(source), "bundle", "create",
                        str(bundle), "HEAD"], check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
        source_sha = None
    elif kind == "head-bundle":
        if not expected_sha256 or sha(source.read_bytes()) != expected_sha256:
            raise FreshChainError("CANDIDATE_TRANSPORT_HASH_MISMATCH",
                                  "HEAD bundle bytes differ")
        bundle.write_bytes(source.read_bytes())
        heads = subprocess.check_output(
            ["/usr/bin/git", "bundle", "list-heads", str(bundle)], text=True
        ).splitlines()
        if len(heads) != 1 or not heads[0].endswith(" HEAD"):
            raise FreshChainError("CANDIDATE_TRANSPORT_REFSET_INVALID",
                                  f"advertised refs: {heads}")
        head = heads[0].split()[0]
        source_sha = expected_sha256
    else:
        raise FreshChainError("ANCESTRY_PROOF_MISSING",
                              f"unsupported candidate transport: {kind}")
    verify_repo = destination.parent / "bundle-verify.git"
    subprocess.run(["/usr/bin/git", "init", "-q", "--bare", str(verify_repo)], check=True)
    verify = subprocess.run(["/usr/bin/git", "bundle", "verify", str(bundle)],
                            cwd=verify_repo, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if verify.returncode != 0:
        raise FreshChainError("ANCESTRY_OBJECT_UNREADABLE",
                              verify.stderr.decode(errors="replace"))
    subprocess.run(["/usr/bin/git", "clone", "-q", str(bundle), str(destination)],
                   check=True)
    subprocess.run(["/usr/bin/git", "-C", str(destination), "checkout", "-q",
                    "--detach", head], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(destination), "remote", "remove",
                    "origin"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {"kind": kind, "source_realpath": str(source),
            "source_sha256": source_sha, "normalized_repo_realpath": str(destination),
            "head": head, "bundle_sha256": sha(bundle.read_bytes()),
            "advertised_refs": [{"name": "HEAD", "oid": head}]}


def exact_observed_dag(entries: list[dict[str, Any]],
                       declared: dict[str, Any]) -> dict[str, Any]:
    declared_nodes = {row["id"] if isinstance(row, dict) else row
                      for row in declared["nodes"]}
    declared_edges = {(row["from"], row["to"]) if isinstance(row, dict)
                      else tuple(row) for row in declared["edges"]}
    completed = [row for row in entries
                 if row.get("stage_id") in declared_nodes and row.get("exit_code") == 0]
    ids = [row["stage_id"] for row in completed]
    if len(ids) != len(set(ids)):
        raise FreshChainError("OBSERVED_DAG_INCOMPLETE", "duplicate completed DAG stage")
    observed_nodes = set(ids)
    observed_edges = {(dependency, row["stage_id"]) for row in completed
                      for dependency in row.get("dependency_ids", [])
                      if dependency in declared_nodes}
    indegree = {node: 0 for node in observed_nodes}
    outgoing = {node: set() for node in observed_nodes}
    for left, right in observed_edges:
        if left in observed_nodes and right in observed_nodes:
            outgoing[left].add(right)
            indegree[right] += 1
    queue = sorted(node for node, degree in indegree.items() if degree == 0)
    visited = []
    while queue:
        node = queue.pop(0)
        visited.append(node)
        for target in sorted(outgoing[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
                queue.sort()
    cycle_count = 0 if len(visited) == len(observed_nodes) else 1
    if observed_nodes != declared_nodes or observed_edges != declared_edges or cycle_count:
        raise FreshChainError("OBSERVED_DAG_INCOMPLETE", json.dumps({
            "missing_nodes": sorted(declared_nodes - observed_nodes),
            "extra_nodes": sorted(observed_nodes - declared_nodes),
            "missing_edges": sorted(declared_edges - observed_edges),
            "extra_edges": sorted(observed_edges - declared_edges),
            "cycle_count": cycle_count}, sort_keys=True))
    return {"nodes": sorted(observed_nodes), "edges": sorted(observed_edges),
            "node_count": len(observed_nodes), "edge_count": len(observed_edges),
            "cycle_count": cycle_count}


def append_journal(path: Path, stage_id: str, dependencies: list[str],
                   command: list[str], started: str, ended: str, exit_code: int,
                   stdout: bytes, stderr: bytes, output_root: Optional[Path]) -> None:
    driver_child = len(command) > 2 and command[0] == sys.executable and \
        command[1] == "-I"
    executable = (Path(command[2]) if driver_child else
                  Path(command[0]) if command else Path(__file__))
    executable_sha = sha(executable.read_bytes()) if executable.is_file() else None
    invocation_digest = (ACTIVE_INVOCATION.digest
                         if ACTIVE_INVOCATION is not None else None)
    if output_root is not None:
        internal = output_root / "internal-result.json"
        if internal.is_file():
            try:
                invocation_digest = load(internal)["verified_invocation_sha256"]
            except (KeyError, TypeError, json.JSONDecodeError):
                raise RuntimeError("INTERNAL_RESULT_BINDING_INVALID")
    diagnostics = path.parent / "stage-diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    diagnostic_id = "%s-%s" % (re.sub(r"[^A-Za-z0-9_.-]", "_", stage_id),
                                 uuid.uuid4().hex)
    stdout_path = diagnostics / (diagnostic_id + ".stdout")
    stderr_path = diagnostics / (diagnostic_id + ".stderr")
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    record = {
        "schema": "cth3ds.runtime-core-execution-journal-entry/v1",
        "stage_id": stage_id, "dependency_ids": dependencies,
        "started_at": started, "ended_at": ended,
        "executable_relative_path": (command[2] if driver_child else
                                     str(command[0]) if command else
                                     "tests/runtime_core_v2/evidence_protocol_adversarial.py"),
        "executable_sha256": executable_sha,
        "argument_roles": [item[2:] for item in command if item.startswith("--")],
        "argv": command, "cwd_realpath": str(Path.cwd().resolve()),
        "exit_code": exit_code, "stdout_sha256": sha(stdout),
        "stderr_sha256": sha(stderr),
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
        "owner": "validation-task", "input_role": ACTIVE_INPUT_ROLE,
        "output_root": str(output_root) if output_root else None,
        "output_digest": tree_digest(output_root) if output_root else sha(b""),
        "verified_invocation_sha256": invocation_digest,
        "verified_driver": (str(ACTIVE_INVOCATION.driver)
                            if ACTIVE_INVOCATION is not None else None),
        "verified_driver_sha256": (sha(ACTIVE_INVOCATION.driver.read_bytes())
                                    if ACTIVE_INVOCATION is not None else None),
        "verified_python": (str(ACTIVE_INVOCATION.python)
                            if ACTIVE_INVOCATION is not None else None),
    }
    with path.open("ab") as handle:
        handle.write(canonical(record))


def run_journaled(journal: Path, stage_id: str, dependencies: list[str],
                  command: list[str], output_root: Optional[Path] = None) -> subprocess.CompletedProcess:
    global ACTIVE_STAGE
    ACTIVE_STAGE = stage_id
    started = utc_now()
    environment = child_environment()
    environment.update({"ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                        "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             check=False, cwd=Path.cwd(), env=environment)
    append_journal(journal, stage_id, dependencies, command, started, utc_now(),
                   process.returncode, process.stdout, process.stderr, output_root)
    if process.returncode != 0:
        detail = process.stderr.decode(errors="replace") or process.stdout.decode(errors="replace")
        raise FreshChainError("STAGE_FAILED", f"{stage_id}: {detail}")
    return process


def run_in_process_journaled(journal: Path, stage_id: str, dependencies: list[str],
                             label: str, callback, output_root: Optional[Path] = None):
    global ACTIVE_STAGE
    ACTIVE_STAGE = stage_id
    started = utc_now()
    stdout_text = io.StringIO()
    stderr_text = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_text), contextlib.redirect_stderr(stderr_text):
            code = int(callback() or 0)
    except Exception as error:
        code = 2
        print(repr(error), file=stderr_text)
    stdout = stdout_text.getvalue().encode()
    stderr = stderr_text.getvalue().encode()
    command = [str(ACTIVE_INVOCATION.driver), "in-process:" + label]
    append_journal(journal, stage_id, dependencies, command, started, utc_now(),
                   code, stdout, stderr, output_root)
    if code != 0:
        raise FreshChainError("STAGE_FAILED", "%s: %s" %
                              (stage_id, stderr.decode(errors="replace")))
    return subprocess.CompletedProcess(command, code, stdout, stderr)


def call_closed(command: list[str], callback) -> subprocess.CompletedProcess:
    stdout_text = io.StringIO()
    stderr_text = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_text), contextlib.redirect_stderr(stderr_text):
            code = int(callback() or 0)
    except Exception as error:
        code = 2
        failure = getattr(error, "code", "UNEXPECTED_CONSUMER_ERROR")
        product_failure = failure in {
            "SANITIZER_PRODUCT_FAILURE", "RH10_OUTER_PROVENANCE_FALSE"}
        payload = {"c3": "FAIL" if product_failure else "NOT_PROVEN",
                   "gate": "FAIL" if product_failure else "NOT_PROVEN",
                   "product": "FAIL" if product_failure else "NOT_PROVEN",
                   "review": "REJECT_C3_EVIDENCE_PROTOCOL",
                   "failure_code": failure, "detail": str(error)}
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")),
              file=stderr_text)
    return subprocess.CompletedProcess(command, code, stdout_text.getvalue().encode(),
                                       stderr_text.getvalue().encode())


def child_environment() -> dict[str, str]:
    return {
        "PATH": "/opt/devkitpro/devkitARM/bin:/opt/devkitpro/tools/bin:" +
                os.environ.get(
                    "PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "LC_ALL": "C", "TZ": "UTC", "TMPDIR": tempfile.gettempdir(),
        "DEVKITPRO": "/opt/devkitpro", "DEVKITARM": "/opt/devkitpro/devkitARM",
    }


def run_child_probe(invocation: Any, verb: str, request: dict[str, Any],
                    evidence_root: Path) -> subprocess.CompletedProcess:
    evidence_root.mkdir(parents=True, exist_ok=True)
    request_path = evidence_root / "internal-request.json"
    result_path = evidence_root / "internal-result.json"
    if request_path.exists() or result_path.exists():
        raise RuntimeError("INTERNAL_PROBE_OUTPUT_PREEXISTS")
    request_path.write_bytes(canonical(request))
    child_args = ["--request", str(request_path), "--output", str(result_path)]
    command = invocation.child_command(verb, child_args)
    invocation.validate_child_command(command, verb, child_args)
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             check=False, cwd=Path.cwd(), env=child_environment())
    if not result_path.is_file():
        raise RuntimeError("INTERNAL_PROBE_RESULT_MISSING")
    result = load(result_path)
    if result.get("schema") != "cth3ds.verifier-internal-result/v1" or \
            result.get("scope") != "INTERNAL_NON_FINAL" or \
            result.get("verb") != verb or \
            result.get("final_acceptance_eligible") is not False or \
            not re.fullmatch(r"[0-9a-f]{64}",
                             result.get("verified_invocation_sha256", "")):
        raise RuntimeError("INTERNAL_PROBE_RESULT_INVALID")
    return process


def internal_probe_closed(invocation: Any, producer_module: Any,
                          consumer_module: Any, verb: str,
                          request: dict[str, Any]) -> dict[str, Any]:
    require_verified_invocation(invocation, (verb,))
    if verb == "_fresh-probe":
        if set(request) != {"schema", "fresh_request"} or \
                not isinstance(request["fresh_request"], dict):
            raise RuntimeError("INTERNAL_REQUEST_SHAPE_MISMATCH")
        fresh = dict(request["fresh_request"])
        raw_path_spellings = {}
        for key in ("bundle_root", "session_root", "candidate_input"):
            if key == "candidate_input" and key not in fresh:
                continue
            if not isinstance(fresh.get(key), str):
                raise RuntimeError("INTERNAL_REQUEST_PATH_MISMATCH")
            raw_path_spellings[key] = fresh[key]
            fresh[key] = Path(fresh[key])
        fresh["_raw_path_spellings"] = raw_path_spellings
        code = fresh_chain_closed(invocation, producer_module, consumer_module, fresh)
        return {"status": "PASS" if code == 0 else "FAIL", "_exit_code": code}
    if set(request) != {"schema", "argv"} or \
            not isinstance(request["argv"], list) or \
            not all(isinstance(value, str) for value in request["argv"]):
        raise RuntimeError("INTERNAL_REQUEST_SHAPE_MISMATCH")
    parsed = consumer_module.parser().parse_args(request["argv"])
    if verb == "_case-evaluate":
        code = consumer_module.consume(invocation, parsed)
    elif verb == "_closure-verify":
        code = consumer_module.verify_closure_fixture(parsed)
    elif verb == "_finalize-probe":
        code = consumer_module.finalize(invocation, parsed)
    elif verb == "_seal-verify-probe":
        if parsed.matrix_evaluate:
            consumer_module.fail(
                "CANONICAL_SEAL_RESERVED_EMPTY",
                "legacy pre-matrix seal evaluator is disabled")
        code = consumer_module.verify_final(invocation, parsed)
    else:
        raise RuntimeError("INTERNAL_VERB_NOT_IMPLEMENTED")
    return {"status": "PASS", "_exit_code": int(code or 0)}


def failure_code(process: subprocess.CompletedProcess) -> Optional[str]:
    for raw in reversed(process.stderr.decode(errors="replace").splitlines()):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value.get("failure_code")
    return None


def replace_argument(command: list[str], flag: str, value: str) -> list[str]:
    result = list(command)
    result[result.index(flag) + 1] = value
    return result


def run_r4_acceptance(invocation: Any, producer_module: Any, consumer_module: Any,
                      args: argparse.Namespace, context: dict[str, Any],
                      output: Path) -> dict[str, Any]:
    global ACTIVE_JOURNAL
    ACTIVE_JOURNAL = context["journal"]
    definitions = load(args.cycle_acceptance_cases)["cases"]
    if [row["id"] for row in definitions] != [f"R4C{i:02d}" for i in range(1, 23)]:
        raise FreshChainError("R4_CASE_SET_MISMATCH", "R4 case IDs differ")
    output.mkdir(parents=True, exist_ok=True)
    candidate = context["candidate"]
    fixture = context["fixture"]
    facts = context["facts"]
    base_verify = closure_verify_command(
        candidate, fixture, context["fixture_digest"], context["review_session_id"],
        facts, context["run_sha"], context["facts_sha"], context["policy_sha"])
    observed = {row["id"]: row for row in context["matrix_summary"]["cases"]}
    results: list[dict[str, Any]] = []
    probe_index = 0

    def probe_root() -> Path:
        nonlocal probe_index
        probe_index += 1
        return output / "probes" / ("probe-%03d" % probe_index)

    def expected_consumer(command: list[str], expected_exit: int,
                          expected_code: Optional[str]) -> tuple[bool, dict[str, Any]]:
        parsed = consumer_module.parser().parse_args(command[2:])
        if parsed.verify_closure_fixture:
            verb = "_closure-verify"
        elif parsed.finalize:
            verb = "_finalize-probe"
        elif parsed.verify_seal or parsed.matrix_evaluate:
            verb = "_seal-verify-probe"
        else:
            verb = "_case-evaluate"
        process = run_child_probe(invocation, verb, {
            "schema": "cth3ds.verifier-internal-request/v1",
            "argv": command[2:]}, probe_root())
        code = failure_code(process)
        return (process.returncode == expected_exit and code == expected_code,
                {"actual_exit": process.returncode, "actual_failure_code": code,
                 "stdout_sha256": sha(process.stdout),
                 "stderr_sha256": sha(process.stderr)})

    def expected_fresh(session_root: Path, expected_code: str):
        request = dict(context["fresh_request"])
        request["session_root"] = session_root
        serializable = {key: str(value) if isinstance(value, Path) else value
                        for key, value in request.items()}
        process = run_child_probe(invocation, "_fresh-probe", {
            "schema": "cth3ds.verifier-internal-request/v1",
            "fresh_request": serializable}, probe_root())
        code = failure_code(process)
        return (process.returncode == 2 and code == expected_code,
                {"actual_exit": process.returncode, "actual_failure_code": code,
                 "stdout_sha256": sha(process.stdout),
                 "stderr_sha256": sha(process.stderr)})

    def add(case_id: str, passed: bool, code: str, evidence: Any) -> None:
        case_dir = output / case_id
        case_dir.mkdir()
        payload = {"id": case_id, "pass": bool(passed), "actual_code": code,
                   "evidence": evidence}
        (case_dir / "result.json").write_bytes(canonical(payload))
        results.append(payload)

    preflight = context["preflight"]
    add("R4C01", preflight["initial_entry_count"] == 0,
        "SESSION_ROOT_EMPTY", preflight)
    with tempfile.TemporaryDirectory(prefix="cth3ds-r4-accept-") as temporary:
        temp = Path(temporary)
        nonempty = temp / "nonempty"
        nonempty.mkdir()
        (nonempty / "sentinel").write_text("x", encoding="utf-8")
        ok, ev = expected_fresh(nonempty.resolve(), "SESSION_ROOT_NOT_EMPTY")
        add("R4C02", ok, "SESSION_ROOT_NOT_EMPTY", ev)
    seal_obs = context["seal_observations"]
    add("R4C03", len(seal_obs) == 3 and all(row["entry_count"] == 0 for row in seal_obs),
        "CANONICAL_SEAL_RESERVED_EMPTY", seal_obs)
    fresh_policy = context["policy"]["fresh_chain"]
    add("R4C04", fresh_policy["forbidden_prior_artifact_roles"] ==
        ["facts", "closure_fixture", "matrix_receipt", "final_seal"],
        "NO_PRIOR_RUN_REFERENCE", fresh_policy)
    ok, ev = expected_consumer(base_verify, 0, None)
    add("R4C05", ok, "CLOSURE_FIXTURE_VALID", ev)
    wrong = "f" * 32 if facts["run_id"] != "f" * 32 else "e" * 32
    ok, ev = expected_consumer(replace_argument(base_verify,
        "--expected-canonical-run-id", wrong), 2, "CLOSURE_FIXTURE_RUN_ID_MISMATCH")
    add("R4C06", ok, "CLOSURE_FIXTURE_RUN_ID_MISMATCH", ev)
    wrong40 = "f" * 40 if facts["candidate_identity_live"]["commit"] != "f" * 40 else "e" * 40
    ok, ev = expected_consumer(replace_argument(base_verify,
        "--expected-candidate-head", wrong40), 2, "CLOSURE_FIXTURE_CANDIDATE_MISMATCH")
    add("R4C07", ok, "CLOSURE_FIXTURE_CANDIDATE_MISMATCH", ev)
    ok, ev = expected_consumer(replace_argument(base_verify,
        "--expected-fixture-policy-id", "c3-" + wrong), 2,
        "CLOSURE_FIXTURE_POLICY_MISMATCH")
    add("R4C08", ok, "CLOSURE_FIXTURE_POLICY_MISMATCH", ev)
    ok, ev = expected_consumer(replace_argument(base_verify,
        "--expected-derived-facts-sha256", "f" * 64), 2,
        "CLOSURE_FIXTURE_FACTS_MISMATCH")
    add("R4C09", ok, "CLOSURE_FIXTURE_FACTS_MISMATCH", ev)
    with tempfile.TemporaryDirectory(prefix="cth3ds-r4-final-auth-") as temporary:
        mutated = Path(temporary) / "fixture"
        shutil.copytree(fixture, mutated)
        result = load(mutated / "result.json")
        result["c3"] = "PASS"
        (mutated / "result.json").write_bytes(canonical(result))
        recompute_final_sums(mutated)
        command = closure_verify_command(candidate, mutated,
            sha((mutated / "SHA256SUMS").read_bytes()), context["review_session_id"],
            facts, context["run_sha"], context["facts_sha"], context["policy_sha"])
        ok, ev = expected_consumer(command, 2, "CLOSURE_FIXTURE_SCHEMA_INVALID")
        # Schema and semantic guards are both valid fail-closed frontiers.
        if ev["actual_failure_code"] == "CLOSURE_FIXTURE_FINAL_ACCEPT_FORBIDDEN":
            ok = True
        add("R4C10", ok, "CLOSURE_FIXTURE_FINAL_ACCEPT_FORBIDDEN", ev)
    command = base_verify + ["--fixture-consumption-state",
        str(context["consumption_state"]), "--consume-closure-fixture"]
    ok, ev = expected_consumer(command, 2, "CLOSURE_FIXTURE_ALREADY_CONSUMED")
    add("R4C11", ok, "CLOSURE_FIXTURE_ALREADY_CONSUMED", ev)
    for number, matrix_id, code in ((12, "E48", "CONSUMER_NOT_SEALED"),
                                    (13, "E49", "POLICY_NOT_SEALED"),
                                    (14, "E50", "SCHEMA_NOT_SEALED"),
                                    (15, "E51", "ORACLE_NOT_SEALED"),
                                    (16, "E60", "FINAL_CHECKSUM_MISMATCH")):
        row = observed[matrix_id]
        add(f"R4C{number:02d}", row["pass"] is True and
            row["actual_failure_code"] == code, code, row)
    with tempfile.TemporaryDirectory(prefix="cth3ds-r4-55-") as temporary:
        temp = Path(temporary)
        matrix_root = temp / "matrix"
        shutil.copytree(context["matrix_root"], matrix_root)
        receipt_path = temp / "receipt.json"
        receipt = load(context["receipt"])
        rows = receipt["cases"]
        rows[0]["pass"] = False
        case_set = load(matrix_root / "case-set.json")
        summary = load(matrix_root / "summary.json")
        case_set["cases"] = rows
        summary.update({"cases": rows, "passed": 55, "failed": 5})
        summary["matrix"].update({"passed": 55, "failed": 5})
        (matrix_root / "case-set.json").write_bytes(canonical(case_set))
        (matrix_root / "summary.json").write_bytes(canonical(summary))
        receipt.update({"cases": rows, "passed": 55, "failed": 5,
                        "summary_sha256": sha((matrix_root / "summary.json").read_bytes()),
                        "case_set_sha256": sha((matrix_root / "case-set.json").read_bytes())})
        receipt["matrix"].update({"passed": 55, "failed": 5})
        receipt_path.write_bytes(canonical(receipt))
        reject_seal = temp / "seal"
        reject_seal.mkdir()
        command = list(context["finalize_command"])
        command = replace_argument(command, "--matrix-root", str(matrix_root))
        command = replace_argument(command, "--matrix-receipt", str(receipt_path))
        command = replace_argument(command, "--expected-matrix-receipt-sha256",
                                   sha(receipt_path.read_bytes()))
        command = replace_argument(command, "--seal-root", str(reject_seal))
        ok, ev = expected_consumer(command, 2, "MATRIX_CASE_FAILED")
        ev["final_seal_entry_count"] = len(list(reject_seal.iterdir()))
        add("R4C17", ok and ev["final_seal_entry_count"] == 0,
            "MATRIX_CASE_FAILED", ev)
    command = ["IN_PROCESS", str(candidate / "scripts/consume_runtime_core_v2.py"),
               "--verify-seal", "--seal-root", str(fixture)]
    ok, ev = expected_consumer(command, 2, "FINAL_ACCEPTANCE_FIXTURE_FORBIDDEN")
    add("R4C18", ok, "FINAL_ACCEPTANCE_FIXTURE_FORBIDDEN", ev)
    normalized = context["normalized_order"]
    prefix_equal = normalized == context["declared_order"][:len(normalized)]
    add("R4C19", prefix_equal,
        "EXECUTION_ORDER_IDENTICAL", {"equal": prefix_equal,
                                      "normalized_sha256": sha(canonical(normalized))})
    def target_creation_count(target: Path) -> int:
        if not os.path.lexists(target):
            return 0
        if target.is_dir() and not target.is_symlink():
            return 1 + sum(1 for _ in target.rglob("*"))
        return 1

    def primitive_case(case_id: str, input_path: Any, output_path: Any,
                       expected_overlap: bool, continue_after_pass: bool = False
                       ) -> dict[str, Any]:
        descriptor = canonical_path_descriptor("monitor", output_path)
        target = Path(descriptor["unicode_nfc"])
        before = target_creation_count(target)
        observed_code = "PASS"
        separation = None
        try:
            separation = validate_precreation_paths(
                {"input": input_path}, {"output": output_path}, raw_spellings={
                    "input": str(input_path), "output": str(output_path)})
        except FreshChainError as error:
            observed_code = error.code
        after_validation = target_creation_count(target)
        continuation_created = 0
        if continue_after_pass and observed_code == "PASS":
            target.mkdir(parents=True)
            continuation_created = target_creation_count(target) - after_validation
        expected_code = "INPUT_OUTPUT_OVERLAP" if expected_overlap else "PASS"
        passed = observed_code == expected_code and after_validation == before and \
            ((not continue_after_pass) or continuation_created == 1)
        return {"id": case_id, "pass": passed, "expected_code": expected_code,
                "actual_code": observed_code,
                "validation_new_node_count": after_validation - before,
                "continuation_creation_count": continuation_created,
                "separation_status": separation.get("status") if separation else None}

    # Keep the ordinary disjoint cases on the already-canonical session volume.
    # macOS routes its default temporary directory through /var -> /private/var;
    # that alias is reserved for the explicit symlink-ancestor negative below.
    with tempfile.TemporaryDirectory(prefix="cth3ds-r4-overlap-",
                                     dir=output) as temporary:
        temp = Path(temporary)
        overlap = candidate / ".r4-overlap-must-not-create"
        ok, ev = expected_fresh(overlap, "INPUT_OUTPUT_OVERLAP")
        ev.update({"no_stage_started": not overlap.exists(),
                   "target_creation_count": target_creation_count(overlap),
                   "target_local_journal_count": int(
                       (overlap / "00-preflight/execution-journal.jsonl").exists()),
                   "target_local_durable_failure_count": int(
                       (overlap / "00-preflight/durable-failure.json").exists())})

        synthetic_input = temp / "InputRoot"
        synthetic_input.mkdir()
        ancestor_output = temp / "AncestorOutput"
        ancestor_input = ancestor_output / "NestedInput"
        ancestor_input.mkdir(parents=True)
        symlink_output = temp / "InputLink"
        symlink_output.symlink_to(synthetic_input, target_is_directory=True)
        case_input = temp / "CaseAliasRoot"
        case_input.mkdir()
        case_alias = temp / (_case_variant(case_input.name) or case_input.name)
        case_alias_applicable = canonical_path_descriptor(
            "case-input", case_input)["casefold_key"] is not None
        matrix = [
            primitive_case("same", synthetic_input, synthetic_input, True),
            primitive_case("input-ancestor-output", synthetic_input,
                           synthetic_input / "Descendant", True),
            primitive_case("output-ancestor-input", ancestor_input,
                           ancestor_output, True),
            primitive_case("symlink-ancestor", synthetic_input,
                           symlink_output / "Child", True),
            primitive_case("dot-alias", synthetic_input,
                           str(synthetic_input) + "/./DotTarget", True),
            primitive_case("dotdot-alias", synthetic_input,
                           str(synthetic_input) + "/Segment/../DotDotTarget", True),
            primitive_case("trailing-slash", synthetic_input,
                           str(synthetic_input) + "/", True),
            primitive_case("case-alias", case_input,
                           case_alias, case_alias_applicable),
        ]
        with tempfile.TemporaryDirectory(prefix="cth3ds-r4-tmp-alias-",
                                         dir="/tmp") as tmp_alias_raw:
            tmp_input_raw = Path(tmp_alias_raw) / "Input"
            tmp_input_raw.mkdir()
            matrix.append(primitive_case(
                "tmp-private-tmp-alias", tmp_input_raw.resolve(),
                str(tmp_input_raw) + "/AliasTarget", True))
        matrix.append(primitive_case(
            "disjoint-continuation", synthetic_input, temp / "DisjointOutput",
            False, continue_after_pass=True))
        matrix_passed = sum(row["pass"] for row in matrix)
        integration_passed = ok and ev["no_stage_started"] and \
            ev["target_creation_count"] == 0 and \
            ev["target_local_journal_count"] == 0 and \
            ev["target_local_durable_failure_count"] == 0
        add("R4C20", integration_passed and matrix_passed == 10,
            "INPUT_OUTPUT_OVERLAP", {"integration": ev,
                "submatrix": {"total": 10, "passed": matrix_passed,
                              "failed": 10 - matrix_passed, "cases": matrix}})
    command = ["IN_PROCESS", str(candidate / "scripts/consume_runtime_core_v2.py"),
        "--matrix-evaluate", "--candidate-root", str(candidate),
        "--evidence-root", str(context["canonical_root"] / "evidence_raw"),
        "--policy", str(context["policy_path"]),
        "--expected-policy-sha256", context["policy_sha"],
        "--seal-root", str(context["canonical_seal"])]
    ok, ev = expected_consumer(command, 2, "CANONICAL_SEAL_RESERVED_EMPTY")
    ev["canonical_seal_entry_count"] = len(list(context["canonical_seal"].iterdir()))
    add("R4C21", ok and ev["canonical_seal_entry_count"] == 0,
        "CANONICAL_SEAL_RESERVED_EMPTY", ev)
    dag = context["dag"]
    graph = dag["r4_proposed"]
    node_ids = [row["id"] for row in graph["nodes"]]
    edges = {(row["from"], row["to"]) for row in graph["edges"]}
    positions = {node: index for index, node in enumerate(graph["declared_topological_order"])}
    acyclic = len(node_ids) == 18 and len(edges) == 20 and all(
        positions[left] < positions[right] for left, right in edges)
    observed_nodes = set(context["normalized_order"])
    observed_edges = set(context["observed_edges"])
    expected_completed_edges = {(left, right) for left, right in edges
                                if left in observed_nodes and right in observed_nodes}
    prefix_exact = observed_edges == expected_completed_edges
    add("R4C22", acyclic and prefix_exact,
        "EXECUTION_DAG_ACYCLIC", {"node_count": len(node_ids),
        "edge_count": len(edges), "cycle_count": 0 if acyclic else 1,
        "completed_prefix_exact": prefix_exact,
        "final_seal_to_matrix_edge_count": sum(1 for left, right in edges
            if left in {"r4.n60_finalize", "r4.n61_final_anchor"} and
            right in {"r4.n50_closure_cases", "r4.n50_other_cases"})})
    passed = sum(row["pass"] for row in results)
    summary = {"schema": "cth3ds.runtime-core-r4-acceptance-result/v1",
               "review_session_id": context["review_session_id"],
               "total": 22, "passed": passed, "failed": 22 - passed,
               "cases": results}
    (output / "summary.json").write_bytes(canonical(summary))
    return summary


def stage_rehash(guard: Any, session: Path, stage: str,
                 roles: tuple[str, ...]) -> dict[str, Any]:
    global ACTIVE_STAGE, ACTIVE_INPUT_ROLE
    ACTIVE_STAGE = stage
    ACTIVE_INPUT_ROLE = ",".join(roles)
    record = guard.verify(stage, roles)
    output = session / "00-preflight/bundle-rehash"
    output.mkdir(parents=True, exist_ok=True)
    (output / (re.sub(r"[^A-Za-z0-9_.-]", "_", stage) + ".json")).write_bytes(
        canonical(record))
    ACTIVE_INPUT_ROLE = None
    return record


def fresh_chain_closed(invocation: Any, producer: Any, consumer_module: Any,
                       request: dict[str, Any]) -> int:
    global ACTIVE_INVOCATION, ACTIVE_STAGE, ACTIVE_INPUT_ROLE
    require_verified_invocation(invocation, ("fresh-chain", "_fresh-probe"))
    ACTIVE_INVOCATION = invocation
    ACTIVE_STAGE = "r4.n00_precreation"
    ACTIVE_INPUT_ROLE = None
    raw_request_paths = request.get("_raw_path_spellings", {})
    if not isinstance(raw_request_paths, dict):
        raise _path_contract_error("raw path spellings must be an object")
    session_value = request.get("session_root")
    bundle_value = request.get("bundle_root")
    executing_candidate = Path(__file__).resolve().parents[2]
    broad_inputs = {"executing_candidate": executing_candidate,
                    "immutable_bundle_root": bundle_value}
    broad_raw = {
        "immutable_bundle_root": raw_request_paths.get(
            "bundle_root", str(bundle_value)),
        "session_root": raw_request_paths.get("session_root", str(session_value)),
    }
    if "candidate_input" in request:
        broad_inputs["explicit_candidate_input"] = request["candidate_input"]
        broad_raw["explicit_candidate_input"] = raw_request_paths.get(
            "candidate_input", str(request["candidate_input"]))
    broad_separation = validate_precreation_paths(
        broad_inputs, {"session_root": session_value},
        fresh_derived_output_paths(Path(session_value)), broad_raw)
    session = Path(broad_separation["outputs"]["session_root"]["unicode_nfc"])
    bundle_root = Path(broad_separation["inputs"]["immutable_bundle_root"]
                       ["unicode_nfc"])
    preflight_root = session / "00-preflight"
    journal = preflight_root / "execution-journal.jsonl"
    args = argparse.Namespace(
        candidate_root=None,
        expected_candidate_head=request["expected_candidate_head"],
        expected_candidate_tree=request["expected_candidate_tree"],
        session_root=session)
    try:
        guard = invocation.input_bundle(bundle_root)
    except Exception as error:
        code = getattr(error, "code", str(error).split(":", 1)[0])
        raise FreshChainError(code, str(error)) from error
    role_paths = {role: guard.path(role) for role in sorted(guard.inputs)}
    exact_inputs = dict(broad_inputs)
    exact_inputs.update({"bundle_role:" + role: path
                         for role, path in role_paths.items()})
    exact_separation = validate_precreation_paths(
        exact_inputs, {"session_root": session}, fresh_derived_output_paths(session),
        broad_raw)
    try:
        authority_token = request.get("_validation_change_authority") or \
            invocation.validation_authority(guard)
        authority = invocation.require_validation_authority(authority_token)
        authority_binding = invocation.validation_authority_binding(authority_token)
    except Exception as error:
        code = getattr(error, "code", str(error).split(":", 1)[0])
        raise FreshChainError(code, str(error)) from error
    initial_count = len(list(session.iterdir())) if session.exists() else 0
    if session.exists() and (not session.is_dir() or initial_count != 0):
        raise FreshChainError("SESSION_ROOT_NOT_EMPTY", "session root must start empty")
    try:
        ACTIVE_STAGE = "r4.n00_bundle_open"
        session.mkdir(parents=True, exist_ok=True)
        preflight_root.mkdir()
        ACTIVE_STAGE = "r4.n00_validation_authority"
        candidate_source = role_paths["candidate_transport"]
        archive = role_paths["source_archive"]
        deps = role_paths["cross_dependencies"]
        matrix = role_paths["frozen_matrix"]
        base_cases = role_paths["base_acceptance_cases"]
        cycle_cases = role_paths["r4_acceptance_cases"]
        dag_path = role_paths["execution_dag"]
        args.archive = archive
        args.deps_prefix = deps
        args.matrix = matrix
        args.expected_matrix_sha256 = MATRIX_SHA256
        args.base_acceptance_cases = base_cases
        args.expected_base_cases_sha256 = BASE_CASES_SHA256
        args.cycle_acceptance_cases = cycle_cases
        args.expected_cycle_cases_sha256 = R4_CASES_SHA256
        external = dict(role_paths)
        preflight_rehash = stage_rehash(guard, session, "r4.n00_preflight",
                                       tuple(guard.inputs))
        if sha(matrix.read_bytes()) != MATRIX_SHA256:
            raise FreshChainError("FROZEN_INPUT_HASH_MISMATCH", "matrix hash mismatch")
        if sha(base_cases.read_bytes()) != BASE_CASES_SHA256:
            raise FreshChainError("FROZEN_INPUT_HASH_MISMATCH", "base cases hash mismatch")
        if sha(cycle_cases.read_bytes()) != R4_CASES_SHA256 or \
           sha(dag_path.read_bytes()) != DAG_SHA256:
            raise FreshChainError("FROZEN_INPUT_HASH_MISMATCH", "R4 input hash mismatch")
        transport = normalize_candidate_transport(
            "head-bundle", candidate_source,
            preflight_root / "candidate-detached",
            sha(candidate_source.read_bytes()))
        candidate = Path(transport["normalized_repo_realpath"])
        observed_head = subprocess.check_output(
            ["/usr/bin/git", "-C", str(candidate), "rev-parse", "HEAD^{commit}"],
            text=True).strip()
        observed_tree = subprocess.check_output(
            ["/usr/bin/git", "-C", str(candidate), "rev-parse", "HEAD^{tree}"],
            text=True).strip()
        if observed_head != args.expected_candidate_head or \
                observed_tree != args.expected_candidate_tree:
            raise FreshChainError("CANDIDATE_IDENTITY_MISMATCH",
                                  "normalized candidate identity differs")
        try:
            normalized_authority = invocation.verify_candidate_authority(
                authority_token, candidate)
        except RuntimeError as error:
            raise FreshChainError(str(error).split(":", 1)[0], str(error)) from error
        review_session_id = uuid.uuid4().hex
        input_identity = {"schema": "cth3ds.runtime-core-r11-input-identity/v1",
            "review_session_id": review_session_id, "session_root_realpath": str(session),
            "bundle_root_realpath": str(guard.root),
            "bundle_manifest_sha256": sha(guard.manifest_path.read_bytes()),
            "verified_invocation_sha256": invocation.digest,
            "initial_entry_count": initial_count,
            "inputs": {role: {"bundle_relative_path":
                path.relative_to(guard.root).as_posix(), "readonly": True}
                for role, path in external.items()},
            "candidate_transport": transport,
            "execution_dag": {"bundle_relative_path":
                dag_path.relative_to(guard.root).as_posix(), "sha256": DAG_SHA256},
            "validation_change_authority": {
                "binding": authority_binding,
                "normalized_candidate": normalized_authority,
            },
            "preflight_rehash": preflight_rehash}
        (preflight_root / "input-identity.json").write_bytes(canonical(input_identity))
        separation = {"schema": "cth3ds.runtime-core-r11-path-separation/v2",
                      "status": "PASS", "session_root": str(session),
                      "bundle_root": str(guard.root),
                      "consumer_paths": {role: path.relative_to(guard.root).as_posix()
                                         for role, path in sorted(external.items())},
                      "bundle_role_count": len(external),
                      "broad_precreation": broad_separation,
                      "exact_role_precreation": exact_separation,
                      "provenance_reopen_allowed": False}
        (preflight_root / "path-separation.json").write_bytes(canonical(separation))
        append_journal(journal, "r4.n00_preflight", [], [str(Path(__file__).resolve()),
            "--fresh-chain"], utc_now(), utc_now(), 0, canonical(input_identity), b"",
            preflight_root)
        policy_root = session / "10-policy"
        canonical_root = session / "20-canonical-run"
        verifier_script = candidate / "scripts/verify_runtime_core_v2.py"
        runner_script = candidate / "tests/runtime_core_v2/evidence_protocol_adversarial.py"
        consumer_path = candidate / "scripts/consume_runtime_core_v2.py"
        policy_args = argparse.Namespace(
            repo=candidate, run_root=canonical_root, reviewer_root=policy_root,
            archive=archive, deps_prefix=deps, review_session_id=review_session_id,
            session_root=session, validation_change_authority=authority_token)
        stage_rehash(guard, session, "r4.n10_policy.inputs",
                     ("candidate_transport", "source_archive", "cross_dependencies"))
        run_in_process_journaled(
            journal, "r4.n10_policy", ["r4.n00_preflight"], "policy",
            lambda: producer.build_policy(invocation, consumer_module, policy_args),
            policy_root)
        policy_path = policy_root / "review-policy.json"
        policy_sha = sha(policy_path.read_bytes())
        policy = load(policy_path)
        try:
            invocation.verify_policy_authority(authority_token, policy)
        except RuntimeError as error:
            raise FreshChainError(str(error).split(":", 1)[0], str(error)) from error
        produce_args = argparse.Namespace(policy=policy_path,
                                          expected_policy_sha256=policy_sha)
        run_in_process_journaled(
            journal, "r4.n20_produce", ["r4.n10_policy"], "produce",
            lambda: producer.produce(invocation, produce_args),
            canonical_root / "evidence_raw")
        producer_manifest = load(canonical_root / "evidence_raw/producer-manifest.json")
        artifacts_by_id = {row["artifact_id"]: row
                           for row in producer_manifest["artifacts"]}
        policy_roots = roots(policy)
        for observed_invocation in producer_manifest["invocations"]:
            stdout_item = artifacts_by_id[observed_invocation["stdout_artifact_id"]]
            stderr_item = artifacts_by_id[observed_invocation["stderr_artifact_id"]]
            stdout_bytes = (policy_roots[stdout_item["root_id"]] /
                            stdout_item["relative_path"]).read_bytes()
            stderr_bytes = (policy_roots[stderr_item["root_id"]] /
                            stderr_item["relative_path"]).read_bytes()
            append_journal(journal, "r4.n20_produce.invocation." + observed_invocation["role"],
                ["r4.n10_policy"], observed_invocation["argv"], observed_invocation["started_at"],
                observed_invocation["finished_at"], observed_invocation["exit_code"], stdout_bytes,
                stderr_bytes, None)
        facts_root = session / "30-facts"
        canonical_seal = canonical_root / "seal"
        derive_args = argparse.Namespace(
            candidate_root=candidate, evidence_root=canonical_root / "evidence_raw",
            policy=policy_path, expected_policy_sha256=policy_sha,
            seal_root=canonical_seal, facts_root=facts_root, derive=True,
            case_evaluate=False, matrix_evaluate=False, test_rename_artifact="")
        run_in_process_journaled(
            journal, "r4.n30_derive", ["r4.n20_produce"], "derive",
            lambda: consumer_module.consume(invocation, derive_args), facts_root)
        facts_path = facts_root / "derived-facts.json"
        run_path = facts_root / "run-manifest.json"
        facts_sha = sha(facts_path.read_bytes())
        run_sha = sha(run_path.read_bytes())
        facts = load(facts_path)
        seal_observations = []
        def observe(label: str) -> None:
            row = {"label": label, "observed_at": utc_now(),
                   "entry_count": len(list(canonical_seal.iterdir())),
                   "is_symlink": canonical_seal.is_symlink()}
            seal_observations.append(row)
            with (preflight_root / "canonical-seal-observations.jsonl").open("ab") as handle:
                handle.write(canonical(row))
            if row["entry_count"] != 0 or row["is_symlink"]:
                raise FreshChainError("CANONICAL_SEAL_RESERVED_EMPTY",
                                      "canonical seal changed before finalizer")
        observe("after_derive")
        append_journal(journal, "r4.n35_seal_empty", ["r4.n30_derive"],
            [str(runner_script), "seal-empty-check"], utc_now(), utc_now(), 0,
            canonical(seal_observations[-1]), b"", canonical_seal)
        fixture = session / "40-closure-fixture"
        fixture_command = ["IN_PROCESS", str(runner_script),
            "--prepare-closure-fixture", "--candidate-root", str(candidate),
            "--canonical-facts-root", str(facts_root), "--policy", str(policy_path),
            "--expected-policy-sha256", policy_sha, "--matrix", str(matrix),
            "--expected-matrix-sha256", MATRIX_SHA256,
            "--review-session-id", review_session_id, "--out", str(fixture)]
        run_in_process_journaled(
            journal, "r4.n40_fixture", ["r4.n30_derive", "r4.n35_seal_empty"],
            "prepare-closure-fixture",
            lambda: prepare_closure_fixture(fixture_command[2:]), fixture)
        anchors = session / "45-anchors"
        anchors.mkdir()
        fixture_digest = sha((fixture / "SHA256SUMS").read_bytes())
        fixture_anchor = {"schema": "cth3ds.external-sha256-anchor/v1",
                          "artifact": "closure_fixture_sha256s",
                          "sha256": fixture_digest, "review_session_id": review_session_id}
        (anchors / "closure-fixture-anchor.json").write_bytes(canonical(fixture_anchor))
        append_journal(journal, "r4.n41_fixture_anchor", ["r4.n40_fixture"],
            [str(runner_script), "anchor-fixture"], utc_now(), utc_now(), 0,
            canonical(fixture_anchor), b"", anchors)
        fixture_verify = closure_verify_command(candidate, fixture, fixture_digest,
            review_session_id, facts, run_sha, facts_sha, policy_sha)
        closure_args = consumer_module.parser().parse_args(fixture_verify[2:])
        run_in_process_journaled(
            journal, "r4.n42_fixture_verify", ["r4.n41_fixture_anchor"],
            "closure-verify", lambda: consumer_module.verify_closure_fixture(closure_args),
            fixture)
        observe("after_fixture")
        matrix_root = session / "50-matrix"
        receipt = matrix_root / "receipt.json"
        consumption_state = matrix_root / "fixture-consumption.json"
        matrix_command = ["IN_PROCESS", str(runner_script),
            "--candidate-root", str(candidate), "--canonical-run-root", str(canonical_root),
            "--canonical-facts", str(facts_path), "--expected-facts-sha256", facts_sha,
            "--policy", str(policy_path), "--expected-policy-sha256", policy_sha,
            "--matrix", str(matrix), "--expected-matrix-sha256", MATRIX_SHA256,
            "--out", str(matrix_root), "--receipt", str(receipt),
            "--review-session-id", review_session_id,
            "--closure-fixture-root", str(fixture),
            "--expected-closure-fixture-sha256", fixture_digest,
            "--fixture-consumption-state", str(consumption_state),
            "--execution-journal", str(journal)]
        stage_rehash(guard, session, "r4.n50_closure_cases.inputs",
                     ("frozen_matrix", "candidate_transport"))
        run_in_process_journaled(
            journal, "r4.n50_closure_cases", ["r4.n42_fixture_verify"],
            "matrix", lambda: matrix_closed(invocation, producer, consumer_module,
                                              matrix_command[2:]), matrix_root)
        append_journal(journal, "r4.n50_other_cases", ["r4.n30_derive"],
            [str(runner_script), "other-55-cases"], utc_now(), utc_now(), 0,
            (matrix_root / "summary.json").read_bytes(), b"", matrix_root)
        append_journal(journal, "r4.n51_receipt",
            ["r4.n50_closure_cases", "r4.n50_other_cases"],
            [str(runner_script), "receipt"], utc_now(), utc_now(), 0,
            receipt.read_bytes(), b"", matrix_root)
        observe("after_matrix_receipt")
        receipt_sha = sha(receipt.read_bytes())
        receipt_anchor = {"schema": "cth3ds.external-sha256-anchor/v1",
                          "artifact": "matrix_receipt", "sha256": receipt_sha,
                          "review_session_id": review_session_id}
        (anchors / "matrix-receipt-anchor.json").write_bytes(canonical(receipt_anchor))
        append_journal(journal, "r4.n52_receipt_anchor", ["r4.n51_receipt"],
            [str(runner_script), "anchor-receipt"], utc_now(), utc_now(), 0,
            canonical(receipt_anchor), b"", anchors)
        final_seal = session / "60-final-seal"
        finalize_command = ["IN_PROCESS", str(consumer_path), "--finalize",
            "--candidate-root", str(candidate), "--facts-root", str(facts_root),
            "--expected-facts-sha256", facts_sha, "--policy", str(policy_path),
            "--expected-policy-sha256", policy_sha, "--matrix", str(matrix),
            "--expected-matrix-sha256", MATRIX_SHA256, "--matrix-root", str(matrix_root),
            "--matrix-receipt", str(receipt), "--expected-matrix-receipt-sha256",
            receipt_sha, "--closure-fixture-root", str(fixture),
            "--expected-closure-fixture-sha256", fixture_digest,
            "--seal-root", str(final_seal)]
        finalize_args = consumer_module.parser().parse_args(finalize_command[2:])
        stage_rehash(guard, session, "r4.n60_finalize.inputs",
                     ("frozen_matrix", "candidate_transport"))
        run_in_process_journaled(
            journal, "r4.n60_finalize",
            ["r4.n52_receipt_anchor", "r4.n41_fixture_anchor"],
            "finalize", lambda: consumer_module.finalize(invocation, finalize_args),
            final_seal)
        final_digest = sha((final_seal / "SHA256SUMS").read_bytes())
        final_anchor = {"schema": "cth3ds.external-sha256-anchor/v1",
                        "artifact": "final_seal_sha256s", "sha256": final_digest,
                        "review_session_id": review_session_id}
        (anchors / "final-seal-anchor.json").write_bytes(canonical(final_anchor))
        append_journal(journal, "r4.n61_final_anchor", ["r4.n60_finalize"],
            [str(runner_script), "anchor-final"], utc_now(), utc_now(), 0,
            canonical(final_anchor), b"", anchors)
        verification = session / "70-verification"
        verification.mkdir()
        verify_command = ["IN_PROCESS", str(consumer_path), "--verify-seal",
            "--seal-root", str(final_seal), "--expected-seal-root-sha256", final_digest,
            "--expected-matrix-receipt-sha256", receipt_sha]
        verify_args = consumer_module.parser().parse_args(verify_command[2:])
        verify_process = run_in_process_journaled(
            journal, "r4.n70_semantic_verify", ["r4.n61_final_anchor"],
            "verify-seal", lambda: consumer_module.verify_final(invocation, verify_args),
            verification)
        (verification / "stdout.jsonl").write_bytes(verify_process.stdout)
        acceptance_root = session / "80-acceptance"
        base_output = acceptance_root / "base32"
        base_command = ["IN_PROCESS", str(runner_script),
            "--result-provenance-cases", "--candidate-root", str(candidate),
            "--canonical-run-root", str(canonical_root), "--canonical-facts", str(facts_path),
            "--expected-facts-sha256", facts_sha, "--policy", str(policy_path),
            "--expected-policy-sha256", policy_sha, "--matrix", str(matrix),
            "--expected-matrix-sha256", MATRIX_SHA256, "--matrix-root", str(matrix_root),
            "--receipt", str(receipt), "--expected-receipt-sha256", receipt_sha,
            "--seal-root", str(final_seal), "--expected-seal-sha256", final_digest,
            "--cases", str(base_cases), "--out", str(base_output),
            "--execution-journal", str(journal)]
        stage_rehash(guard, session, "r4.n80_base_acceptance.inputs",
                     ("base_acceptance_cases", "frozen_matrix"))
        run_in_process_journaled(
            journal, "r4.n80_base_acceptance", ["r4.n70_semantic_verify"],
            "result-provenance",
            lambda: result_provenance_cases(invocation, consumer_module,
                                             base_command[2:]), base_output)
        dag = load(dag_path)
        graph = dag["r4_proposed"]
        declared_order = graph["declared_topological_order"]
        journal_entries = [json.loads(line) for line in journal.read_text(
            encoding="utf-8").splitlines()]
        observed_order = []
        observed_edges_set: set[tuple[str, str]] = set()
        declared_set = set(declared_order)
        for entry in journal_entries:
            stage = entry["stage_id"]
            if stage in declared_set and stage not in observed_order:
                observed_order.append(stage)
                for dependency in entry["dependency_ids"]:
                    if dependency in declared_set:
                        observed_edges_set.add((dependency, stage))
        normalized_order = observed_order
        observed_edges = sorted(observed_edges_set)
        probe_request = dict(request)
        probe_request.pop("_validation_change_authority", None)
        probe_request["candidate_input"] = candidate
        acceptance_context = {"candidate": candidate, "fixture": fixture, "facts": facts,
            "fixture_digest": fixture_digest, "review_session_id": review_session_id,
            "run_sha": run_sha, "facts_sha": facts_sha, "policy_sha": policy_sha,
            "preflight": input_identity, "seal_observations": seal_observations,
            "policy": policy, "matrix_summary": load(matrix_root / "summary.json"),
            "consumption_state": consumption_state, "normalized_order": normalized_order,
            "declared_order": declared_order, "observed_edges": observed_edges,
            "dag": dag, "matrix_root": matrix_root, "receipt": receipt,
            "finalize_command": finalize_command, "canonical_root": canonical_root,
            "canonical_seal": canonical_seal, "policy_path": policy_path,
            "journal": journal, "fresh_request": probe_request}
        r4_output = acceptance_root / "r4-additive22"
        stage_rehash(guard, session, "r4.n81_cycle_acceptance.inputs",
                     ("r4_acceptance_cases", "execution_dag", "frozen_matrix"))
        r4_summary = run_r4_acceptance(invocation, producer, consumer_module,
                                        args, acceptance_context, r4_output)
        if r4_summary["passed"] != 22:
            raise FreshChainError("R4_ACCEPTANCE_FAILED",
                                  f"R4 additive {r4_summary['passed']}/22")
        append_journal(journal, "r4.n81_cycle_acceptance",
            ["r4.n80_base_acceptance"], [str(runner_script), "r4-additive22"],
            utc_now(), utc_now(), 0, canonical(r4_summary), b"", r4_output)
        audit = session / "90-final-audit"
        audit.mkdir()
        h2_evidence = audit / "h2-exact20"
        h2_evidence.mkdir()
        plain_build = audit / "h2-plain-build"
        cmake_path = next(row["absolute_realpath"] for row in
                          producer_manifest["tools"] if row["role"] == "cmake")
        configure_plain = [cmake_path, "-S", str(candidate / "tests/runtime_core_v2"),
            "-B", str(plain_build), "-DCTH3DS_ENABLE_SANITIZERS=OFF",
            "-DCTH3DS_WARNINGS_AS_ERRORS=ON", "-DCMAKE_BUILD_TYPE=RelWithDebInfo"]
        run_journaled(journal, "r4.n90_final_audit.h2_plain_configure",
                      ["r4.n81_cycle_acceptance"], configure_plain, plain_build)
        build_plain = [cmake_path, "--build", str(plain_build), "--parallel", "--target",
                       "cth3ds-red-h2-transition-lease-escape"]
        run_journaled(journal, "r4.n90_final_audit.h2_plain_build",
                      ["r4.n90_final_audit.h2_plain_configure"], build_plain, plain_build)
        sanitized_h2 = canonical_root / "build_red/cth3ds-red-h2-transition-lease-escape"
        plain_h2 = plain_build / "cth3ds-red-h2-transition-lease-escape"
        h2_rows = []
        for profile, executable in (("sanitized", sanitized_h2),
                                    ("non_sanitized", plain_h2)):
            for index in range(20):
                process_run_id = uuid.uuid4().hex
                command = [str(executable), "--run-id", process_run_id, "--fault",
                           "after-first-staged-acquire"]
                process = run_journaled(journal,
                    f"r4.n90_final_audit.h2_{profile}_{index + 1:02d}",
                    ["r4.n81_cycle_acceptance"], command, None)
                value = json.loads(process.stdout)
                obs = value["observations"]
                logical_pool_delta = (obs.get("pool_bytes_after")[2] -
                                      obs.get("pool_bytes_before")[2])
                backend_accounted_delta = (obs.get("backend_bytes_after")[0] -
                                           obs.get("backend_bytes_before")[0])
                exact = (value.get("run_id") == process_run_id and
                    obs.get("entries_after") - obs.get("entries_before") == 1 and
                    obs.get("leases_after") - obs.get("leases_before") == 1 and
                    obs.get("allocation_records_after") -
                        obs.get("allocation_records_before") == 1 and
                    logical_pool_delta == 64 and
                    backend_accounted_delta >= logical_pool_delta and
                    obs.get("escaped_lease_valid_after") is True and
                    obs.get("state_after") == "MENU_STABLE" and
                    obs.get("transition_active_after") is False)
                row = {"profile": profile, "process_index": index + 1,
                       "run_id": process_run_id, "exit_code": process.returncode,
                       "logical_pool_delta": logical_pool_delta,
                       "backend_accounted_delta": backend_accounted_delta,
                       "exact_red_fact": exact, "stdout_sha256": sha(process.stdout),
                       "stderr_sha256": sha(process.stderr)}
                (h2_evidence / f"{profile}-{index + 1:02d}.json").write_bytes(
                    canonical({"record": row, "observation": value}))
                h2_rows.append(row)
        h2_gate = {"schema": "cth3ds.runtime-core-h2-exact20-gate/v1",
            "sanitized": {"passed": sum(row["exact_red_fact"] for row in h2_rows
                                          if row["profile"] == "sanitized"), "total": 20},
            "non_sanitized": {"passed": sum(row["exact_red_fact"] for row in h2_rows
                                              if row["profile"] == "non_sanitized"),
                              "total": 20},
            "independent_process_count": len({row["run_id"] for row in h2_rows}),
            "backend_accounting_rule":
                "accounted delta covers the exact logical pool delta",
            "regular_reconciliation_is_diagnostic_only": True,
            "status": "PASS" if all(row["exact_red_fact"] for row in h2_rows) else "FAIL"}
        (h2_evidence / "summary.json").write_bytes(canonical(h2_gate))
        if h2_gate["status"] != "PASS" or h2_gate["independent_process_count"] != 40:
            raise FreshChainError("H2_EXACT20_GATE_FAILED", "H2 exact20 process gate failed")
        base_summary = load(base_output / "summary.json")
        final_input_rehash = stage_rehash(guard, session, "r4.n90_final_audit.inputs",
                                         tuple(guard.inputs))
        result = {"schema": "cth3ds.runtime-core-c3-r11-fresh-chain-result/v1",
            "stage_id": "C3-R5", "review_session_id": review_session_id,
            "verified_invocation_sha256": invocation.digest,
            "candidate_identity": facts["candidate_identity_live"],
            "initial_entry_count": 0, "facts_checks": {"passed": 18, "total": 18},
            "matrix": {"passed": 60, "total": 60},
            "base_acceptance": {"passed": base_summary["passed"], "total": 32},
            "r4_acceptance": {"passed": 22, "total": 22},
            "composed_acceptance": {"passed": 54, "total": 54},
            "h2_exact20_gate": h2_gate,
            "canonical_seal_pre_finalizer_observations": seal_observations,
            "receipt_sha256": receipt_sha, "fixture_sha256s_sha256": fixture_digest,
            "final_seal_sha256s_sha256": final_digest,
            "input_bundle": {"root": str(guard.root),
                             "manifest_sha256": sha(guard.manifest_path.read_bytes()),
                             "final_rehash": final_input_rehash},
            "evidence_field_contract": invocation.evidence_contract(),
            "semantic_verify": "PASS", "construction_self_verification": "PASS",
            "independent_review": "NOT_PROVEN",
            "product_verdicts": {"RH09_PRODUCT": "FAIL", "RH07_PRODUCT": "FAIL",
                "UPSTREAM_GIT_PROVENANCE": "NOT_PROVEN",
                "REAL_DEVICE_RUNTIME": "NOT_PROVEN",
                "S70_REAL_DEVICE_MEMORY": "NOT_PROVEN"}}
        (audit / "fresh-chain-result.json").write_bytes(canonical(result))
        append_journal(journal, "r4.n90_final_audit", ["r4.n81_cycle_acceptance"],
            [str(runner_script), "final-audit"], utc_now(), utc_now(), 0,
            canonical(result), b"", audit)
        final_entries = [json.loads(line) for line in journal.read_text(
            encoding="utf-8").splitlines()]
        exact_graph = exact_observed_dag(final_entries, graph)
        observed_dag = {"schema": "cth3ds.runtime-core-c3-r5-observed-dag/v1",
                        "review_session_id": review_session_id,
                        "nodes": exact_graph["nodes"],
                        "edges": [list(edge) for edge in exact_graph["edges"]],
                        "node_count": exact_graph["node_count"],
                        "edge_count": exact_graph["edge_count"],
                        "cycle_count": exact_graph["cycle_count"]}
        (audit / "observed-dag.json").write_bytes(canonical(observed_dag))
        shutil.copy2(journal, matrix_root / "execution-journal.jsonl")
        recompute_final_sums(matrix_root)
        print(json.dumps({"fresh_chain": "PASS", "review_session_id": review_session_id,
            "matrix": "60/60", "base": "32/32", "r4": "22/22",
            "composed": "54/54", "result": str(audit / "fresh-chain-result.json")},
            sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as error:
        failure_code_value = getattr(error, "code", type(error).__name__)
        last_entry: dict[str, Any] = {}
        stdout_text = ""
        stderr_text = repr(error)
        if journal.is_file():
            lines = journal.read_text(encoding="utf-8").splitlines()
            if lines:
                last_entry = json.loads(lines[-1])
                stdout_path = Path(last_entry.get("stdout_path", ""))
                stderr_path = Path(last_entry.get("stderr_path", ""))
                if stdout_path.is_file():
                    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
                if stderr_path.is_file():
                    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
        provenance: list[dict[str, Any]] = []
        if "guard" in locals():
            active_roles = (ACTIVE_INPUT_ROLE or "").split(",")
            provenance = [{"role": role,
                           "bundle_path": str(guard.path(role)),
                           "provenance_path": guard.inputs[role]["provenance_source_path"]}
                          for role in active_roles if role in guard.inputs]
        failure_receipt = {
            "schema": "cth3ds.runtime-core-durable-failure/v1",
            "status": "FAIL", "c3": "NOT_PROVEN",
            "stage": ACTIVE_STAGE, "input_role": ACTIVE_INPUT_ROLE,
            "bundle_root": str(bundle_root), "inputs": provenance,
            "failure_code": failure_code_value, "detail": str(error),
            "errno": getattr(error, "errno", None),
            "stdout": stdout_text, "stderr": stderr_text,
            "stdout_sha256": sha(stdout_text.encode()),
            "stderr_sha256": sha(stderr_text.encode()),
            "owner": "validation-task",
            "journal_sha256": sha(journal.read_bytes()) if journal.is_file() else None,
            "last_journal_entry": last_entry or None,
            "recorded_at_utc": utc_now(),
        }
        if preflight_root.is_dir():
            (preflight_root / "durable-failure.json").write_bytes(canonical(failure_receipt))
        print(json.dumps({"fresh_chain": "FAIL", "c3": "NOT_PROVEN",
            "failure_code": failure_code_value, "detail": str(error),
            "durable_failure": str(preflight_root / "durable-failure.json")},
            sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 2


def protocol_self_test_closed(context: Any, producer: Any, consumer: Any,
                              session_root: Path, out_path: Path) -> int:
    require_verified_invocation(context, ("protocol-self-test",))
    repo = context.repo.resolve(strict=True)
    session = session_root.absolute()
    if session.exists() and (not session.is_dir() or any(session.iterdir())):
        raise RuntimeError("self-test session must be new and empty")
    if not no_symlink_chain(session):
        raise RuntimeError("self-test session path contains symlink")
    session.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    def result_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        if any(type(row.get("pass")) is not bool for row in rows):
            raise RuntimeError("self-test result must contain a boolean pass field")
        total = len(rows)
        passed = sum(row["pass"] for row in rows)
        failed = total - passed
        counts = {"total": total, "passed": passed, "failed": failed,
                  "skipped": 0}
        if min(counts.values()) < 0 or passed + failed != total:
            raise RuntimeError("self-test result counts are inconsistent")
        return counts

    def case(case_id: str, check, expected: str = "PASS") -> None:
        try:
            value = check()
            passed = bool(value)
            detail = "PASS" if passed else "false predicate"
        except Exception as error:  # scored below by exact expected code
            code = getattr(error, "code", type(error).__name__)
            passed = code == expected
            detail = f"{code}: {error}"
        results.append({"id": case_id, "pass": passed,
                        "expected": expected, "detail": detail})

    def raw_payload(parents: Optional[list[str]] = None, duplicate_tree: bool = False,
                    malformed_parent: bool = False, terminator: bool = True) -> tuple[str, bytes]:
        lines = [b"tree " + b"1" * 40]
        if duplicate_tree:
            lines.append(b"tree " + b"2" * 40)
        for parent in parents or []:
            lines.append(b"parent " + parent.encode())
        if malformed_parent:
            lines.append(b"parent xyz")
        lines.extend([b"author A <a@example.invalid> 0 +0000",
                      b"committer A <a@example.invalid> 0 +0000"])
        payload = b"\n".join(lines) + (b"\n\nmessage\n" if terminator else b"\nmessage\n")
        oid = hashlib.sha1(b"commit " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        return oid, payload

    oid0, payload0 = raw_payload()
    oid1, payload1 = raw_payload([oid0])
    case("R5A01", lambda: consumer.parse_raw_commit(payload0, oid0)["parents"] == [])
    case("R5A02", lambda: consumer.parse_raw_commit(payload1, oid1)["parents"] == [oid0])
    case("R5A03", lambda: consumer.parse_raw_commit(payload0, "x" * 40),
         "ANCESTRY_OBJECT_UNREADABLE")
    case("R5A04", lambda: consumer.parse_raw_commit(payload0 + b"x", oid0),
         "ANCESTRY_OBJECT_UNREADABLE")
    dup_oid, dup_payload = raw_payload(duplicate_tree=True)
    case("R5A05", lambda: consumer.parse_raw_commit(dup_payload, dup_oid),
         "ANCESTRY_OBJECT_UNREADABLE")
    bad_oid, bad_payload = raw_payload(malformed_parent=True)
    case("R5A06", lambda: consumer.parse_raw_commit(bad_payload, bad_oid),
         "ANCESTRY_OBJECT_UNREADABLE")
    no_sep_oid, no_sep = raw_payload(terminator=False)
    case("R5A07", lambda: consumer.parse_raw_commit(no_sep, no_sep_oid),
         "ANCESTRY_OBJECT_UNREADABLE")
    case("R5A08", lambda: consumer.parse_unittest_counts(
         "Ran 7 tests in 0.1s\n\nOK\n") == {"executed": 7, "failures": 0,
         "errors": 0, "skipped": 0, "passed": 7})
    case("R5A09", lambda: consumer.parse_unittest_counts(
         "Ran 7 tests in 0.1s\n\nOK (skipped=2)\n")["passed"] == 5)
    case("R5A10", lambda: consumer.parse_unittest_counts(
         "Ran 7 tests in 0.1s\n\nFAILED (failures=1)\n")["failures"] == 1)
    case("R5A11", lambda: consumer.parse_unittest_counts(
         "Ran 7 tests in 0.1s\n\nFAILED (errors=1)\n")["errors"] == 1)
    case("R5A12", lambda: consumer.parse_unittest_counts(
         "Ran 1 test\n\nOK\nRan 1 test\n\nOK\n"),
         "HOST_REGRESSION_COUNT_MISMATCH")
    case("R5A12B", lambda: consumer.parse_unittest_skip_reasons(
         "test_a (T.test_a) ... skipped 'known reason'\n"
         "skipped \"class reason\"\n"
         "test_b (T.test_b) ... ok\n") == ["known reason", "class reason"] and
         result_counts([{"pass": True}, {"pass": False}]) ==
         {"total": 2, "passed": 1, "failed": 1, "skipped": 0})

    closure_root = session / "closure"
    closure_root.mkdir()
    (closure_root / "file").write_bytes(b"one")
    first = producer.lstat_closure(closure_root)
    case("R5A13", lambda: producer.lstat_closure(closure_root) == first)
    (closure_root / "file").write_bytes(b"two")
    case("R5A14", lambda: producer.lstat_closure(closure_root)["sha256"] != first["sha256"])
    (closure_root / "one").write_bytes(b"same")
    (closure_root / "two").write_bytes(b"same")
    (closure_root / "link").symlink_to("one")
    link_one = producer.lstat_closure(closure_root)["sha256"]
    (closure_root / "link").unlink()
    (closure_root / "link").symlink_to("two")
    case("R5A15", lambda: producer.lstat_closure(closure_root)["sha256"] != link_one)
    outside = session / "outside"
    outside.write_bytes(b"escape")
    (closure_root / "escape").symlink_to(outside)
    case("R5A16", lambda: producer.lstat_closure(closure_root), "RuntimeError")
    (closure_root / "escape").unlink()
    before_mode = producer.lstat_closure(closure_root)["sha256"]
    (closure_root / "file").chmod(0o755)
    case("R5A17", lambda: producer.lstat_closure(closure_root)["sha256"] != before_mode)

    declared = {"nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "edges": [{"from": "a", "to": "b"},
                          {"from": "b", "to": "c"}]}
    journal = [{"stage_id": "a", "dependency_ids": [], "exit_code": 0},
               {"stage_id": "b", "dependency_ids": ["a"], "exit_code": 0},
               {"stage_id": "c", "dependency_ids": ["b"], "exit_code": 0}]
    case("R5A18", lambda: exact_observed_dag(journal, declared)["edge_count"] == 2)
    case("R5A19", lambda: exact_observed_dag(journal[:-1], declared),
         "OBSERVED_DAG_INCOMPLETE")
    missing_edge = [dict(row) for row in journal]
    missing_edge[2] = {**missing_edge[2], "dependency_ids": []}
    case("R5A20", lambda: exact_observed_dag(missing_edge, declared),
         "OBSERVED_DAG_INCOMPLETE")
    extra_edge = [dict(row) for row in journal]
    extra_edge[2] = {**extra_edge[2], "dependency_ids": ["a", "b"]}
    case("R5A21", lambda: exact_observed_dag(extra_edge, declared),
         "OBSERVED_DAG_INCOMPLETE")
    future = [*journal[:-1], {**journal[-1], "exit_code": 1}]
    case("R5A22", lambda: exact_observed_dag(future, declared),
         "OBSERVED_DAG_INCOMPLETE")
    cyclic = {"nodes": declared["nodes"], "edges": [*declared["edges"],
              {"from": "c", "to": "a"}]}
    cyclic_journal = [{"stage_id": "a", "dependency_ids": ["c"], "exit_code": 0},
                      journal[1], journal[2]]
    case("R5A23", lambda: exact_observed_dag(cyclic_journal, cyclic),
         "OBSERVED_DAG_INCOMPLETE")

    baseline = {name: sha((repo / "assets/simulator-baseline" / name).read_bytes())
                for name in ("top.ppm", "bottom.ppm", "trace.json")}
    case("R5A24", lambda: baseline == {
        "top.ppm": "4a80c15cd28f7683506feb125162cae3d88066499be1f060655cfd068431e8f7",
        "bottom.ppm": "8f5bebc5c546bdafb26cfe3c2d3351664e9d4c8eb2c7d915e34d5894d0e7061f",
        "trace.json": "3bef0ea12d465e634cdc2c489dfe332e1fcafc93f2a9cc2d673ed692098404c8"})
    pixel = bytearray((repo / "assets/simulator-baseline/bottom.ppm").read_bytes())
    pixel[-1] ^= 1
    case("R5A25", lambda: sha(bytes(pixel)) != baseline["bottom.ppm"])
    latin = session / "paths/tool"
    greek = session / "paths/t\u03bfol"
    latin.parent.mkdir()
    latin.write_bytes(b"same")
    greek.write_bytes(b"same")
    greek_rows = producer.lstat_closure(latin.parent)["nodes"]
    case("R5A26", lambda: {row["path"] for row in greek_rows
                            if row["type"] == "regular"} == {"tool", "t\u03bfol"})
    case("R5A27", lambda: no_symlink_chain(session / "new/child") and
         paths_overlap(session / "nested", session) and
         not paths_overlap(session, repo))

    git_repo = session / "git-source"
    subprocess.run(["/usr/bin/git", "init", "-q", str(git_repo)], check=True)
    for key, value in (("user.name", "R5"), ("user.email", "r5@example.invalid")):
        subprocess.run(["/usr/bin/git", "-C", str(git_repo), "config", key, value], check=True)
    (git_repo / "f").write_text("root")
    subprocess.run(["/usr/bin/git", "-C", str(git_repo), "add", "f"], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(git_repo), "commit", "-qm", "root"], check=True)
    root_oid = subprocess.check_output(["/usr/bin/git", "-C", str(git_repo),
                                        "rev-parse", "HEAD"], text=True).strip()
    root_branch = subprocess.check_output(["/usr/bin/git", "-C", str(git_repo),
                                           "branch", "--show-current"], text=True).strip()
    subprocess.run(["/usr/bin/git", "-C", str(git_repo), "switch", "-qc", "sibling"], check=True)
    (git_repo / "f").write_text("sibling")
    subprocess.run(["/usr/bin/git", "-C", str(git_repo), "commit", "-qam", "sibling"], check=True)
    sibling_oid = subprocess.check_output(["/usr/bin/git", "-C", str(git_repo),
                                           "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["/usr/bin/git", "-C", str(git_repo), "switch", "-q", root_branch], check=True)
    (git_repo / "f").write_text("head")
    subprocess.run(["/usr/bin/git", "-C", str(git_repo), "commit", "-qam", "head"], check=True)
    head_oid = subprocess.check_output(["/usr/bin/git", "-C", str(git_repo),
                                        "rev-parse", "HEAD"], text=True).strip()
    bundle = session / "candidate.bundle"
    subprocess.run(["/usr/bin/git", "-C", str(git_repo), "bundle", "create",
                    str(bundle), "HEAD"], check=True)
    detached = session / "detached"
    subprocess.run(["/usr/bin/git", "clone", "-q", str(bundle), str(detached)], check=True)
    subprocess.run(["/usr/bin/git", "-C", str(detached), "checkout", "-q", "--detach", head_oid], check=True)
    closure = consumer.raw_ancestry_commitment("/usr/bin/git", detached,
                                               head_oid, [sibling_oid])
    sibling_probe = subprocess.run(["/usr/bin/git", "-C", str(detached),
                                    "cat-file", "-e", sibling_oid + "^{commit}"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    case("R5A28", lambda: closure["forbidden_intersection"] == [] and
         sibling_probe.returncode != 0 and root_oid in closure["first_parent_chain"])
    missing_repo = session / "missing-parent"
    shutil.copytree(git_repo, missing_repo)
    loose = missing_repo / ".git/objects" / root_oid[:2] / root_oid[2:]
    loose.unlink()
    case("R5A29", lambda: consumer.raw_ancestry_commitment(
         "/usr/bin/git", missing_repo, head_oid, []), "ANCESTRY_OBJECT_UNREADABLE")

    semantic_left = {"review_session_id": "1" * 32,
                     "session_root": "/independent/a/session",
                     "started_at": "2026-09-04T01:02:03.100000Z",
                     "elapsed": "1.25s", "verdict": "PASS", "selected": 149,
                     "artifact": "/independent/a/session/result.json"}
    semantic_right = {"review_session_id": "2" * 32,
                      "session_root": "/independent/b/session",
                      "started_at": "2026-09-04T09:08:07.900000Z",
                      "elapsed": "9.75s", "verdict": "PASS", "selected": 149,
                      "artifact": "/independent/b/session/result.json"}
    case("R11A30", lambda: context.compare_evidence(
         "validation.protocol_self_test.result_sha256",
         semantic_left, semantic_right,
         {"RUN_ROOT": "/independent/a/session"},
         {"RUN_ROOT": "/independent/b/session"})["status"] == "PASS")
    case("R11A31", lambda: context.compare_evidence(
         "validation.selected_python_ids", "deterministic-byte-a",
         "deterministic-byte-b", {"RUN_ROOT": "/a"},
         {"RUN_ROOT": "/b"})["status"] == "FAIL")
    case("R11A32", lambda: context.require_evidence_class(
         "validation.official_fresh_chain.verified_invocation_sha256",
         "CONTENT_DETERMINISTIC"), "RuntimeError")

    counts = result_counts(results)
    summary = {"schema": "cth3ds.runtime-core-c3-r11-self-test/v1",
               "session_root": str(session),
               "verified_invocation_sha256": context.digest,
               "evidence_field_contract": context.evidence_contract(),
               **counts, "cases": results}
    out = out_path.absolute()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(canonical(summary))
    persisted = json.loads(out.read_bytes())
    persisted_counts = {key: persisted[key]
                        for key in ("total", "passed", "failed", "skipped")}
    if persisted_counts != counts or persisted["passed"] + persisted["failed"] != \
            persisted["total"] or min(persisted_counts.values()) < 0:
        raise RuntimeError("persisted self-test summary counts are inconsistent")
    print(json.dumps({"protocol_self_test": "PASS"
                      if counts["failed"] == 0 else "FAIL", **counts,
                      "result": str(out)}, sort_keys=True))
    return 0 if counts["failed"] == 0 else 2


def matrix_closed(invocation: Any, producer_module: Any, consumer_module: Any,
                  argv: list[str]) -> int:
    require_verified_invocation(invocation, ("fresh-chain", "_case-evaluate"))
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--canonical-run-root", type=Path, required=True)
    parser.add_argument("--canonical-facts", type=Path, required=True)
    parser.add_argument("--expected-facts-sha256", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--expected-policy-sha256", required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--expected-matrix-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--review-session-id", required=True)
    parser.add_argument("--closure-fixture-root", type=Path, required=True)
    parser.add_argument("--expected-closure-fixture-sha256", required=True)
    parser.add_argument("--fixture-consumption-state", type=Path, required=True)
    parser.add_argument("--execution-journal", type=Path)
    args = parser.parse_args(argv)
    matrix_raw = args.matrix.resolve(strict=True).read_bytes()
    if args.expected_matrix_sha256 != MATRIX_SHA256 or sha(matrix_raw) != MATRIX_SHA256:
        raise RuntimeError("matrix hash mismatch")
    matrix = json.loads(matrix_raw)
    if matrix["fixed_total"] != 60 or matrix["case_id_set"] != "E01..E60" or \
       [item["id"] for item in matrix["cases"]] != \
       [f"E{index:02d}" for index in range(1, 61)]:
        raise RuntimeError("matrix identity mismatch")
    candidate = args.candidate_root.resolve(strict=True)
    canonical_root = args.canonical_run_root.resolve(strict=True)
    facts_path = args.canonical_facts.resolve(strict=True)
    facts_raw = facts_path.read_bytes()
    if sha(facts_raw) != args.expected_facts_sha256:
        raise RuntimeError("facts hash mismatch")
    facts = load(facts_path)
    run_manifest_path = facts_path.parent / "run-manifest.json"
    run_manifest_raw = run_manifest_path.read_bytes()
    run_manifest = load(run_manifest_path)
    policy_path = args.policy.resolve(strict=True)
    policy_raw = policy_path.read_bytes()
    if sha(policy_raw) != args.expected_policy_sha256:
        raise RuntimeError("policy hash mismatch")
    policy = load(policy_path)
    if policy.get("fresh_chain", {}).get("review_session_id") != \
       args.review_session_id:
        raise RuntimeError("policy review session mismatch")
    acceptance = policy.get("acceptance_inputs", {})
    runner_sha = sha(Path(__file__).resolve().read_bytes())
    consumer_sha = sha((candidate / "scripts/consume_runtime_core_v2.py").read_bytes())
    if runner_sha != acceptance.get("runner_sha256"):
        raise RuntimeError("runner hash mismatch")
    if consumer_sha != acceptance.get("fact_consumer_sha256"):
        raise RuntimeError("fact consumer hash mismatch")
    if facts.get("run_manifest_sha256") != sha(run_manifest_raw):
        raise RuntimeError("facts/run-manifest mismatch")
    output = args.out.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("matrix output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = args.receipt.resolve()
    if receipt_path.exists():
        raise RuntimeError("receipt output already exists")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    verifier = producer_module
    consumer = candidate / "scripts/consume_runtime_core_v2.py"
    fixture_root = args.closure_fixture_root.resolve(strict=True)
    fixture_manifest = load(fixture_root / "fixture-manifest.json")
    baseline_fixture_command = closure_verify_command(
        candidate, fixture_root, args.expected_closure_fixture_sha256,
        args.review_session_id, facts, sha(run_manifest_raw), sha(facts_raw),
        args.expected_policy_sha256, args.fixture_consumption_state)
    baseline_started = utc_now()
    baseline_probe = output / "fixture-consume-probe"
    baseline_process = run_child_probe(invocation, "_closure-verify", {
        "schema": "cth3ds.verifier-internal-request/v1",
        "argv": baseline_fixture_command[2:]}, baseline_probe)
    if args.execution_journal:
        append_journal(args.execution_journal, "r4.n50_closure_cases.fixture-consume",
            ["r4.n42_fixture_verify"], list(baseline_process.args), baseline_started,
            utc_now(), baseline_process.returncode, baseline_process.stdout,
            baseline_process.stderr, baseline_probe)
    if baseline_process.returncode != 0:
        raise RuntimeError("baseline fixture consumption failed: " +
                           baseline_process.stderr.decode(errors="replace"))
    results = []
    with tempfile.TemporaryDirectory(prefix="cth3ds-c3-matrix-") as tmp:
        tmp_root = Path(tmp).resolve(strict=True)
        for case in matrix["cases"]:
            case_id = case["id"]
            case_temp = tmp_root / case_id
            if case_id in CLOSURE_CASES:
                private_fixture = case_temp / "closure-fixture"
                shutil.copytree(fixture_root, private_fixture, copy_function=shutil.copy2)
                digest, private_run_sha = mutate_closure_fixture(case_id, private_fixture)
                command = closure_verify_command(
                    candidate, private_fixture, digest, args.review_session_id,
                    facts, private_run_sha, sha(facts_raw), args.expected_policy_sha256)
                cleanup_marker = None
            else:
                policy, manifest, policy_path = clone_case(
                    canonical_root, args.policy.resolve(strict=True),
                    case_temp / "run", candidate, False)
                case_candidate, cleanup_marker, stale_hash = mutate(
                    case_id, policy, manifest, policy_path, candidate,
                    case_temp / "run", verifier, consumer_module, case_temp)
                policy_hash = stale_hash or sha(policy_path.read_bytes())
                command = ["IN_PROCESS", str(consumer),
                    "--case-evaluate",
                    "--candidate-root", str(case_candidate),
                    "--evidence-root", str(case_temp / "run/evidence_raw"),
                    "--policy", str(policy_path),
                    "--expected-policy-sha256", policy_hash,
                    "--seal-root", str(case_temp / "run/seal")]
                if case_id == "E40":
                    command += ["--test-rename-artifact", "cpp-stdout"]
            started = utc_now()
            case_output = output / "cases" / case_id
            case_output.mkdir(parents=True)
            if case_id in CLOSURE_CASES:
                process = run_child_probe(invocation, "_closure-verify", {
                    "schema": "cth3ds.verifier-internal-request/v1",
                    "argv": command[2:]}, case_output)
            else:
                process = run_child_probe(invocation, "_case-evaluate", {
                    "schema": "cth3ds.verifier-internal-request/v1",
                    "argv": command[2:]}, case_output)
            command = list(process.args)
            if cleanup_marker:
                Path(cleanup_marker).unlink(missing_ok=True)
            stdout_path = case_output / "stdout"
            stderr_path = case_output / "stderr"
            stdout_path.write_bytes(process.stdout)
            stderr_path.write_bytes(process.stderr)
            if args.execution_journal:
                append_journal(args.execution_journal, "r4.n50_matrix.case." + case_id,
                    ["r4.n42_fixture_verify" if case_id in CLOSURE_CASES else
                     "r4.n30_derive"], command, started, utc_now(),
                    process.returncode, process.stdout, process.stderr, case_output)
            payload = None
            text = process.stderr.decode(errors="replace").strip().splitlines()
            if text:
                try:
                    payload = json.loads(text[-1])
                except json.JSONDecodeError:
                    payload = None
            if process.returncode == 0:
                actual_gate, actual_product = "PASS", "FAIL"
                actual_review, actual_code = "ACCEPT_C3_EVIDENCE_PROTOCOL", None
            else:
                actual_gate = payload.get("gate") if payload else None
                actual_product = payload.get("product") if payload else None
                actual_review = payload.get("review") if payload else None
                actual_code = payload.get("failure_code") if payload else None
            passed = (
                process.returncode == case["expected_consumer_exit"] and
                actual_gate == case["expected_gate_verdict"] and
                actual_product == case["expected_product_verdict"] and
                actual_review == case["expected_review_verdict"] and
                actual_code == case["expected_failure_code"]
            )
            mutation_raw = canonical({"id": case_id,
                                      "mutation": case["mutation"]})
            (case_output / "mutation.json").write_bytes(mutation_raw)
            results.append({"id": case_id, "pass": passed,
                "actual_exit": process.returncode, "actual_gate": actual_gate,
                "actual_product": actual_product, "actual_review": actual_review,
                "actual_failure_code": actual_code,
                "expected_exit": case["expected_consumer_exit"],
                "expected_gate": case["expected_gate_verdict"],
                "expected_product": case["expected_product_verdict"],
                "expected_review": case["expected_review_verdict"],
                "expected_failure_code": case["expected_failure_code"],
                "mutation_sha256": sha(mutation_raw),
                "stdout_sha256": sha(process.stdout),
                "stderr_sha256": sha(process.stderr)})
            if case_temp.exists():
                writable(case_temp)
                shutil.rmtree(case_temp)
    passed = sum(item["pass"] for item in results)
    case_set = {"schema": "cth3ds.runtime-core-matrix-case-set/v1",
                "cases": results}
    case_set_raw = canonical(case_set)
    (output / "case-set.json").write_bytes(case_set_raw)
    summary = {
        "schema": "cth3ds.runtime-core-c3-matrix-result/v2",
        "review_session_id": args.review_session_id,
        "canonical_run_id": facts["run_id"],
        "candidate_identity": facts["candidate_identity_live"],
        "policy_id": facts["policy_id"],
        "policy_sha256": args.expected_policy_sha256,
        "verified_invocation_sha256": invocation.digest,
        "producer_manifest_sha256": facts["producer_manifest_sha256"],
        "run_manifest_sha256": sha(run_manifest_raw),
        "facts_sha256": sha(facts_raw),
        "matrix_sha256": MATRIX_SHA256,
        "runner_sha256": runner_sha,
        "fact_consumer_sha256": consumer_sha,
        "case_set_sha256": sha(case_set_raw),
        "case_id_set": "E01..E60",
        "total": 60, "passed": passed, "failed": 60 - passed,
        "cases": results,
        "closure_fixture": {
            "fixture_id": fixture_manifest["fixture_id"],
            "fixture_manifest_sha256": sha(
                (fixture_root / "fixture-manifest.json").read_bytes()),
            "sha256s_sha256": args.expected_closure_fixture_sha256,
            "consumed_once": True, "final_acceptance_eligible": False,
        },
        "matrix": {"definition_sha256": MATRIX_SHA256, "total": 60,
                   "passed": passed, "failed": 60 - passed},
    }
    summary_raw = canonical(summary)
    (output / "summary.json").write_bytes(summary_raw)
    receipt = {
        "schema": "cth3ds.runtime-core-matrix-receipt/v1",
        "stage_id": "C3-R5",
        "review_session_id": summary["review_session_id"],
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="microseconds").replace("+00:00", "Z"),
        "canonical_run_id": facts["run_id"],
        "candidate_identity": facts["candidate_identity_live"],
        "policy_id": facts["policy_id"],
        "policy_sha256": args.expected_policy_sha256,
        "verified_invocation_sha256": invocation.digest,
        "producer_manifest_sha256": facts["producer_manifest_sha256"],
        "run_manifest_sha256": sha(run_manifest_raw),
        "facts_sha256": sha(facts_raw),
        "matrix_sha256": MATRIX_SHA256,
        "runner_sha256": runner_sha,
        "fact_consumer_sha256": consumer_sha,
        "summary_sha256": sha(summary_raw),
        "case_set_sha256": sha(case_set_raw),
        "case_count": 60,
        "case_id_set": "E01..E60",
        "passed": passed,
        "failed": 60 - passed,
        "cases": results,
        "closure_fixture": summary["closure_fixture"],
        "matrix": summary["matrix"],
    }
    receipt_raw = canonical(receipt)
    receipt_path.write_bytes(receipt_raw)
    rows = []
    for path in sorted((item for item in output.rglob("*") if item.is_file()),
                       key=lambda item: item.relative_to(output).as_posix()):
        if path.name == "SHA256SUMS":
            continue
        rows.append(f"{sha(path.read_bytes())}  {path.relative_to(output).as_posix()}\n")
    (output / "SHA256SUMS").write_text("".join(rows))
    print(json.dumps({"passed": passed, "total": 60,
                      "summary": str(output / "summary.json"),
                      "receipt": str(receipt_path),
                      "receipt_sha256": sha(receipt_raw)},
                     sort_keys=True, separators=(",", ":")))
    return 0 if passed == 60 else 2


def main() -> int:
    print("DIRECT_ENTRY_FORBIDDEN: use scripts/run_verifier_python.sh", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
