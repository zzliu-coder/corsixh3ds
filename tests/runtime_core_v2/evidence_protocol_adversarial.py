#!/usr/bin/env python3
"""Run the frozen 60-case C3 adversarial evidence-protocol matrix."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import Any

MATRIX_SHA256 = "8b7cf0d8e3b3702e9aa3c32aff9d1ed3e363ceab52699539251975a61985060f"
BASE_CASES_SHA256 = "45f7bda680a10c159e70ce15b9389eb7cafc419001af542583fdd5353d319d7f"
R4_CASES_SHA256 = "a4a7160e0dc762599d13a4df721d0d156e2daeea6ce6b8b4226c16f3a4d5dc64"
DAG_SHA256 = "b9be4ec34c97cdb10138354df740ad24143b0e202cc96383006f6ef9ca9b52fa"
CLOSURE_CASES = {"E48", "E49", "E50", "E51", "E60"}
ACTIVE_JOURNAL: Path | None = None


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


def module_from(path: Path):
    spec = importlib.util.spec_from_file_location("c3_verify_for_matrix", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load verifier helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def update_candidate_identity(policy: dict[str, Any], manifest: dict[str, Any],
                              candidate: Path, verifier) -> None:
    head = verifier.git(candidate, "rev-parse", "HEAD^{commit}").decode().strip()
    tree = verifier.git(candidate, "rev-parse", "HEAD^{tree}").decode().strip()
    fp, entries = verifier.fingerprint(candidate, head)
    git_path = next(row["absolute_realpath"] for row in manifest["tools"]
                    if row["role"] == "git")
    ancestry = verifier.reviewer_ancestry_commitment(candidate, head, git_path)
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


def mutate_observation(policy, manifest, role, fn, raw: bytes | None = None):
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
           temp: Path) -> tuple[Path, str | None, str | None]:
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
        update_candidate_identity(policy, manifest, clone, verifier)
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
        def outer_true(root: Path) -> None:
            path = root / "tests/runtime_core_v2/fixtures/no-level/fixture-manifest.json"
            value = load(path)
            value["contains_original_theme_hospital_data"] = True
            path.write_bytes(canonical(value))
        clone = commit_fixture_mutation(candidate, temp, outer_true)
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
        update_candidate_identity(policy, manifest, clone, verifier)
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
                           consume_state: Path | None = None) -> list[str]:
    identity = facts["candidate_identity_live"]
    command = [sys.executable, str(candidate / "scripts/consume_runtime_core_v2.py"),
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


def result_provenance_cases(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
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
    base_finalize = [sys.executable, str(consumer), "--finalize",
        "--candidate-root", str(args.candidate_root), "--facts-root",
        str(args.canonical_facts.parent), "--expected-facts-sha256",
        args.expected_facts_sha256, "--policy", str(args.policy),
        "--expected-policy-sha256", args.expected_policy_sha256,
        "--matrix", str(args.matrix), "--expected-matrix-sha256",
        args.expected_matrix_sha256, "--matrix-root", str(args.matrix_root)]
    results = []
    with tempfile.TemporaryDirectory(prefix="cth3ds-r3-provenance-") as temporary:
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
                command = [sys.executable, str(consumer), "--verify-seal",
                           "--seal-root", str(fixture),
                           "--expected-matrix-receipt-sha256", expected_receipt]
                if case_id != "R3P27":
                    command += ["--expected-seal-root-sha256", expected_seal]
            started = utc_now()
            process = subprocess.run(command, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, check=False,
                                     env={"PATH": "/usr/bin:/bin",
                                          "PYTHONDONTWRITEBYTECODE": "1",
                                          "LC_ALL": "C", "TZ": "UTC"})
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
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            return False
    return True


def paths_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def normalize_candidate_transport(kind: str, source: Path, destination: Path,
                                  expected_sha256: str | None) -> dict[str, Any]:
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
                   stdout: bytes, stderr: bytes, output_root: Path | None) -> None:
    executable = Path(command[0]) if command else Path(__file__)
    executable_sha = sha(executable.read_bytes()) if executable.is_file() else None
    record = {
        "schema": "cth3ds.runtime-core-execution-journal-entry/v1",
        "stage_id": stage_id, "dependency_ids": dependencies,
        "started_at": started, "ended_at": ended,
        "executable_relative_path": (command[1] if len(command) > 1 and
                                     command[0] == sys.executable else
                                     str(command[0]) if command else
                                     "tests/runtime_core_v2/evidence_protocol_adversarial.py"),
        "executable_sha256": executable_sha,
        "argument_roles": [item[2:] for item in command if item.startswith("--")],
        "argv": command, "cwd_realpath": str(Path.cwd().resolve()),
        "exit_code": exit_code, "stdout_sha256": sha(stdout),
        "stderr_sha256": sha(stderr),
        "output_root": str(output_root) if output_root else None,
        "output_digest": tree_digest(output_root) if output_root else sha(b""),
    }
    with path.open("ab") as handle:
        handle.write(canonical(record))


def run_journaled(journal: Path, stage_id: str, dependencies: list[str],
                  command: list[str], output_root: Path | None = None) -> subprocess.CompletedProcess:
    started = utc_now()
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             check=False, cwd=Path.cwd(),
                             env={"PATH": "/opt/devkitpro/devkitARM/bin:/opt/devkitpro/tools/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                                  "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C",
                                  "TZ": "UTC", "DEVKITPRO": "/opt/devkitpro",
                                  "DEVKITARM": "/opt/devkitpro/devkitARM",
                                  "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                                  "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                                  "TMPDIR": "/tmp"})
    append_journal(journal, stage_id, dependencies, command, started, utc_now(),
                   process.returncode, process.stdout, process.stderr, output_root)
    if process.returncode != 0:
        detail = process.stderr.decode(errors="replace") or process.stdout.decode(errors="replace")
        raise FreshChainError("STAGE_FAILED", f"{stage_id}: {detail}")
    return process


def failure_code(process: subprocess.CompletedProcess) -> str | None:
    for raw in reversed(process.stderr.decode(errors="replace").splitlines()):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value.get("failure_code")
    return None


def run_expected(command: list[str], expected_exit: int,
                 expected_code: str | None) -> tuple[bool, dict[str, Any]]:
    started = utc_now()
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             check=False, env={"PATH": "/usr/bin:/bin",
                                               "PYTHONDONTWRITEBYTECODE": "1",
                                               "LC_ALL": "C", "TZ": "UTC"})
    if ACTIVE_JOURNAL:
        append_journal(ACTIVE_JOURNAL, "r4.n81_cycle_acceptance.case",
            ["r4.n80_base_acceptance"], command, started, utc_now(),
            process.returncode, process.stdout, process.stderr, None)
    code = failure_code(process)
    return (process.returncode == expected_exit and code == expected_code,
            {"actual_exit": process.returncode, "actual_failure_code": code,
             "stdout_sha256": sha(process.stdout), "stderr_sha256": sha(process.stderr)})


def replace_argument(command: list[str], flag: str, value: str) -> list[str]:
    result = list(command)
    result[result.index(flag) + 1] = value
    return result


def run_r4_acceptance(args: argparse.Namespace, context: dict[str, Any],
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
        command = context["fresh_command"]
        command = replace_argument(command, "--session-root", str(nonempty.resolve()))
        ok, ev = run_expected(command, 2, "SESSION_ROOT_NOT_EMPTY")
        add("R4C02", ok, "SESSION_ROOT_NOT_EMPTY", ev)
    seal_obs = context["seal_observations"]
    add("R4C03", len(seal_obs) == 3 and all(row["entry_count"] == 0 for row in seal_obs),
        "CANONICAL_SEAL_RESERVED_EMPTY", seal_obs)
    fresh_policy = context["policy"]["fresh_chain"]
    add("R4C04", fresh_policy["forbidden_prior_artifact_roles"] ==
        ["facts", "closure_fixture", "matrix_receipt", "final_seal"],
        "NO_PRIOR_RUN_REFERENCE", fresh_policy)
    ok, ev = run_expected(base_verify, 0, None)
    add("R4C05", ok, "CLOSURE_FIXTURE_VALID", ev)
    wrong = "f" * 32 if facts["run_id"] != "f" * 32 else "e" * 32
    ok, ev = run_expected(replace_argument(base_verify,
        "--expected-canonical-run-id", wrong), 2, "CLOSURE_FIXTURE_RUN_ID_MISMATCH")
    add("R4C06", ok, "CLOSURE_FIXTURE_RUN_ID_MISMATCH", ev)
    wrong40 = "f" * 40 if facts["candidate_identity_live"]["commit"] != "f" * 40 else "e" * 40
    ok, ev = run_expected(replace_argument(base_verify,
        "--expected-candidate-head", wrong40), 2, "CLOSURE_FIXTURE_CANDIDATE_MISMATCH")
    add("R4C07", ok, "CLOSURE_FIXTURE_CANDIDATE_MISMATCH", ev)
    ok, ev = run_expected(replace_argument(base_verify,
        "--expected-fixture-policy-id", "c3-" + wrong), 2,
        "CLOSURE_FIXTURE_POLICY_MISMATCH")
    add("R4C08", ok, "CLOSURE_FIXTURE_POLICY_MISMATCH", ev)
    ok, ev = run_expected(replace_argument(base_verify,
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
        ok, ev = run_expected(command, 2, "CLOSURE_FIXTURE_SCHEMA_INVALID")
        # Schema and semantic guards are both valid fail-closed frontiers.
        if ev["actual_failure_code"] == "CLOSURE_FIXTURE_FINAL_ACCEPT_FORBIDDEN":
            ok = True
        add("R4C10", ok, "CLOSURE_FIXTURE_FINAL_ACCEPT_FORBIDDEN", ev)
    command = base_verify + ["--fixture-consumption-state",
        str(context["consumption_state"]), "--consume-closure-fixture"]
    ok, ev = run_expected(command, 2, "CLOSURE_FIXTURE_ALREADY_CONSUMED")
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
        ok, ev = run_expected(command, 2, "MATRIX_CASE_FAILED")
        ev["final_seal_entry_count"] = len(list(reject_seal.iterdir()))
        add("R4C17", ok and ev["final_seal_entry_count"] == 0,
            "MATRIX_CASE_FAILED", ev)
    command = [sys.executable, str(candidate / "scripts/consume_runtime_core_v2.py"),
               "--verify-seal", "--seal-root", str(fixture)]
    ok, ev = run_expected(command, 2, "FINAL_ACCEPTANCE_FIXTURE_FORBIDDEN")
    add("R4C18", ok, "FINAL_ACCEPTANCE_FIXTURE_FORBIDDEN", ev)
    normalized = context["normalized_order"]
    prefix_equal = normalized == context["declared_order"][:len(normalized)]
    add("R4C19", prefix_equal,
        "EXECUTION_ORDER_IDENTICAL", {"equal": prefix_equal,
                                      "normalized_sha256": sha(canonical(normalized))})
    with tempfile.TemporaryDirectory(prefix="cth3ds-r4-overlap-") as temporary:
        overlap = candidate / ".r4-overlap-must-not-create"
        command = replace_argument(context["fresh_command"], "--session-root", str(overlap))
        ok, ev = run_expected(command, 2, "INPUT_OUTPUT_OVERLAP")
        add("R4C20", ok and not overlap.exists(), "INPUT_OUTPUT_OVERLAP", ev)
    command = [sys.executable, str(candidate / "scripts/consume_runtime_core_v2.py"),
        "--matrix-evaluate", "--candidate-root", str(candidate),
        "--evidence-root", str(context["canonical_root"] / "evidence_raw"),
        "--policy", str(context["policy_path"]),
        "--expected-policy-sha256", context["policy_sha"],
        "--seal-root", str(context["canonical_seal"])]
    ok, ev = run_expected(command, 2, "CANONICAL_SEAL_RESERVED_EMPTY")
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


def fresh_chain(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh-chain", action="store_true")
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--candidate-input-kind", choices=["detached-repo", "head-bundle"],
                        default="detached-repo")
    parser.add_argument("--candidate-input-path", type=Path)
    parser.add_argument("--expected-candidate-input-sha256")
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--deps-prefix", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--expected-matrix-sha256", required=True)
    parser.add_argument("--base-acceptance-cases", type=Path, required=True)
    parser.add_argument("--expected-base-cases-sha256", required=True)
    parser.add_argument("--cycle-acceptance-cases", type=Path, required=True)
    parser.add_argument("--expected-cycle-cases-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        candidate_input = args.candidate_input_path or args.candidate_root
        if candidate_input is None:
            raise FreshChainError("CLI_REQUIRED_ARGUMENT", "candidate transport missing")
        candidate_source = candidate_input.resolve(strict=True)
        archive = args.archive.resolve(strict=True)
        deps = args.deps_prefix.resolve(strict=True)
        matrix = args.matrix.resolve(strict=True)
        base_cases = args.base_acceptance_cases.resolve(strict=True)
        cycle_cases = args.cycle_acceptance_cases.resolve(strict=True)
        dag_path = (cycle_cases.parent / "execution-dag.json").resolve(strict=True)
        session = args.session_root.absolute()
        if not no_symlink_chain(args.session_root.absolute()):
            raise FreshChainError("INPUT_OUTPUT_OVERLAP", "session path contains symlink")
        executing_candidate = Path(__file__).resolve().parents[2]
        if paths_overlap(session, executing_candidate):
            raise FreshChainError(
                "INPUT_OUTPUT_OVERLAP",
                "session overlaps the candidate executing the Fresh Chain")
        external = {"candidate_transport": candidate_source, "archive": archive,
                    "deps_prefix": deps,
                    "frozen_matrix": matrix, "base_acceptance_cases": base_cases,
                    "r4_acceptance_cases": cycle_cases}
        for left_name, left in external.items():
            if paths_overlap(session, left):
                raise FreshChainError("INPUT_OUTPUT_OVERLAP",
                                      f"session overlaps {left_name}")
        initial_count = len(list(session.iterdir())) if session.exists() else 0
        if session.exists() and (not session.is_dir() or initial_count != 0):
            raise FreshChainError("SESSION_ROOT_NOT_EMPTY", "session root must start empty")
        if args.expected_matrix_sha256 != MATRIX_SHA256 or sha(matrix.read_bytes()) != MATRIX_SHA256:
            raise FreshChainError("FROZEN_INPUT_HASH_MISMATCH", "matrix hash mismatch")
        if args.expected_base_cases_sha256 != BASE_CASES_SHA256 or \
           sha(base_cases.read_bytes()) != BASE_CASES_SHA256:
            raise FreshChainError("FROZEN_INPUT_HASH_MISMATCH", "base cases hash mismatch")
        if args.expected_cycle_cases_sha256 != R4_CASES_SHA256 or \
           sha(cycle_cases.read_bytes()) != R4_CASES_SHA256 or \
           sha(dag_path.read_bytes()) != DAG_SHA256:
            raise FreshChainError("FROZEN_INPUT_HASH_MISMATCH", "R4 input hash mismatch")
        session.mkdir(parents=True, exist_ok=True)
        preflight_root = session / "00-preflight"
        preflight_root.mkdir()
        transport = normalize_candidate_transport(
            args.candidate_input_kind, candidate_source,
            preflight_root / "candidate-detached",
            args.expected_candidate_input_sha256)
        candidate = Path(transport["normalized_repo_realpath"])
        journal = preflight_root / "execution-journal.jsonl"
        review_session_id = uuid.uuid4().hex
        input_identity = {"schema": "cth3ds.runtime-core-r5-input-identity/v1",
            "review_session_id": review_session_id, "session_root_realpath": str(session),
            "initial_entry_count": initial_count,
            "inputs": {role: {"realpath": str(path),
                "sha256": sha(path.read_bytes()) if path.is_file() else tree_digest(path),
                "readonly": not os.access(path, os.W_OK)} for role, path in external.items()},
            "candidate_transport": transport,
            "execution_dag": {"realpath": str(dag_path), "sha256": DAG_SHA256}}
        (preflight_root / "input-identity.json").write_bytes(canonical(input_identity))
        separation = {"schema": "cth3ds.runtime-core-r4-path-separation/v1",
                      "status": "PASS", "session_root": str(session),
                      "external_realpaths": [str(path) for path in external.values()]}
        (preflight_root / "path-separation.json").write_bytes(canonical(separation))
        append_journal(journal, "r4.n00_preflight", [], [str(Path(__file__).resolve()),
            "--fresh-chain"], utc_now(), utc_now(), 0, canonical(input_identity), b"",
            preflight_root)
        policy_root = session / "10-policy"
        canonical_root = session / "20-canonical-run"
        verifier_script = candidate / "scripts/verify_runtime_core_v2.py"
        runner_script = candidate / "tests/runtime_core_v2/evidence_protocol_adversarial.py"
        consumer = candidate / "scripts/consume_runtime_core_v2.py"
        policy_command = [sys.executable, str(verifier_script), "policy",
            "--repo", str(candidate), "--run-root", str(canonical_root),
            "--reviewer-root", str(policy_root), "--archive", str(archive),
            "--deps-prefix", str(deps), "--review-session-id", review_session_id,
            "--session-root", str(session)]
        run_journaled(journal, "r4.n10_policy", ["r4.n00_preflight"],
                      policy_command, policy_root)
        policy_path = policy_root / "review-policy.json"
        policy_sha = sha(policy_path.read_bytes())
        policy = load(policy_path)
        produce_command = [sys.executable, str(verifier_script), "produce",
                           "--policy", str(policy_path),
                           "--expected-policy-sha256", policy_sha]
        run_journaled(journal, "r4.n20_produce", ["r4.n10_policy"],
                      produce_command, canonical_root / "evidence_raw")
        producer_manifest = load(canonical_root / "evidence_raw/producer-manifest.json")
        artifacts_by_id = {row["artifact_id"]: row
                           for row in producer_manifest["artifacts"]}
        policy_roots = roots(policy)
        for invocation in producer_manifest["invocations"]:
            stdout_item = artifacts_by_id[invocation["stdout_artifact_id"]]
            stderr_item = artifacts_by_id[invocation["stderr_artifact_id"]]
            stdout_bytes = (policy_roots[stdout_item["root_id"]] /
                            stdout_item["relative_path"]).read_bytes()
            stderr_bytes = (policy_roots[stderr_item["root_id"]] /
                            stderr_item["relative_path"]).read_bytes()
            append_journal(journal, "r4.n20_produce.invocation." + invocation["role"],
                ["r4.n10_policy"], invocation["argv"], invocation["started_at"],
                invocation["finished_at"], invocation["exit_code"], stdout_bytes,
                stderr_bytes, None)
        facts_root = session / "30-facts"
        canonical_seal = canonical_root / "seal"
        derive_command = [sys.executable, str(consumer), "--derive",
            "--candidate-root", str(candidate), "--evidence-root",
            str(canonical_root / "evidence_raw"), "--policy", str(policy_path),
            "--expected-policy-sha256", policy_sha, "--seal-root", str(canonical_seal),
            "--facts-root", str(facts_root)]
        run_journaled(journal, "r4.n30_derive", ["r4.n20_produce"],
                      derive_command, facts_root)
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
        fixture_command = [sys.executable, str(runner_script),
            "--prepare-closure-fixture", "--candidate-root", str(candidate),
            "--canonical-facts-root", str(facts_root), "--policy", str(policy_path),
            "--expected-policy-sha256", policy_sha, "--matrix", str(matrix),
            "--expected-matrix-sha256", MATRIX_SHA256,
            "--review-session-id", review_session_id, "--out", str(fixture)]
        run_journaled(journal, "r4.n40_fixture",
                      ["r4.n30_derive", "r4.n35_seal_empty"],
                      fixture_command, fixture)
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
        run_journaled(journal, "r4.n42_fixture_verify", ["r4.n41_fixture_anchor"],
                      fixture_verify, fixture)
        observe("after_fixture")
        matrix_root = session / "50-matrix"
        receipt = matrix_root / "receipt.json"
        consumption_state = matrix_root / "fixture-consumption.json"
        matrix_command = [sys.executable, str(runner_script),
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
        run_journaled(journal, "r4.n50_closure_cases", ["r4.n42_fixture_verify"],
                      matrix_command, matrix_root)
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
        finalize_command = [sys.executable, str(consumer), "--finalize",
            "--candidate-root", str(candidate), "--facts-root", str(facts_root),
            "--expected-facts-sha256", facts_sha, "--policy", str(policy_path),
            "--expected-policy-sha256", policy_sha, "--matrix", str(matrix),
            "--expected-matrix-sha256", MATRIX_SHA256, "--matrix-root", str(matrix_root),
            "--matrix-receipt", str(receipt), "--expected-matrix-receipt-sha256",
            receipt_sha, "--closure-fixture-root", str(fixture),
            "--expected-closure-fixture-sha256", fixture_digest,
            "--seal-root", str(final_seal)]
        run_journaled(journal, "r4.n60_finalize",
                      ["r4.n52_receipt_anchor", "r4.n41_fixture_anchor"],
                      finalize_command, final_seal)
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
        verify_command = [sys.executable, str(consumer), "--verify-seal",
            "--seal-root", str(final_seal), "--expected-seal-root-sha256", final_digest,
            "--expected-matrix-receipt-sha256", receipt_sha]
        verify_process = run_journaled(journal, "r4.n70_semantic_verify",
            ["r4.n61_final_anchor"], verify_command, verification)
        (verification / "stdout.jsonl").write_bytes(verify_process.stdout)
        acceptance_root = session / "80-acceptance"
        base_output = acceptance_root / "base32"
        base_command = [sys.executable, str(runner_script),
            "--result-provenance-cases", "--candidate-root", str(candidate),
            "--canonical-run-root", str(canonical_root), "--canonical-facts", str(facts_path),
            "--expected-facts-sha256", facts_sha, "--policy", str(policy_path),
            "--expected-policy-sha256", policy_sha, "--matrix", str(matrix),
            "--expected-matrix-sha256", MATRIX_SHA256, "--matrix-root", str(matrix_root),
            "--receipt", str(receipt), "--expected-receipt-sha256", receipt_sha,
            "--seal-root", str(final_seal), "--expected-seal-sha256", final_digest,
            "--cases", str(base_cases), "--out", str(base_output),
            "--execution-journal", str(journal)]
        run_journaled(journal, "r4.n80_base_acceptance", ["r4.n70_semantic_verify"],
                      base_command, base_output)
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
        context = {"candidate": candidate, "fixture": fixture, "facts": facts,
            "fixture_digest": fixture_digest, "review_session_id": review_session_id,
            "run_sha": run_sha, "facts_sha": facts_sha, "policy_sha": policy_sha,
            "preflight": input_identity, "seal_observations": seal_observations,
            "policy": policy, "matrix_summary": load(matrix_root / "summary.json"),
            "consumption_state": consumption_state, "normalized_order": normalized_order,
            "declared_order": declared_order, "observed_edges": observed_edges,
            "dag": dag, "matrix_root": matrix_root, "receipt": receipt,
            "finalize_command": finalize_command, "canonical_root": canonical_root,
            "canonical_seal": canonical_seal, "policy_path": policy_path,
            "journal": journal,
            "fresh_command": [sys.executable, str(runner_script), *argv]}
        r4_output = acceptance_root / "r4-additive22"
        r4_summary = run_r4_acceptance(args, context, r4_output)
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
                exact = (value.get("run_id") == process_run_id and
                    obs.get("entries_after") - obs.get("entries_before") == 1 and
                    obs.get("leases_after") - obs.get("leases_before") == 1 and
                    obs.get("allocation_records_after") -
                        obs.get("allocation_records_before") == 1 and
                    obs.get("pool_bytes_after")[2] - obs.get("pool_bytes_before")[2] == 64 and
                    obs.get("backend_bytes_after")[0] -
                        obs.get("backend_bytes_before")[0] == 64 and
                    obs.get("escaped_lease_valid_after") is True and
                    obs.get("state_after") == "MENU_STABLE" and
                    obs.get("transition_active_after") is False)
                row = {"profile": profile, "process_index": index + 1,
                       "run_id": process_run_id, "exit_code": process.returncode,
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
            "regular_reconciliation_is_diagnostic_only": True,
            "status": "PASS" if all(row["exact_red_fact"] for row in h2_rows) else "FAIL"}
        (h2_evidence / "summary.json").write_bytes(canonical(h2_gate))
        if h2_gate["status"] != "PASS" or h2_gate["independent_process_count"] != 40:
            raise FreshChainError("H2_EXACT20_GATE_FAILED", "H2 exact20 process gate failed")
        base_summary = load(base_output / "summary.json")
        result = {"schema": "cth3ds.runtime-core-c3-r5-fresh-chain-result/v1",
            "stage_id": "C3-R5", "review_session_id": review_session_id,
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
    except FreshChainError as error:
        print(json.dumps({"fresh_chain": "FAIL", "c3": "NOT_PROVEN",
            "failure_code": error.code, "detail": str(error)},
            sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 2


def protocol_self_test(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-self-test", action="store_true")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = args.repo.resolve(strict=True)
    session = args.session_root.absolute()
    if session.exists() and (not session.is_dir() or any(session.iterdir())):
        raise RuntimeError("self-test session must be new and empty")
    if not no_symlink_chain(session):
        raise RuntimeError("self-test session path contains symlink")
    session.mkdir(parents=True, exist_ok=True)
    consumer = module_from(repo / "scripts/consume_runtime_core_v2.py")
    producer = module_from(repo / "scripts/verify_runtime_core_v2.py")
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

    def raw_payload(parents: list[str] | None = None, duplicate_tree: bool = False,
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

    counts = result_counts(results)
    summary = {"schema": "cth3ds.runtime-core-c3-r5-self-test/v1",
               "session_root": str(session), **counts, "cases": results}
    out = args.out.absolute()
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


def main() -> int:
    if "--protocol-self-test" in sys.argv:
        return protocol_self_test(sys.argv[1:])
    if "--fresh-chain" in sys.argv:
        return fresh_chain(sys.argv[1:])
    if "--prepare-closure-fixture" in sys.argv:
        return prepare_closure_fixture(sys.argv[1:])
    if "--result-provenance-cases" in sys.argv:
        return result_provenance_cases(sys.argv[1:])
    parser = argparse.ArgumentParser()
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
    args = parser.parse_args()
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
    verifier = module_from(candidate / "scripts/verify_runtime_core_v2.py")
    consumer = candidate / "scripts/consume_runtime_core_v2.py"
    fixture_root = args.closure_fixture_root.resolve(strict=True)
    fixture_manifest = load(fixture_root / "fixture-manifest.json")
    baseline_fixture_command = closure_verify_command(
        candidate, fixture_root, args.expected_closure_fixture_sha256,
        args.review_session_id, facts, sha(run_manifest_raw), sha(facts_raw),
        args.expected_policy_sha256, args.fixture_consumption_state)
    baseline_started = utc_now()
    baseline_process = subprocess.run(
        baseline_fixture_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
                          "LC_ALL": "C", "TZ": "UTC"})
    if args.execution_journal:
        append_journal(args.execution_journal, "r4.n50_closure_cases.fixture-consume",
            ["r4.n42_fixture_verify"], baseline_fixture_command, baseline_started,
            utc_now(), baseline_process.returncode, baseline_process.stdout,
            baseline_process.stderr, fixture_root)
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
                    case_temp / "run", verifier, case_temp)
                policy_hash = stale_hash or sha(policy_path.read_bytes())
                command = [sys.executable, str(consumer),
                    "--case-evaluate",
                    "--candidate-root", str(case_candidate),
                    "--evidence-root", str(case_temp / "run/evidence_raw"),
                    "--policy", str(policy_path),
                    "--expected-policy-sha256", policy_hash,
                    "--seal-root", str(case_temp / "run/seal")]
                if case_id == "E40":
                    command += ["--test-rename-artifact", "cpp-stdout"]
            started = utc_now()
            process = subprocess.run(command, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, check=False,
                                     env={"PATH": "/usr/bin:/bin",
                                          "PYTHONDONTWRITEBYTECODE": "1",
                                          "LC_ALL": "C", "TZ": "UTC"})
            if cleanup_marker:
                Path(cleanup_marker).unlink(missing_ok=True)
            case_output = output / "cases" / case_id
            case_output.mkdir(parents=True)
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


if __name__ == "__main__":
    raise SystemExit(main())
