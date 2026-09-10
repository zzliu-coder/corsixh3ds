"""Bounded FTP product update with fresh user-data protection and explicit recovery.

The adapter is runner.Remote: connection(), get(ftp, path, limit), live(sha).
parse_identity converts device.kv bytes to a mapping containing boot and
launcher_sha256. No runner imports, host paths, historical save counts, or game
launches are embedded here. Callers must use the SAME owner_lock for a device.
flock excludes cooperating local clients; independent FTP writers cannot be
excluded by FTP. Inventory/content checks detect observed interference and fail
closed, but are not a filesystem snapshot against arbitrary concurrent writers.

delta.json: {candidate: {commit: ...}, files: [{path, size, sha256, previous?}]}.
previous, if supplied, is null for an expected new target or {sha256: ...}.
Omitting it captures the current product file as this transaction's rollback
baseline. Payloads are package/files/<path>. The executable must be last.
deploy() never resumes a journal. inspect() is read-only. rollback() requires an
explicit caller invocation and only moves recognized product bytes; Saves and
configuration are never overwritten, deleted, or rolled back.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import uuid


MAX_FILE = 64 * 1024 * 1024
MAX_PROTECTED_FILES = 4096
PRODUCTS = {"CorsixTH-3DS.3dsx", "boot-contract.json", "sd-manifest.json",
            "CorsixTH-SC-subset.ttf", "loose-assets.json", "private-media.json"}
CONFIG_SUFFIXES = {".txt", ".cfg", ".ini", ".json"}


class UpdateError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise UpdateError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _name(name):
    require(isinstance(name, str) and name and name not in (".", ".."), "unsafe name")
    require(not any(c in name for c in "/\\\r\n\x00") and not name.endswith((" ", ".")),
            "unsafe name")
    require(all(ord(c) >= 32 for c in name), "control character in name")
    return name


def _relative(path):
    require(isinstance(path, str) and not path.startswith("/"), "absolute path")
    for part in path.split("/"):
        _name(part)
    require(str(PurePosixPath(path)) == path, "noncanonical path")
    return path


def _product(path):
    _relative(path)
    require(path in PRODUCTS or (path.startswith("Lua/") and path.endswith(".lua")),
            "target outside product allowlist: " + path)
    return path


def _absolute(path):
    require(path.startswith("/") and path != "/", "unsafe device root")
    _relative(path[1:])
    return path


def _listing(ftp, path):
    lines = []
    ftp.retrlines("LIST " + path, lines.append)
    result, folded = {}, set()
    for line in lines:
        fields = line.split(maxsplit=8)
        require(len(fields) == 9 and fields[0][0] in "d-", "unsupported FTP listing")
        name = _name(fields[8])
        require(name.casefold() not in folded, "case collision in device listing")
        folded.add(name.casefold())
        result[name] = fields[0].startswith("d")
    return result


def _write(path, value):
    """Durably replace a small local receipt; never mutate device data."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


