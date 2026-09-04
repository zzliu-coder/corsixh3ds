#!/usr/bin/env python3
"""Build an immutable, relocatable input bundle for CorsixTH validation.

This is the only component allowed to read provenance paths.  Consumers receive
the completed bundle root and resolve every executable input below that root.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from typing import Any, Iterable


Path = pathlib.Path
SCHEMA = "cth3ds.verifier-input-bundle/v1"
ROOT_RULE = (
    "consumer paths resolve beneath bundle_root; provenance paths are audit metadata only"
)
REQUIRED_TOP_LEVEL = (
    "candidate", "authority", "dependencies", "runtimes", "wheelhouse",
    "toolchains", "ci", "replay", "device",
)
RUNTIME_VERSIONS = ("3.9.25", "3.14.6")
EXPECTED_PACKAGES = {
    "attrs": "25.3.0",
    "jsonschema": "4.25.1",
    "jsonschema-specifications": "2025.9.1",
    "referencing": "0.36.2",
    "rpds-py": "0.27.1",
    "typing-extensions": "4.14.1",
}
LIFECYCLE = "durable final receipt accepted by the scheduler"
AUTHORITY_KEY = "e0_r11_validation_change_authority"


class BundleError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("utf-8")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*argv: str, cwd: Path | None = None) -> str:
    process = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, check=False)
    if process.returncode:
        raise BundleError("COMMAND_FAILED: %s: %s" %
                          (" ".join(argv), process.stderr.decode(errors="replace")))
    return process.stdout.decode("utf-8", errors="strict").strip()


def git(repo: Path, *argv: str) -> str:
    return run("/usr/bin/git", "-C", str(repo), *argv)


def verify_candidate_transport(bundle: Path, identity: dict[str, Any]) -> dict[str, Any]:
    heads = run("/usr/bin/git", "bundle", "list-heads", str(bundle)).splitlines()
    expected_heads = [str(identity.get("head")) + " HEAD"]
    if heads != expected_heads:
        raise BundleError("CANDIDATE_BUNDLE_REFSET_INVALID: %s" % heads)
    with tempfile.TemporaryDirectory(prefix="cth3ds-candidate-transport-") as temporary:
        clone = Path(temporary) / "candidate"
        run("/usr/bin/git", "clone", "-q", str(bundle), str(clone))
        if git(clone, "rev-parse", "--is-shallow-repository") != "false":
            raise BundleError("CANDIDATE_BUNDLE_SHALLOW")
        run("/usr/bin/git", "-C", str(clone), "fsck", "--strict",
            "--connectivity-only", "--no-dangling", "HEAD")
        head = git(clone, "rev-parse", "HEAD^{commit}")
        tree = git(clone, "rev-parse", "HEAD^{tree}")
        parents = git(clone, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
        ancestry_count = len(git(clone, "rev-list", "HEAD").splitlines())
    if head != identity.get("head") or tree != identity.get("tree") or \
            parents != identity.get("parents"):
        raise BundleError("CANDIDATE_BUNDLE_IDENTITY_MISMATCH")
    return {"heads": heads, "ancestry_commit_count": ancestry_count,
            "connectivity": "PASS", "shallow": False}


def pointer_get(value: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise BundleError("VALIDATION_AUTHORITY_POINTER_INVALID")
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise BundleError("VALIDATION_AUTHORITY_POINTER_INVALID: %s" % pointer)
        current = current[token]
    return current


def validate_authority_object(authority: Any) -> dict[str, Any]:
    required = {
        "schema", "owner", "baseline", "authorized_diff_count",
        "authorized_diff_lines_sha256", "authorized_diff_exact",
        "review_policy_schema_role", "product_boundary", "candidate_constraints",
    }
    if not isinstance(authority, dict) or set(authority) != required:
        raise BundleError("VALIDATION_AUTHORITY_OBJECT_INVALID")
    paths = authority["authorized_diff_exact"]
    if not isinstance(paths, list) or not paths or \
            not all(isinstance(item, str) for item in paths):
        raise BundleError("VALIDATION_AUTHORITY_PATH_SET_INVALID")
    for item in paths:
        pure = pathlib.PurePosixPath(item)
        if pure.is_absolute() or ".." in pure.parts or item != pure.as_posix():
            raise BundleError("VALIDATION_AUTHORITY_PATH_INVALID: %s" % item)
    if paths != sorted(set(paths), key=lambda item: item.encode("utf-8")):
        raise BundleError("VALIDATION_AUTHORITY_PATH_SET_INVALID")
    if authority["authorized_diff_count"] != len(paths):
        raise BundleError("VALIDATION_AUTHORITY_PATH_COUNT_MISMATCH")
    lines_digest = hashlib.sha256(("\n".join(paths) + "\n").encode("utf-8")).hexdigest()
    if authority["authorized_diff_lines_sha256"] != lines_digest:
        raise BundleError("VALIDATION_AUTHORITY_PATH_DIGEST_MISMATCH")
    baseline = authority["baseline"]
    product = authority["product_boundary"]
    if not isinstance(baseline, dict) or set(baseline) != {"commit", "tree"} or \
            not all(re.fullmatch(r"[0-9a-f]{40}", baseline.get(key, ""))
                    for key in ("commit", "tree")):
        raise BundleError("VALIDATION_AUTHORITY_BASELINE_INVALID")
    if not isinstance(product, dict) or set(product) != {"entry_count", "sha256"} or \
            not isinstance(product.get("entry_count"), int) or product["entry_count"] < 1 or \
            not re.fullmatch(r"[0-9a-f]{64}", product.get("sha256", "")):
        raise BundleError("VALIDATION_AUTHORITY_PRODUCT_INVALID")
    role = authority["review_policy_schema_role"]
    constraints = authority["candidate_constraints"]
    if not isinstance(role, dict) or set(role) != {
            "json_pointer", "required_keywords", "forbidden_keywords"} or \
            not isinstance(constraints, dict) or set(constraints) != {
            "sole_parent", "clean", "repair_commits"}:
        raise BundleError("VALIDATION_AUTHORITY_CONTRACT_INVALID")
    return json.loads(canonical(authority))


def authority_binding_from_dag_bytes(dag_raw: bytes) -> dict[str, Any]:
    try:
        dag = json.loads(dag_raw.decode("utf-8"))
    except Exception as error:
        raise BundleError("VALIDATION_AUTHORITY_DAG_INVALID: %s" % error) from error
    if not isinstance(dag, dict) or AUTHORITY_KEY not in dag:
        raise BundleError("VALIDATION_AUTHORITY_MISSING")
    authority = validate_authority_object(dag[AUTHORITY_KEY])
    paths = authority["authorized_diff_exact"]
    return {
        "schema": "cth3ds.validation-authority-projection/v1",
        "dag_input_role": "execution_dag",
        "dag_input_sha256": hashlib.sha256(dag_raw).hexdigest(),
        "dag_authority_json_pointer": "/" + AUTHORITY_KEY,
        "authority_canonical_sha256": hashlib.sha256(canonical(authority)).hexdigest(),
        "authorized_diff_count": authority["authorized_diff_count"],
        "authorized_diff_lines_sha256": authority["authorized_diff_lines_sha256"],
        "authorized_diff_exact": paths,
        "projection": authority,
    }


def validate_authority_binding(binding: Any, dag_raw: bytes) -> dict[str, Any]:
    if not isinstance(binding, dict) or \
            binding.get("dag_input_sha256") != hashlib.sha256(dag_raw).hexdigest():
        raise BundleError("VALIDATION_AUTHORITY_DAG_HASH_MISMATCH")
    expected = authority_binding_from_dag_bytes(dag_raw)
    if binding != expected:
        raise BundleError("VALIDATION_AUTHORITY_BUILDER_PROJECTION_MISMATCH")
    return expected


def validate_schema_role(repo: Path, authority: dict[str, Any]) -> None:
    schema = json.loads((repo / "tests/runtime_core_v2/review-policy.schema.json").read_text(
        encoding="utf-8"))
    role = authority["review_policy_schema_role"]
    node = pointer_get(schema, role["json_pointer"])
    missing = set(role["required_keywords"]) - set(node) if isinstance(node, dict) else set()
    forbidden = set(role["forbidden_keywords"]) & set(node) if isinstance(node, dict) else set()
    if not isinstance(node, dict) or missing or forbidden or node.get("type") != "array" or \
            not isinstance(node.get("items"), dict) or node["items"].get("type") != "string" or \
            node.get("uniqueItems") is not True:
        raise BundleError("VALIDATION_AUTHORITY_SCHEMA_ROLE_MISMATCH")


def validate_candidate_authority(repo: Path, head: str, parents: list[str],
                                 binding: dict[str, Any]) -> None:
    authority = binding["projection"]
    baseline = authority["baseline"]
    if parents != [baseline["commit"]] or \
            git(repo, "rev-parse", baseline["commit"] + "^{tree}") != baseline["tree"]:
        raise BundleError("CANDIDATE_PARENT_MISMATCH")
    status_rows = git(repo, "diff", "--name-status", "--no-renames",
                      baseline["commit"], head, "--").splitlines()
    if any(not row.startswith(("A\t", "M\t")) for row in status_rows):
        raise BundleError("VALIDATION_AUTHORITY_DIFF_MODE_MISMATCH")
    paths = sorted((row.split("\t", 1)[1] for row in status_rows),
                   key=lambda item: item.encode("utf-8"))
    if paths != authority["authorized_diff_exact"]:
        raise BundleError("VALIDATION_AUTHORITY_DIFF_SET_MISMATCH")
    digest = hashlib.sha256(("\n".join(paths) + "\n").encode("utf-8")).hexdigest()
    if digest != authority["authorized_diff_lines_sha256"]:
        raise BundleError("VALIDATION_AUTHORITY_PATH_DIGEST_MISMATCH")
    validate_schema_role(repo, authority)


def inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def lexical_entries(root: Path) -> list[dict[str, Any]]:
    root = root.absolute()
    rows: list[dict[str, Any]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in sorted([*directories, *files], key=lambda item: item.encode("utf-8")):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                if os.path.isabs(target):
                    raise BundleError("ABSOLUTE_SYMLINK_FORBIDDEN: %s -> %s" % (path, target))
                resolved = (path.parent / target).resolve(strict=True)
                if not inside(root.resolve(strict=True), resolved):
                    raise BundleError("SYMLINK_ESCAPE: %s -> %s" % (path, target))
                # POSIX symlink permissions are not semantic and cannot be
                # preserved portably: Darwin reports 0755 for newly-created
                # links while Linux reports 0777.  Canonicalize the value so a
                # bundle built on one host rehashes identically after transport
                # to another host.
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
                raise BundleError("SPECIAL_FILE_FORBIDDEN: %s" % path)
    return sorted(rows, key=lambda row: row["path"].encode("utf-8"))


def tree_digest(root: Path) -> tuple[str, int]:
    rows = lexical_entries(root)
    return hashlib.sha256(canonical(rows)).hexdigest(), len(rows)


def is_macho(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        magic = handle.read(4)
    return magic in {
        b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
    }


def copy_tree(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    lexical_entries(source)
    destination.mkdir(parents=True)
    for current, directories, files in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(source)
        target_dir = destination / relative
        for name in list(directories):
            item = current_path / name
            target = target_dir / name
            if item.is_symlink():
                link = os.readlink(item)
                target.symlink_to(link)
                directories.remove(name)
            else:
                target.mkdir()
        for name in files:
            item = current_path / name
            target = target_dir / name
            if item.is_symlink():
                target.symlink_to(os.readlink(item))
            else:
                shutil.copy2(item, target, follow_symlinks=False)
    lexical_entries(destination)


def copy_runtime_tree(source: Path, destination: Path) -> list[str]:
    """Copy a runtime, replacing Homebrew's external site-packages link.

    The verifier installs its locked wheels into a new task-owned runtime.
    Global Homebrew site-packages are therefore unnecessary and forbidden.
    """
    source = source.resolve(strict=True)
    destination.mkdir(parents=True)
    removed_host_policies: list[str] = []
    for current, directories, files in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(source)
        target_dir = destination / relative
        for name in list(directories):
            item = current_path / name
            target = target_dir / name
            if name == "site-packages":
                target.mkdir()
                removed_host_policies.append(item.relative_to(source).as_posix())
                directories.remove(name)
                continue
            if item.is_symlink():
                link = os.readlink(item)
                resolved = item.resolve(strict=True)
                if inside(source, resolved):
                    target.symlink_to(link)
                else:
                    raise BundleError("RUNTIME_SYMLINK_ESCAPE: %s -> %s" % (item, link))
                directories.remove(name)
            else:
                target.mkdir()
        for name in files:
            item = current_path / name
            target = target_dir / name
            if item.is_symlink():
                resolved = item.resolve(strict=True)
                if not inside(source, resolved):
                    raise BundleError("RUNTIME_SYMLINK_ESCAPE: %s" % item)
                target.symlink_to(os.readlink(item))
            elif item.is_file():
                # Homebrew's sitecustomize injects prefix-global packages and
                # split-formula paths.  A bundled verifier runtime owns its
                # complete import path, so that host policy must not survive.
                if name == "sitecustomize.py" and b"Homebrew" in item.read_bytes():
                    removed_host_policies.append(item.relative_to(source).as_posix())
                    continue
                shutil.copy2(item, target, follow_symlinks=False)
            else:
                raise BundleError("RUNTIME_SPECIAL_FILE_FORBIDDEN: %s" % item)
    lexical_entries(destination)
    return removed_host_policies


def deterministic_tar(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    lexical_entries(source)

    def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "wheel"
        info.mtime = 0
        info.pax_headers = {}
        return info

    with tarfile.open(destination, "w", format=tarfile.PAX_FORMAT) as archive:
        archive.add(source, arcname="runtime", recursive=True, filter=normalize)


def patch_macos_runtime(root: Path, provenance_root: Path) -> list[dict[str, str]]:
    if platform.system() != "Darwin":
        return []
    otool = Path("/usr/bin/otool")
    install_name_tool = Path("/usr/bin/install_name_tool")
    codesign = Path("/usr/bin/codesign")
    if not otool.is_file() or not install_name_tool.is_file():
        return []
    source_root = provenance_root.resolve(strict=True)
    source_prefix = str(source_root) + "/"
    vendor_root = root / "lib/cth3ds-runtime-deps"
    vendor_root.mkdir(parents=True, exist_ok=True)
    changes: list[dict[str, str]] = []
    pending = sorted((item for item in root.rglob("*") if is_macho(item)),
                     key=lambda item: str(item).encode("utf-8"))
    visited: set[Path] = set()
    while pending:
        path = pending.pop(0)
        if path in visited:
            continue
        visited.add(path)
        probe = subprocess.run([str(otool), "-L", str(path)], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, check=False, text=True)
        if probe.returncode:
            continue
        changed = False
        id_probe = subprocess.run([str(otool), "-D", str(path)], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, check=False, text=True)
        dylib_id = None
        if id_probe.returncode == 0:
            id_lines = id_probe.stdout.splitlines()[1:]
            if id_lines:
                dylib_id = id_lines[0].strip()
        for line in probe.stdout.splitlines()[1:]:
            old = line.strip().split(" (", 1)[0]
            if old.startswith(("@", "/usr/lib/", "/System/Library/")):
                continue
            if dylib_id and old == dylib_id:
                replacement = "@rpath/" + path.name
                run(str(install_name_tool), "-id", replacement, str(path))
                changes.append({"binary": path.relative_to(root).as_posix(),
                                "old": old, "new": replacement, "kind": "dylib-id"})
                changed = True
                continue
            if not old.startswith("/"):
                raise BundleError("MACHO_DEPENDENCY_RELATIVE_FORBIDDEN: %s -> %s" %
                                  (path, old))
            dependency = Path(old).resolve(strict=True)
            if old.startswith(source_prefix) and inside(source_root, dependency):
                relative_target = dependency.relative_to(source_root)
                copied_target = root / relative_target
                if not copied_target.exists():
                    raise BundleError("MACHO_DEPENDENCY_MISSING: %s -> %s" % (path, old))
            elif old.startswith("/opt/homebrew/"):
                identity = hashlib.sha256(str(dependency).encode("utf-8")).hexdigest()[:16]
                copied_target = vendor_root / (identity + "-" + dependency.name)
                if not copied_target.exists():
                    shutil.copy2(dependency, copied_target, follow_symlinks=True)
                    copied_target.chmod(0o755)
                    pending.append(copied_target)
            else:
                raise BundleError("MACHO_EXTERNAL_DEPENDENCY_FORBIDDEN: %s -> %s" %
                                  (path, old))
            replacement = "@loader_path/" + os.path.relpath(copied_target, path.parent)
            run(str(install_name_tool), "-change", old, replacement, str(path))
            changes.append({"binary": path.relative_to(root).as_posix(),
                            "old": old, "new": replacement, "kind": "dependency"})
            changed = True
        if changed and codesign.is_file():
            run(str(codesign), "--force", "--sign", "-", str(path))
    # Re-scan every Mach-O after patching.  Only loader-relative and OS-owned
    # libraries may remain; this is the runtime closure gate.
    for path in sorted((item for item in root.rglob("*") if is_macho(item)),
                       key=lambda item: str(item).encode("utf-8")):
        probe = subprocess.run([str(otool), "-L", str(path)], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, check=False, text=True)
        if probe.returncode:
            continue
        external = []
        for line in probe.stdout.splitlines()[1:]:
            value = line.strip().split(" (", 1)[0]
            if value.startswith(("@", "/usr/lib/", "/System/Library/")):
                continue
            external.append(value)
        if external:
            raise BundleError("MACHO_CLOSURE_FAILED: %s -> %s" % (path, external))
    return changes


def runtime_executable(root: Path, version: str) -> Path:
    major_minor = ".".join(version.split(".")[:2])
    choices = [root / "bin" / ("python" + major_minor),
               root / "bin" / "python3", root / "bin" / "python"]
    for path in choices:
        if path.exists():
            return path
    raise BundleError("PYTHON_RUNTIME_EXECUTABLE_MISSING: %s" % root)


def verify_runtime(root: Path, version: str) -> dict[str, Any]:
    executable = runtime_executable(root, version)
    observed = run(str(executable), "-I", "-c",
                   "import json,pathlib,sys; print(json.dumps({"
                   "'version':sys.version.split()[0],'executable':sys.executable,"
                   "'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
                   "'implementation':str(pathlib.Path(sys.executable).resolve())},sort_keys=True))")
    value = json.loads(observed)
    if value["version"] != version:
        raise BundleError("PYTHON_RUNTIME_VERSION_MISMATCH: %s" % value)
    resolved = Path(value["implementation"]).resolve(strict=True)
    if not inside(root.resolve(strict=True), resolved):
        raise BundleError("PYTHON_RUNTIME_REALPATH_ESCAPE: %s" % resolved)
    if not inside(root.resolve(strict=True), Path(value["base_prefix"]).resolve(strict=True)):
        raise BundleError("PYTHON_RUNTIME_BASE_PREFIX_ESCAPE: %s" % value["base_prefix"])
    return value


def parse_mapping(values: Iterable[str], label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise BundleError("%s requires VERSION=/absolute/path" % label)
        version, path_raw = raw.split("=", 1)
        path = Path(path_raw)
        if not path.is_absolute():
            raise BundleError("%s path must be absolute" % label)
        if version in result:
            raise BundleError("duplicate %s version: %s" % (label, version))
        result[version] = path.resolve(strict=True)
    return result


def wheel_inventory(root: Path) -> dict[str, Any]:
    wheels = sorted(root.glob("*.whl"), key=lambda path: path.name.encode("utf-8"))
    if not wheels:
        raise BundleError("WHEELHOUSE_EMPTY: %s" % root)
    rows = [{"filename": path.name, "bytes": path.stat().st_size,
             "sha256": sha_file(path)} for path in wheels]
    normalized = {name.replace("_", "-").lower() for name in EXPECTED_PACKAGES}
    observed: set[str] = set()
    for row in rows:
        observed.add(row["filename"].split("-", 1)[0].replace("_", "-").lower())
    if observed != normalized:
        raise BundleError("WHEELHOUSE_PACKAGE_SET_MISMATCH: expected=%s observed=%s" %
                          (sorted(normalized), sorted(observed)))
    return {"files": rows, "file_count": len(rows),
            "inventory_sha256": hashlib.sha256(canonical(rows)).hexdigest()}


def make_readonly(root: Path) -> None:
    for current, directories, files in os.walk(root, topdown=False, followlinks=False):
        current_path = Path(current)
        for name in files:
            path = current_path / name
            if not path.is_symlink():
                path.chmod(0o444)
        for name in directories:
            path = current_path / name
            if not path.is_symlink():
                path.chmod(0o555)
        current_path.chmod(0o555)


def add_input(inputs: list[dict[str, Any]], bundle: Path, role: str, owner: str,
              provenance: Path, relative: str, stages: list[str],
              source_identity: dict[str, Any]) -> None:
    target = bundle / relative
    copied_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if target.is_file():
        digest = sha_file(target)
        count = target.stat().st_size
        kind = "file"
        mode = "0444"
    elif target.is_dir():
        digest, count = tree_digest(target)
        kind = "tree"
        mode = "0555-tree"
    else:
        raise BundleError("BUNDLE_INPUT_MISSING: %s" % target)
    inputs.append({
        "role": role,
        "owner": owner,
        "provenance_source_path": str(provenance.absolute()),
        "bundle_relative_path": relative,
        "kind": kind,
        "byte_size_or_tree_entry_count": count,
        "sha256_or_tree_digest": digest,
        "required_stages": stages,
        "copied_at_utc": copied_at,
        "mode": mode,
        "symlink_policy": "internal-relative-only",
        "source_identity": source_identity,
        "lifecycle_end": LIFECYCLE,
        "cleanup_boundary": "retain bundle until its durable receipt is accepted",
    })


def product_fingerprint(repo: Path, excluded: set[str]) -> dict[str, Any]:
    paths = [line for line in git(repo, "ls-files").splitlines() if line not in excluded]
    rows = []
    for relative in paths:
        path = repo / relative
        rows.append({"path": relative, "bytes": path.stat().st_size,
                     "sha256": sha_file(path)})
    return {"algorithm": "sha256(canonical(path,bytes,sha256))/v1",
            "entry_count": len(rows),
            "sha256": hashlib.sha256(canonical(rows)).hexdigest()}


def create_bundle(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.absolute()
    if output.exists():
        raise BundleError("OUTPUT_EXISTS: %s" % output)
    output.parent.mkdir(parents=True, exist_ok=True)
    repo = args.candidate_repo.resolve(strict=True)
    if git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise BundleError("CANDIDATE_DIRTY")
    if git(repo, "rev-parse", "--is-shallow-repository") != "false":
        raise BundleError("CANDIDATE_SHALLOW_REPOSITORY")
    head = git(repo, "rev-parse", "HEAD^{commit}")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    parents = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    if len(parents) != 1:
        raise BundleError("CANDIDATE_SOLE_PARENT_REQUIRED")
    dag_raw = args.dag.resolve(strict=True).read_bytes()
    authority_binding = authority_binding_from_dag_bytes(dag_raw)
    validate_candidate_authority(repo, head, parents, authority_binding)
    staged = output.parent / (".%s.creating.%s" % (output.name, uuid.uuid4().hex))
    runtimes = parse_mapping(args.python_runtime, "--python-runtime")
    wheelhouses = parse_mapping(args.wheelhouse, "--wheelhouse")
    if set(runtimes) != set(RUNTIME_VERSIONS) or set(wheelhouses) != set(RUNTIME_VERSIONS):
        raise BundleError("BOTH_EXACT_RUNTIME_AND_WHEELHOUSE_VERSIONS_REQUIRED")
    try:
        staged.mkdir()
        for name in REQUIRED_TOP_LEVEL:
            (staged / name).mkdir()
        inputs: list[dict[str, Any]] = []

        candidate_dir = staged / "candidate"
        candidate_bundle = candidate_dir / "candidate.bundle"
        run("/usr/bin/git", "-C", str(repo), "bundle", "create",
            str(candidate_bundle), "HEAD")
        tracked_raw = subprocess.run(["/usr/bin/git", "-C", str(repo), "ls-files", "-s", "-z"],
                                     stdout=subprocess.PIPE, check=True).stdout
        candidate_identity = {
            "head": head,
            "tree": tree,
            "parents": parents,
            "tracked_entries": sum(bool(row) for row in tracked_raw.split(b"\0")),
            "tracked_fingerprint": hashlib.sha256(tracked_raw).hexdigest(),
        }
        verify_candidate_transport(candidate_bundle, candidate_identity)
        candidate_bundle.chmod(0o444)
        add_input(inputs, staged, "candidate_transport", "validation-task", repo,
                  "candidate/candidate.bundle", ["preflight", "all"],
                  {**candidate_identity, "product_fingerprint": product_fingerprint(
                      repo, set(authority_binding["authorized_diff_exact"]))})

        authority = staged / "authority/frozen"
        authority.mkdir(parents=True)
        authority_sources = (
            ("source_archive", args.archive, "CorsixTH.tar.gz"),
            ("frozen_matrix", args.matrix, "c3-acceptance-matrix.json"),
            ("base_acceptance_cases", args.base_cases, "c3-r3-acceptance-cases.json"),
            ("r4_acceptance_cases", args.r4_cases, "c3-r4-acceptance-cases.json"),
            ("execution_dag", args.dag, "execution-dag.json"),
        )
        for role, source_arg, name in authority_sources:
            source = source_arg.resolve(strict=True)
            target = authority / name
            shutil.copy2(source, target)
            target.chmod(0o444)
            add_input(inputs, staged, role, "validation-task", source,
                      "authority/frozen/" + name, ["preflight", "all"],
                      {"sha256": sha_file(source), "bytes": source.stat().st_size})

        copy_tree(args.deps_prefix, staged / "dependencies/host")
        make_readonly(staged / "dependencies/host")
        source_digest, source_count = tree_digest(args.deps_prefix)
        add_input(inputs, staged, "cross_dependencies", "validation-task",
                  args.deps_prefix, "dependencies/host", ["policy", "produce", "final-audit"],
                  {"tree_digest": source_digest, "entry_count": source_count})

        runtime_meta: dict[str, Any] = {}
        for version in RUNTIME_VERSIONS:
            source = runtimes[version]
            runtime_stage = staged / (".runtime-stage-" + version)
            removed_policies = copy_runtime_tree(source, runtime_stage)
            patch_rows = patch_macos_runtime(runtime_stage, source)
            observed = verify_runtime(runtime_stage, version)
            destination_dir = staged / "runtimes" / platform_tag() / ("python-" + version)
            destination_dir.mkdir(parents=True)
            archive = destination_dir / "runtime.tar"
            deterministic_tar(runtime_stage, archive)
            shutil.rmtree(runtime_stage)
            archive.chmod(0o444)
            runtime_meta[version] = {"observed": observed, "patches": patch_rows,
                                     "removed_host_policies": removed_policies,
                                     "archive_sha256": sha_file(archive)}
            add_input(inputs, staged, "python_runtime_" + version.replace(".", "_"),
                      "validation-task", source,
                      archive.relative_to(staged).as_posix(), ["environment", "all"],
                      runtime_meta[version])

        for version in RUNTIME_VERSIONS:
            source = wheelhouses[version]
            inventory = wheel_inventory(source)
            relative = "wheelhouse/%s/python-%s" % (platform_tag(), version)
            copy_tree(source, staged / relative)
            make_readonly(staged / relative)
            add_input(inputs, staged, "python_wheelhouse_" + version.replace(".", "_"),
                      "validation-task", source, relative, ["environment", "all"], inventory)

        toolchain_archive_dir = staged / "toolchains/old3ds"
        toolchain_archive_dir.mkdir(parents=True)
        toolchain_archive = toolchain_archive_dir / "toolchain.tar"
        deterministic_tar(args.toolchain_root, toolchain_archive)
        toolchain_archive.chmod(0o444)
        toolchain_source_digest, toolchain_source_count = tree_digest(args.toolchain_root)
        add_input(inputs, staged, "old3ds_toolchain", "validation-task",
                  args.toolchain_root, "toolchains/old3ds/toolchain.tar",
                  ["old3ds-cross-build"], {"tree_digest": toolchain_source_digest,
                  "entry_count": toolchain_source_count})

        workflow = repo / ".github/workflows/old3ds-validation.yml"
        workflow_copy = staged / "ci/old3ds-validation.yml"
        shutil.copy2(workflow, workflow_copy)
        uses = re.findall(r"uses:\s*([^\s#]+)", workflow.read_text(encoding="utf-8"))
        unpinned = [item for item in uses if not re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", item)]
        if unpinned:
            raise BundleError("UNPINNED_ACTION_REFERENCES: %s" % unpinned)
        ci_lock = {
            "schema": "cth3ds.public-ci-environment-lock/v1",
            "workflow_sha256": sha_file(workflow),
            "actions": uses,
            "runner": args.ci_runner,
            "host_container": args.ci_host_container,
            "old3ds_container": args.ci_old3ds_container,
            "python_versions": list(RUNTIME_VERSIONS),
        }
        (staged / "ci/actions-lock.json").write_bytes(canonical(ci_lock))
        policy_source = repo / "requirements/verifier-wheelhouse-manifest.json"
        shutil.copy2(policy_source, staged / "ci/verifier-wheelhouse-manifest.json")
        for item in (workflow_copy, staged / "ci/actions-lock.json",
                     staged / "ci/verifier-wheelhouse-manifest.json"):
            item.chmod(0o444)
        make_readonly(staged / "ci")
        add_input(inputs, staged, "public_ci_environment", "validation-task", workflow,
                  "ci", ["public-ci"], ci_lock)

        for name in ("replay", "device"):
            marker = staged / name / "NOT_REQUIRED_FOR_E0.json"
            marker.write_bytes(canonical({"schema": "cth3ds.bundle-role-placeholder/v1",
                                          "status": "NOT_REQUIRED_FOR_E0"}))
            marker.chmod(0o444)

        manifest = {
            "schema": SCHEMA,
            "bundle_id": uuid.uuid4().hex,
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "root_rule": ROOT_RULE,
            "candidate_identity": candidate_identity,
            "validation_change_authority": authority_binding,
            "inputs": sorted(inputs, key=lambda row: row["role"]),
            "immutability": {"file_mode": "0444", "directory_mode": "0555",
                             "symlink_policy": "internal-relative-only", "stage_rehash": True},
            "lifecycle": {"owner": "validation-task",
                          "ends_after": "durable-final-receipt-accepted",
                          "outputs_separate": True},
        }
        (staged / "manifest.json").write_bytes(canonical(manifest))
        regular_files = sorted(
            [path for path in staged.rglob("*") if path.is_file() and
             path.name not in {"manifest.json", "SHA256SUMS"}],
            key=lambda path: path.relative_to(staged).as_posix().encode("utf-8"))
        sums = "".join("%s  %s\n" % (sha_file(path), path.relative_to(staged).as_posix())
                       for path in regular_files)
        with (staged / "SHA256SUMS").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(sums)
        make_readonly(staged)
        os.replace(staged, output)
        verify_completed_bundle(output)
        return {"status": "PASS", "bundle_root": str(output),
                "manifest_sha256": sha_file(output / "manifest.json"),
                "sha256sums_sha256": sha_file(output / "SHA256SUMS"),
                "candidate_identity": candidate_identity,
                "validation_change_authority": authority_binding,
                "input_count": len(inputs), "runtime_meta": runtime_meta}
    except Exception:
        if staged.exists():
            make_writable(staged)
            shutil.rmtree(staged)
        raise


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    return "%s-%s" % (system, machine)


def make_writable(root: Path) -> None:
    for current, directories, files in os.walk(root, topdown=False, followlinks=False):
        current_path = Path(current)
        for name in files:
            path = current_path / name
            if not path.is_symlink():
                path.chmod(0o600)
        for name in directories:
            path = current_path / name
            if not path.is_symlink():
                path.chmod(0o700)
        current_path.chmod(0o700)


def verify_completed_bundle(root: Path) -> dict[str, Any]:
    root = root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise BundleError("BUNDLE_ROOT_INVALID")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise BundleError("BUNDLE_SCHEMA_MISMATCH")
    for name in REQUIRED_TOP_LEVEL:
        if not (root / name).is_dir():
            raise BundleError("BUNDLE_TOP_LEVEL_MISSING: %s" % name)
    seen: set[str] = set()
    for item in manifest.get("inputs", []):
        role = item.get("role")
        relative = item.get("bundle_relative_path")
        if not isinstance(role, str) or role in seen:
            raise BundleError("BUNDLE_ROLE_INVALID: %s" % role)
        seen.add(role)
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise BundleError("BUNDLE_RELATIVE_PATH_INVALID: %s" % relative)
        lexical = root / relative
        resolved = lexical.resolve(strict=True)
        if not inside(root.resolve(strict=True), resolved):
            raise BundleError("BUNDLE_REALPATH_ESCAPE: %s" % relative)
        if item.get("kind") == "file":
            actual = sha_file(lexical)
            mode = stat.S_IMODE(lexical.stat().st_mode)
            if mode != 0o444:
                raise BundleError("BUNDLE_FILE_MODE_INVALID: %s %04o" % (relative, mode))
        else:
            actual, _ = tree_digest(lexical)
        if actual != item.get("sha256_or_tree_digest"):
            raise BundleError("BUNDLE_INPUT_HASH_MISMATCH: %s" % role)
    expected_roles = {
        "candidate_transport", "source_archive", "frozen_matrix",
        "base_acceptance_cases", "r4_acceptance_cases", "execution_dag",
        "cross_dependencies", "python_runtime_3_9_25", "python_runtime_3_14_6",
        "python_wheelhouse_3_9_25", "python_wheelhouse_3_14_6",
        "old3ds_toolchain", "public_ci_environment",
    }
    if seen != expected_roles:
        raise BundleError("BUNDLE_ROLE_SET_MISMATCH: %s" % sorted(seen ^ expected_roles))
    binding = manifest.get("validation_change_authority")
    dag_item = next((item for item in manifest.get("inputs", [])
                     if item.get("role") == "execution_dag"), None)
    if not isinstance(binding, dict) or dag_item is None or \
            binding.get("dag_input_sha256") != dag_item.get("sha256_or_tree_digest"):
        raise BundleError("VALIDATION_AUTHORITY_DAG_HASH_MISMATCH")
    dag_path = root / dag_item["bundle_relative_path"]
    expected_binding = validate_authority_binding(binding, dag_path.read_bytes())
    identity = manifest.get("candidate_identity", {})
    if identity.get("parents") != [binding["projection"]["baseline"]["commit"]]:
        raise BundleError("VALIDATION_AUTHORITY_CANDIDATE_BINDING_MISMATCH")
    verify_candidate_transport(root / "candidate/candidate.bundle", identity)
    sums = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    for line in sums:
        digest, relative = line.split("  ", 1)
        path = root / relative
        if sha_file(path) != digest:
            raise BundleError("SHA256SUMS_MISMATCH: %s" % relative)
    for path in [root, *(item for item in root.rglob("*") if item.is_dir() and not item.is_symlink())]:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o555:
            raise BundleError("BUNDLE_DIRECTORY_MODE_INVALID: %s %04o" % (path, mode))
    lexical_entries(root)
    return {"status": "PASS", "roles": sorted(seen),
            "validation_change_authority": binding,
            "manifest_sha256": sha_file(root / "manifest.json"),
            "sha256sums_sha256": sha_file(root / "SHA256SUMS")}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(allow_abbrev=False)
    result.add_argument("--output", type=Path)
    result.add_argument("--candidate-repo", type=Path)
    result.add_argument("--archive", type=Path)
    result.add_argument("--matrix", type=Path)
    result.add_argument("--base-cases", type=Path)
    result.add_argument("--r4-cases", type=Path)
    result.add_argument("--dag", type=Path)
    result.add_argument("--deps-prefix", type=Path)
    result.add_argument("--python-runtime", action="append", default=[])
    result.add_argument("--wheelhouse", action="append", default=[])
    result.add_argument("--toolchain-root", type=Path)
    result.add_argument("--ci-runner")
    result.add_argument("--ci-host-container")
    result.add_argument("--ci-old3ds-container")
    result.add_argument("--verify", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.verify:
            conflicting = [name for name in ("output", "candidate_repo", "archive", "matrix",
                           "base_cases", "r4_cases", "dag", "deps_prefix", "toolchain_root",
                           "ci_runner", "ci_host_container", "ci_old3ds_container")
                           if getattr(args, name) is not None]
            if conflicting or args.python_runtime or args.wheelhouse:
                raise BundleError("VERIFY_MODE_CONFLICTING_ARGUMENTS")
            value = verify_completed_bundle(args.verify)
        else:
            required = ("output", "candidate_repo", "archive", "matrix", "base_cases",
                        "r4_cases", "dag", "deps_prefix", "toolchain_root", "ci_runner",
                        "ci_host_container", "ci_old3ds_container")
            missing = [name for name in required if getattr(args, name) is None]
            if missing:
                raise BundleError("CREATE_MODE_ARGUMENTS_MISSING: %s" % missing)
            value = create_bundle(args)
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"status": "FAIL", "failure_code": str(error).split(":", 1)[0],
                          "detail": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
