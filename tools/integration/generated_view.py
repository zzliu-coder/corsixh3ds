"""Disposable complete generation and explicit, non-overwriting source views.

This is a deliberately bounded candidate API. Publication creates one symlink
to a finished private source directory. It never edits the input checkout and
does not switch an existing build's source pointer. Existing in-place callers
must opt in and select the returned view; there is no multi-file transaction.
"""
from __future__ import annotations

from pathlib import Path
import os
import hashlib
import json
import shutil
import stat
import tempfile

from .common import IntegrationError, sha256_file
from .overlay import iter_overlay_files, refresh_embedded_adapter


def _regular_copy(source: Path, target: Path) -> None:
    # lstat rejects links before copy2 can follow them outside the supplied tree.
    if not stat.S_ISREG(source.lstat().st_mode):
        raise IntegrationError(f"source view requires a regular file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)


def snapshot_source(source: Path, target: Path) -> dict[str, str]:
    """Copy source bytes, never .git or hard links; reject special entries.

    Input must be a source checkout/archive, with build/cache/game data outside
    it. An unexpected symlink fails closed instead of creating a partial view.
    Git identity is validated on the real input before this function is called.
    """
    target.mkdir()
    hashes: dict[str, str] = {}
    for directory, dirs, files in os.walk(source, followlinks=False):
        relative = Path(directory).relative_to(source)
        if relative == Path('.'):
            dirs[:] = [name for name in dirs if name != '.git']
            files = [name for name in files if name != '.git']
        dirs.sort()
        for name in dirs:
            path = Path(directory) / name
            if not stat.S_ISDIR(path.lstat().st_mode):
                raise IntegrationError(f"source view rejects linked directory: {path}")
            (target / relative / name).mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            path = Path(directory) / name
            key = (relative / name).as_posix()
            _regular_copy(path, target / key)
            hashes[key] = sha256_file(target / key)
    return hashes


RECEIPT = ".cth3ds-view.json"


def inventory(root: Path, *, omit_receipt: bool = False) -> dict:
    """Complete regular-source inventory, excluding only top-level Git metadata.

    Modes are part of product identity. Timestamps are not: every production game
    build is clean-first. Directory links, special files and hard links fail closed.
    """
    rows = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        relative = Path(directory).relative_to(root)
        if relative == Path("."):
            dirs[:] = [n for n in dirs if n != ".git"]
            files = [n for n in files if n != ".git"]
        for name in dirs:
            p = Path(directory) / name
            if not stat.S_ISDIR(p.lstat().st_mode):
                raise IntegrationError(f"linked source directory: {p}")
        for name in files:
            p = Path(directory) / name
            key = p.relative_to(root).as_posix()
            if omit_receipt and key == RECEIPT:
                continue
            info = p.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise IntegrationError(f"source requires exclusive regular file: {p}")
            rows[key] = {"sha256": sha256_file(p), "bytes": info.st_size,
                         "mode": stat.S_IMODE(info.st_mode)}
    return dict(sorted(rows.items()))


def input_paths(root: Path) -> list[Path]:
    """Bounded executable/overlay closure; no media, builds or dependency cache.

    All top-level Python tools and integration modules are included because
    generation imports both. Ordinary final Staff/World sources are captured
    with the overlay and included in its input identity.
    """
    paths = {p for p, _ in iter_overlay_files(root)}
    paths.update(root.glob("tools/*.py"))
    paths.update(root.glob("tools/integration/*.py"))
    overrides = root / "upstream_overrides"
    if overrides.exists():
        paths.update(p for p in overrides.rglob("*") if not p.is_dir())
    return sorted(paths)


def input_inventory(root: Path) -> dict:
    rows = {}
    for path in input_paths(root):
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise IntegrationError(f"linked generation input directory: {parent}")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise IntegrationError(f"generation input is not a regular file: {path}")
        rows[path.relative_to(root).as_posix()] = {
            "sha256": sha256_file(path), "bytes": info.st_size,
            "mode": stat.S_IMODE(info.st_mode)}
    # The orchestrator executes from its own tools directory. Custom overlays
    # must contain those exact tool bytes; recording a different unused copy
    # would create a false input identity.
    executing = Path(__file__).resolve().parents[1]
    actual = [*executing.glob("*.py"), *(executing / "integration").glob("*.py")]
    expected = {"tools/" + p.relative_to(executing).as_posix(): sha256_file(p) for p in actual}
    supplied = {key: row["sha256"] for key, row in rows.items() if key.startswith("tools/")}
    if supplied != expected:
        raise IntegrationError("overlay generation tools differ from executing tools")
    return rows


def snapshot_overlay(source: Path, target: Path) -> dict:
    rows = input_inventory(source)
    for key in rows:
        _regular_copy(source / key, target / key)
    refresh_embedded_adapter(target)
    return rows


def digest(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def seal_view(root: Path, overlay: Path, provenance: str) -> dict:
    rows = inventory(root, omit_receipt=True)
    inputs = input_inventory(overlay)
    receipt = {"format": 1, "kind": "complete-generated-source",
               "origin": provenance, "files": rows,
               "view_sha256": digest(rows), "inputs": inputs,
               "input_sha256": digest(inputs)}
    (root / RECEIPT).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def verify_view(root: Path, overlay: Path | None = None) -> dict:
    path = root / RECEIPT
    if path.is_symlink() or not path.is_file():
        raise IntegrationError(f"complete generated-source receipt missing: {path}")
    receipt = json.loads(path.read_text())
    if (not isinstance(receipt, dict) or receipt.get("format") != 1 or
            receipt.get("kind") != "complete-generated-source"):
        raise IntegrationError("unsupported complete generated-source receipt")
    rows = inventory(root, omit_receipt=True)
    if receipt.get("files") != rows or receipt.get("view_sha256") != digest(rows):
        raise IntegrationError("complete generated-source inventory changed")
    inputs = receipt.get("inputs")
    if not isinstance(inputs, dict) or receipt.get("input_sha256") != digest(inputs):
        raise IntegrationError("generation input receipt is malformed")
    if overlay is not None and inputs != input_inventory(overlay):
        raise IntegrationError("generation inputs changed; regenerate clean pinned source")
    return receipt


def _contains(parent: Path, child: Path) -> bool:
    return parent == child or parent in child.parents


def validate_output(output: Path | None, source: Path, overlay: Path,
                    *, private_empty: bool = False) -> None:
    if output is None:
        return
    # Keep the final component unresolved: broken links are occupied too.
    if output.is_symlink() or (output.exists() and not
            (private_empty and output.is_dir() and not any(output.iterdir()))):
        raise IntegrationError(f"output already exists; choose a new view: {output}")
    if not output.parent.is_dir():
        raise IntegrationError(f"output parent must already exist: {output.parent}")
    if any(_contains(root, output) or _contains(output, root)
           for root in (source, overlay)):
        raise IntegrationError("output must be separate from source and overlay")


class SourceView:
    """Own exactly one temporary build view until explicit publish succeeds."""
    def __init__(self, source: Path, overlay: Path, output: Path | None):
        validate_output(output, source, overlay)
        self.source, self.overlay, self.output = source, overlay, output
        self.directory = Path(tempfile.mkdtemp(
            prefix='.cth3ds-view-', dir=output.parent if output else None))
        self.root = self.directory / 'source'
        self.private_overlay = self.directory / 'overlay'
        self.published = False

    def __enter__(self):
        try:
            self.source_hashes = inventory(self.source)
            snapshot_source(self.source, self.root)
            self.overlay_hashes = snapshot_overlay(self.overlay, self.private_overlay)
        except BaseException:
            shutil.rmtree(self.directory)
            raise
        return self

    def verify_inputs(self):
        if inventory(self.source) != self.source_hashes:
            raise IntegrationError("source changed during generation")
        if input_inventory(self.overlay) != self.overlay_hashes:
            raise IntegrationError("overlay changed during generation")

    def publish(self):
        if self.output is None:
            raise IntegrationError('source view publication requires --output')
        self.verify_inputs()
        validate_output(self.output, self.source, self.overlay)
        # Only finished source remains. A failed exclusive symlink creation
        # leaves an existing output untouched and the context removes our view.
        shutil.rmtree(self.private_overlay)
        target = os.path.relpath(self.root, self.output.parent)
        os.symlink(target, self.output, target_is_directory=True)
        self.published = True

    def __exit__(self, exc_type, exc, traceback):
        # An interrupt can arrive after symlink creation and before the Python
        # flag assignment. The published reference is authoritative: retain its
        # source even when the call reports interruption at that exact boundary.
        if self.output is not None and self.output.is_symlink():
            target = os.path.relpath(self.root, self.output.parent)
            if os.readlink(self.output) == target:
                self.published = True
        if not self.published:
            shutil.rmtree(self.directory)