@contextmanager
def _lock(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        initial = os.fstat(handle.fileno())
        def guard():
            current = path.stat()
            require((initial.st_dev, initial.st_ino) == (current.st_dev, current.st_ino),
                    "owner lock replaced")
        yield guard


class _Session:
    def __init__(self, remote, parse_identity, state, guard):
        self.remote, self.parse_identity, self.state, self.local_guard = remote, parse_identity, state, guard

    def guard(self, ftp):
        self.local_guard()
        names = _listing(ftp, self.state["control"])
        require(not set(names).intersection({"active", "ready", "dispatch.lock"}), "runner busy")
        now = self.parse_identity(self.remote.get(ftp, self.state["control"] + "/device.kv", 16384))
        require(now["launcher_sha256"] == self.state["launcher_sha256"], "runner launcher changed")
        require(now["boot"] == self.state["boot"], "runner boot changed")

    @contextmanager
    def connection(self):
        with self.remote.connection() as ftp:
            self.guard(ftp)
            yield ftp

    def inventory(self, ftp):
        root = self.state["live"]
        roots = _listing(ftp, root)
        require(not any(name.casefold() == "saves" and name != "Saves" for name in roots),
                "case alias for protected Saves directory")
        files, directories = [], []
        def walk(path, depth=0):
            require(depth <= 32 and len(directories) < MAX_PROTECTED_FILES, "protection tree exceeds bound")
            directories.append(path)
            for name, is_dir in sorted(_listing(ftp, path).items()):
                child = path + "/" + name
                if is_dir:
                    walk(child, depth + 1)
                else:
                    files.append(child)
                    require(len(files) <= MAX_PROTECTED_FILES, "protection file count exceeds bound")
        if "Saves" in roots:
            require(roots["Saves"], "Saves is not a directory")
            walk(root + "/Saves")
        for name, is_dir in roots.items():
            if not is_dir and name not in PRODUCTS and PurePosixPath(name).suffix.lower() in CONFIG_SUFFIXES:
                files.append(root + "/" + name)
        # Optional nested config locations are exact paths, including absence.
        extra_presence = {}
        for relative in self.state["extra_config_paths"]:
            path = root + "/" + relative
            data = self.optional(ftp, path)
            extra_presence[path] = data is not None
            if data is not None:
                files.append(path)
        return {"files": sorted(set(files)), "directories": sorted(directories),
                "extra_presence": extra_presence}

    def optional(self, ftp, path):
        root = self.state["live"]
        require(path.startswith(root + "/"), "read outside product root")
        here = root
        pieces = path[len(root) + 1:].split("/")
        for i, part in enumerate(pieces):
            rows = _listing(ftp, here)
            # Reject differently cased aliases on FAT before touching anything.
            require(not any(n.casefold() == part.casefold() and n != part for n in rows),
                    "case alias in device target")
            if part not in rows:
                return None
            if i == len(pieces) - 1:
                require(not rows[part], "file target is a directory")
                return self.remote.get(ftp, path, MAX_FILE)
            require(rows[part], "parent is not a directory")
            here += "/" + part

    def protect(self, ftp, state_dir):
        inventory = self.inventory(ftp)
        protected = {}
        blobs = Path(state_dir) / "protected-blobs"
        blobs.mkdir()
        for path in inventory["files"]:
            data = self.remote.get(ftp, path, MAX_FILE)
            checksum = digest(data)
            local = blobs / checksum
            # Deduplication is local-only, after fresh remote bytes were read.
            if local.exists():
                require(digest(local.read_bytes()) == checksum, "local backup corrupt")
            else:
                with local.open("xb") as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
            protected[path] = {"sha256": checksum, "size": len(data), "blob": checksum}
        require(self.inventory(ftp) == inventory, "user inventory changed during capture")
        self.state["protection"] = {"inventory": inventory, "files": protected}
        self.check_protection(ftp)

    def check_protection(self, ftp):
        before = self.state["protection"]
        require(self.inventory(ftp) == before["inventory"], "user inventory changed")
        for path, expected in before["files"].items():
            data = self.remote.get(ftp, path, MAX_FILE)
            require(len(data) == expected["size"] and digest(data) == expected["sha256"],
                    "user content changed: " + path)
        require(self.inventory(ftp) == before["inventory"], "user inventory changed during verification")

    def mkdirs(self, ftp, path):
        if path == self.state["live"]:
            return
        require(path.startswith(self.state["live"] + "/"), "mkdir outside product root")
        self.mkdirs(ftp, posixpath.dirname(path))
        rows = _listing(ftp, posixpath.dirname(path))
        name = posixpath.basename(path)
        require(not any(n.casefold() == name.casefold() and n != name for n in rows), "directory alias")
        if name in rows:
            require(rows[name], "directory target occupied")
        else:
            self.guard(ftp)
            ftp.mkd(path)


def _rows(package, candidate):
    data = json.loads((package / "delta.json").read_text())
    require(data["candidate"] == candidate and isinstance(candidate.get("commit"), str)
            and re.fullmatch("[0-9a-f]{40}", candidate["commit"]), "candidate mismatch")
    rows, names, components = data["files"], set(), {}
    require(rows and rows[-1]["path"] == "CorsixTH-3DS.3dsx", "executable must be last")
    for row in rows:
        name = _product(row["path"])
        require(name.casefold() not in names, "duplicate or case-colliding target")
        names.add(name.casefold())
        pieces = name.split("/")
        for i in range(1, len(pieces) + 1):
            prefix = "/".join(pieces[:i])
            prior = components.setdefault(prefix.casefold(), prefix)
            require(prior == prefix, "case-colliding parent directory")
        require(isinstance(row["size"], int) and 0 <= row["size"] <= MAX_FILE, "invalid size")
        require(isinstance(row["sha256"], str) and re.fullmatch("[0-9a-f]{64}", row["sha256"]), "invalid hash")
        path = package / "files" / name
        require(path.resolve().is_relative_to((package / "files").resolve()), "payload symlink escapes package")
        payload = path.read_bytes()
        require(len(payload) == row["size"] and digest(payload) == row["sha256"], "payload differs")
    require(not any("/".join(name.split("/")[:i]) in names for name in names
                    for i in range(1, len(name.split("/")))), "file target is another target's parent")
    return rows


def deploy(remote, parse_identity, *, package, state_dir, owner_lock, launcher_sha,
           candidate, source_guard, live="/3ds/corsixth", control="/3ds/ftpd-runner",
           extra_config_paths=()):
    """Run exactly once. Interruptions leave inspectable product backups on SD."""
    package, state_dir = Path(package).resolve(), Path(state_dir).resolve()
    _absolute(live); _absolute(control)
    require(isinstance(launcher_sha, str) and re.fullmatch("[0-9a-f]{64}", launcher_sha), "invalid launcher hash")
    extras = sorted({_relative(p) for p in extra_config_paths})
    require(not any(p in PRODUCTS or p.startswith("Lua/") for p in extras), "config overlaps product")
    rows = _rows(package, candidate)
    with _lock(owner_lock) as local_guard:
        require(not state_dir.exists(), "existing transaction state; inspect instead of resuming")
        source_guard()
        identity = remote.live(launcher_sha)
        require(identity["launcher_sha256"] == launcher_sha and identity.get("boot"), "invalid runner identity")
        state_dir.mkdir(parents=True)
        state = {"schema": "cth3ds.device-update/v1", "phase": "PREFLIGHT", "candidate": candidate,
                 "live": live, "control": control, "launcher_sha256": launcher_sha,
                 "boot": identity["boot"], "extra_config_paths": extras, "files": rows,
                 "owner_lock": str(Path(owner_lock).resolve()),
                 "transaction": live + "/.runner-update-" + uuid.uuid4().hex,
                 "operations": [], "third_party_ftp_exclusion": "NOT_PROVEN"}
        journal = state_dir / "journal.json"
        def checkpoint(): _write(journal, state)
        checkpoint()
        session = _Session(remote, parse_identity, state, local_guard)
        try:
            with session.connection() as ftp:
                require(not any(n.startswith(".runner-update-") for n in _listing(ftp, live)),
                        "stale device transaction requires inspection/archive")
                session.protect(ftp, state_dir)
                for row in rows:
                    old = session.optional(ftp, live + "/" + row["path"])
                    old_hash = digest(old) if old is not None else None
                    if "previous" in row:
                        expected = row["previous"]
                        require(old_hash == (expected["sha256"] if expected else None), "old product differs")
                    require(old_hash != row["sha256"], "unchanged payload must be omitted from delta")
                    row["old_sha256"] = old_hash
                state["phase"] = "PROTECTED"; checkpoint()
            for row in rows:
                with session.connection() as ftp:
                    source_guard()
                    path = state["transaction"] + "/new/" + row["path"]
                    session.mkdirs(ftp, posixpath.dirname(path))
                    payload = (package / "files" / row["path"]).read_bytes()
                    require(len(payload) == row["size"] and digest(payload) == row["sha256"], "payload changed before STOR")
                    state["intent"] = {"op": "STOR", "target": path}; checkpoint()
                    ftp.storbinary("STOR " + path, io.BytesIO(payload), blocksize=262144,
                                   callback=lambda chunk: session.local_guard())
                    require(digest(session.optional(ftp, path)) == row["sha256"], "staged hash differs")
                    state["operations"].append(state.pop("intent")); checkpoint()
            with session.connection() as ftp:
                source_guard()
                session.check_protection(ftp)
                for row in rows:
                    current = session.optional(ftp, live + "/" + row["path"])
                    require((digest(current) if current is not None else None) == row["old_sha256"], "old product changed")
                state["phase"] = "SWITCHING"; checkpoint()
                for row in rows:
                    name = row["path"]
                    dest = live + "/" + name
                    session.mkdirs(ftp, posixpath.dirname(dest))
                    pairs = []
                    if row["old_sha256"] is not None:
                        backup = state["transaction"] + "/old/" + name
                        session.mkdirs(ftp, posixpath.dirname(backup))
                        pairs.append((dest, backup))
                    pairs.append((state["transaction"] + "/new/" + name, dest))
                    for src, target in pairs:
                        session.guard(ftp)
                        require(session.optional(ftp, target) is None, "rename destination occupied")
                        state["intent"] = {"op": "RENAME", "source": src, "target": target}; checkpoint()
                        ftp.rename(src, target)
                        state["operations"].append(state.pop("intent")); checkpoint()
                    require(digest(session.optional(ftp, dest)) == row["sha256"], "published hash differs")
                session.guard(ftp)
                session.check_protection(ftp)
                source_guard()
            state["phase"] = "DEPLOYED_HASH_VERIFIED_NOT_RUN"; checkpoint()
            return state
        except BaseException as exc:
            state.update(phase="INTERRUPTED_REQUIRES_INSPECTION", error_type=type(exc).__name__, error=str(exc))
            checkpoint()
            raise


def _load(state_dir):
    state = json.loads((Path(state_dir) / "journal.json").read_text())
    require(state["schema"] == "cth3ds.device-update/v1", "unknown journal")
    _absolute(state["live"]); _absolute(state["control"])
    require(re.fullmatch(re.escape(state["live"]) + r"/\.runner-update-[0-9a-f]{32}", state["transaction"]), "unsafe transaction path")
    folded = set()
    for row in state["files"]:
        _product(row["path"])
        require(row["path"].casefold() not in folded, "duplicate journal target")
        folded.add(row["path"].casefold())
    return state


def _inspect(session, ftp):
    state = session.state
    session.check_protection(ftp)
    result = {}
    for row in state["files"]:
        name = row["path"]
        locations = {"live": state["live"] + "/" + name,
                     **{k: state["transaction"] + "/" + k + "/" + name for k in ("old", "new", "discarded")}}
        found = {}
        for key, path in locations.items():
            payload = session.optional(ftp, path)
            found[key] = digest(payload) if payload is not None else None
        old, new = row["old_sha256"], row["sha256"]
        require(found["live"] in {None, old, new} and found["old"] in {None, old}
                and found["discarded"] in {None, new}, "unrecognized product bytes; manual inspection required")
        # A failed STOR may leave arbitrary bytes, isolated under new/. No retry
        # or publication of that partial payload is allowed; rollback ignores it.
        require(not (found["live"] == old and old is not None and found["old"] == old), "duplicate old product")
        require(old is None or found["live"] == old or found["old"] == old, "old product unavailable")
        require(not (found["live"] == new and found["discarded"] == new), "duplicate published payload")
        result[name] = found
    return result


def inspect(remote, parse_identity, *, state_dir, owner_lock):
    """Read-only recovery inspection, requiring the original runner boot/idle."""
    with _lock(owner_lock) as local_guard:
        state = _load(state_dir)
        require(state["owner_lock"] == str(Path(owner_lock).resolve()), "different owner lock")
        require("protection" in state and all("old_sha256" in row for row in state["files"]),
                "preflight did not finish; no product switch authorized")
        session = _Session(remote, parse_identity, state, local_guard)
        with session.connection() as ftp:
            return {"phase": state["phase"], "files": _inspect(session, ftp), "remote_writes": 0}


def rollback(remote, parse_identity, *, state_dir, owner_lock):
    """Explicit safe rollback. Unknown bytes/user changes cause zero new writes.

    An interrupted rollback can be inspected and explicitly called again. It
    preserves new payloads under discarded/; user files are never destinations.
    """
    state_dir = Path(state_dir)
    with _lock(owner_lock) as local_guard:
        state = _load(state_dir)
        require(state["owner_lock"] == str(Path(owner_lock).resolve()), "different owner lock")
        require("protection" in state and all("old_sha256" in row for row in state["files"]),
                "preflight did not finish; no product switch authorized")
        session = _Session(remote, parse_identity, state, local_guard)
        def checkpoint(): _write(state_dir / "journal.json", state)
        with session.connection() as ftp:
            observed = _inspect(session, ftp)  # Validate every target before any write.
            try:
                state["phase"] = "ROLLING_BACK"; checkpoint()
                for row in reversed(state["files"]):
                    name = row["path"]
                    current = observed[name]
                    pairs = []
                    if current["live"] == row["sha256"]:
                        discarded = state["transaction"] + "/discarded/" + name
                        session.mkdirs(ftp, posixpath.dirname(discarded))
                        pairs.append((state["live"] + "/" + name, discarded))
                    if row["old_sha256"] is not None and current["live"] != row["old_sha256"]:
                        pairs.append((state["transaction"] + "/old/" + name, state["live"] + "/" + name))
                    for src, dest in pairs:
                        session.guard(ftp)
                        require(session.optional(ftp, dest) is None, "rollback destination occupied")
                        expected = row["old_sha256"] if "/old/" in src else row["sha256"]
                        require(digest(session.optional(ftp, src)) == expected, "rollback source changed")
                        state["intent"] = {"op": "ROLLBACK_RENAME", "source": src, "target": dest}; checkpoint()
                        ftp.rename(src, dest)
                        state["operations"].append(state.pop("intent")); checkpoint()
                    result = session.optional(ftp, state["live"] + "/" + name)
                    require((digest(result) if result is not None else None) == row["old_sha256"], "rollback verification differs")
                session.check_protection(ftp)
                state["phase"] = "ROLLED_BACK_HASH_VERIFIED_NOT_RUN"; checkpoint()
                return state
            except BaseException as exc:
                state.update(phase="ROLLBACK_INTERRUPTED_REQUIRES_INSPECTION", error_type=type(exc).__name__, error=str(exc))
                checkpoint()
                raise
