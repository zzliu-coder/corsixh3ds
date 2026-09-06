#!/usr/bin/env python3
"""Build a runtime-only delta against a retained, validated SD baseline.

No network or resource conversion. A temporary hard-linked view is validated
with the full existing SD validator, then only changed files are published.
The baseline is never edited; replacement and generated files use new inodes.
This proves package coherence, not binary provenance or device acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import time

from validate_sd_tree import (
    CONTRACT_NAME, MANIFEST_NAME, ENTRYPOINT, ValidationError, _safe_relative,
    sha256_path, validate_sd_tree, write_boot_contract, write_sd_manifest,
)

METADATA = {CONTRACT_NAME, MANIFEST_NAME}


def runtime_path(value: str) -> str:
    value = _safe_relative(value)
    # Asset/config changes belong to the full packaging lane. Language subset
    # changes also need its converter and must not silently expand the runtime.
    first = PurePosixPath(value).parts[0]
    if value in {ENTRYPOINT, "CorsixTH.lua", "cth3ds-overlay-version.txt"}:
        return value
    if first == "Lua" and not value.lower().startswith("lua/languages/") and value.endswith(".lua"):
        return value
    raise ValidationError(f"not a runtime-only delta path: {value}")


def clean_identity(repo: Path) -> dict[str, str]:
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValidationError("commit the candidate before making a delta")
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}


def make_delta(baseline: Path, replacements: dict[str, Path], output: Path,
               candidate: dict[str, str]) -> dict:
    started = time.monotonic()
    baseline = baseline.absolute()
    output = output.absolute()
    if baseline.is_symlink() or not baseline.is_dir():
        raise ValidationError("baseline must be a real retained directory")
    if output.exists() or output.is_symlink():
        raise ValidationError("delta output already exists")
    if baseline.resolve() in output.resolve().parents:
        raise ValidationError("delta output cannot be inside the baseline")
    base_result = validate_sd_tree(baseline, require_mode="loose")
    base_manifest_hash = sha256_path(baseline / MANIFEST_NAME)
    base_manifest = json.loads((baseline / MANIFEST_NAME).read_text())
    old = {row["path"]: row for row in base_manifest["files"]}
    old[MANIFEST_NAME] = {"path": MANIFEST_NAME,
        "size": (baseline / MANIFEST_NAME).stat().st_size, "sha256": base_manifest_hash}
    sources = {}
    for relative, source in replacements.items():
        relative = runtime_path(relative)
        source = source.absolute()
        if not stat.S_ISREG(source.lstat().st_mode) or source.is_symlink():
            raise ValidationError(f"replacement must be a regular file: {source}")
        if not source.stat().st_size:
            raise ValidationError(f"empty replacement: {relative}")
        sources[relative] = (source, sha256_path(source))
    if ENTRYPOINT not in sources:
        raise ValidationError("supply the new built entrypoint explicitly")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cth3ds-delta-", dir=output.parent) as scratch:
        scratch = Path(scratch)
        merged = scratch / "merged"; merged.mkdir()
        published = scratch / "delta"; (published / "files").mkdir(parents=True)
        for relative in old:
            if relative in METADATA or relative in sources:
                continue
            target = merged / relative; target.parent.mkdir(parents=True, exist_ok=True)
            os.link(baseline / relative, target)
        for relative, (source, digest) in sources.items():
            target = merged / relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if sha256_path(target) != digest:
                raise ValidationError(f"replacement changed while copied: {relative}")
        write_boot_contract(merged, asset_mode="loose",
            candidate_commit=candidate["commit"], candidate_tree=candidate["tree"])
        manifest = write_sd_manifest(merged)
        validation = validate_sd_tree(merged, require_mode="loose")
        rows = list(manifest["files"]) + [{"path": MANIFEST_NAME,
            "size": (merged / MANIFEST_NAME).stat().st_size, "sha256": sha256_path(merged / MANIFEST_NAME)}]
        changed = []
        for row in rows:
            relative = row["path"]
            if old.get(relative) == row:
                continue
            if relative not in sources and relative not in METADATA:
                raise ValidationError(f"unexpected delta: {relative}")
            target = published / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(merged / relative, target)
            changed.append({**row, "previous": old.get(relative)})
        # Full revalidation detects accidental baseline writes or stale input.
        validate_sd_tree(baseline, require_mode="loose")
        if sha256_path(baseline / MANIFEST_NAME) != base_manifest_hash:
            raise ValidationError("baseline changed during delta creation")
        for relative, (source, digest) in sources.items():
            if sha256_path(source) != digest:
                raise ValidationError(f"replacement changed during validation: {relative}")
        changed.sort(key=lambda row: (row["path"] == ENTRYPOINT, row["path"]))
        result = {"format": "cth3ds-runtime-delta-v1", "lane": "development",
            "candidate": candidate, "baseline": base_result["candidate"],
            "baseline_manifest_sha256": base_manifest_hash,
            "package_validation": validation, "device_acceptance": "NOT_PROVEN",
            "files": changed, "upload_bytes": sum(row["size"] for row in changed),
            "retained_files": len(rows)-len(changed),
            "retained_bytes": sum(row["size"] for row in rows)-sum(row["size"] for row in changed),
            "elapsed_seconds": round(time.monotonic()-started, 3),
            "preserved": ["game", "Saves", "config.txt", "hotkeys.txt", "Logs"]}
        (published / "delta.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
        # Never replace a previously published delta.
        if output.exists() or output.is_symlink():
            raise ValidationError("delta output appeared during construction")
        published.rename(output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace", action="append", required=True, metavar="SD_PATH=LOCAL_FILE")
    args = parser.parse_args()
    try:
        replacements = {}
        for value in args.replace:
            relative, separator, source = value.partition("=")
            if not separator or not source or relative in replacements:
                raise ValidationError("replacement requires one unique SD_PATH=LOCAL_FILE")
            replacements[relative] = Path(source)
        identity = clean_identity(args.repo)
        result = make_delta(args.baseline, replacements, args.output, identity)
        # This tool performs no repository writes. Concurrent construction is
        # unsupported; the caller must freeze the candidate before packaging.
        if clean_identity(args.repo) != identity:
            raise ValidationError("candidate changed during packaging; do not deploy this delta")
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, ValueError, ValidationError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"SD_DELTA_FAIL: {exc}\n")


if __name__ == "__main__":
    main()
