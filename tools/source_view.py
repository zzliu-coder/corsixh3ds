#!/usr/bin/env python3
"""Small single-owner gate and source/build binding for the 3DS game target."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import signal
import time

from integration.common import IntegrationError
from integration.generated_view import RECEIPT, verify_view

OWNER_ENV = ("CTH3DS_SOURCE_OWNER_FD", "CTH3DS_SOURCE_OWNER_LOCK",
             "CTH3DS_SOURCE_OWNER_RECEIPT")
CANCEL_DOMAIN = "CTH3DS_CANCEL_DOMAIN"


def independent_environment() -> dict:
    """Isolate fixture ownership, retaining the outer cancellation domain."""
    return {key: value for key, value in os.environ.items() if key not in OWNER_ENV}


def cancellation_domain() -> int | None:
    """Validate kernel membership before trusting inherited domain metadata."""
    marker = os.environ.get(CANCEL_DOMAIN)
    if marker is None:
        return None
    try:
        supervisor, group = (int(value) for value in marker.split(':'))
        if (supervisor <= 1 or group <= 1 or supervisor == group
                or os.getpgrp() != group or os.getsid(0) != group
                or os.getpgid(supervisor) == group):
            raise ValueError('wrong cancellation domain membership')
    except (ValueError, OSError) as error:
        raise IntegrationError('invalid inherited cancellation domain') from error
    return group


def domain_worker(supervisor: int, command: list[str]) -> None:
    # Popen establishes the one session before this shim supplies its real PGID.
    # exec retains that membership and the explicitly inherited owner FD.
    if (supervisor != os.getppid() or os.getpid() != os.getpgrp()
            or os.getsid(0) != os.getpgrp() or CANCEL_DOMAIN in os.environ):
        raise IntegrationError('invalid cancellation domain worker')
    env = dict(os.environ, **{CANCEL_DOMAIN: f'{supervisor}:{os.getpgrp()}'})
    os.execvpe(command[0], command, env)


def _live_group(group: int) -> bool:
    # Orphan grandchildren cannot be waitpid()'d by this process. Zombies have
    # stopped executing; ps distinguishes them from live workers on Linux/macOS.
    rows = subprocess.check_output(['ps', '-axo', 'pgid=,stat='], text=True)
    return any(len(parts := row.split()) >= 2 and parts[0] == str(group)
               and not parts[1].startswith('Z') for row in rows.splitlines())


def supervise(command: list[str], env: dict, pass_fds=()) -> int:
    """Only the outer supervisor creates/cancels/waits for the worker group."""
    if cancellation_domain() is not None:
        # Fixture FD isolation and a private owner do not create another session.
        # The outer supervisor signals this entire group and performs final KILL
        # and liveness checks. Nested waiters never race it with another deadline.
        cancelled = []
        def observe(number, _frame):
            if not cancelled: cancelled.append(number)
        previous = {number: signal.signal(number, observe)
                    for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
        try:
            result = subprocess.Popen(command, env=env, pass_fds=pass_fds).wait()
            return 128 + cancelled[0] if cancelled else result
        finally:
            if cancelled and env.get('CTH3DS_SOURCE_OWNER_RECEIPT'):
                Path(env['CTH3DS_SOURCE_OWNER_RECEIPT']).unlink(missing_ok=True)
            for number, handler in previous.items(): signal.signal(number, handler)
    process = None
    cancelled = []
    def forward(number, _frame):
        if not cancelled:
            cancelled.append(number)
        if process is not None:
            try: os.killpg(process.pid, number)
            except ProcessLookupError: pass
    previous = {number: signal.signal(number, forward)
                for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
    try:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                    '_domain-worker', str(os.getpid()), '--', *command],
                                   env=env, pass_fds=pass_fds,
                                   start_new_session=True)
        if cancelled: forward(cancelled[0], None)
        while not cancelled:
            try:
                result = process.wait(timeout=.1)
                if cancelled: break
                return result
            except subprocess.TimeoutExpired: pass
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            process.poll()  # reap the direct child before inspecting grandchildren
            if not _live_group(process.pid): break
            time.sleep(.02)
        else:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        process.wait()
        deadline = time.monotonic() + 3
        while _live_group(process.pid):
            if time.monotonic() >= deadline:
                raise IntegrationError('cancelled worker group did not stop')
            time.sleep(.02)
        return 128 + cancelled[0]
    finally:
        # Run after the worker group has stopped, so it cannot republish success.
        if cancelled and env.get('CTH3DS_SOURCE_OWNER_RECEIPT'):
            Path(env['CTH3DS_SOURCE_OWNER_RECEIPT']).unlink(missing_ok=True)
        for number, handler in previous.items(): signal.signal(number, handler)


def own(lock: Path, command: list[str]) -> int:
    cancellation_domain()
    lock = lock.absolute()
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.is_symlink():
        raise IntegrationError("source-owner lock cannot be a link")
    inherited = os.environ.get("CTH3DS_SOURCE_OWNER_FD")
    if inherited:
        try:
            fd = int(inherited)
            info, expected = os.fstat(fd), lock.stat()
            if (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino):
                raise ValueError("different owner lock")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ValueError, OSError) as error:
            raise IntegrationError("invalid inherited source owner") from error
        return supervise(command, dict(os.environ, CTH3DS_SOURCE_OWNER_LOCK=str(lock)), (fd,))
    with lock.open("a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        env = dict(os.environ, CTH3DS_SOURCE_OWNER_FD=str(stream.fileno()),
                   CTH3DS_SOURCE_OWNER_LOCK=str(lock))
        return supervise(command, env, (stream.fileno(),))


def require_owner(lock: Path) -> None:
    cancellation_domain()
    # Invocations use one inherited open file description through shell/Python.
    # Holding the lock spans source selection, clean/configure/build and package.
    fd = int(os.environ.get("CTH3DS_SOURCE_OWNER_FD", "-1"))
    try:
        a, b = os.fstat(fd), lock.stat()
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
            raise OSError("owner mismatch")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        raise IntegrationError("source operation requires its unique owner") from error


def select(view: Path, alias: Path, overlay: Path, lock: Path) -> None:
    require_owner(lock)
    verify_view(view.resolve(), overlay.resolve())
    if alias.exists() and not alias.is_symlink():
        raise IntegrationError("source alias contains a real directory; preserve it and choose a new external directory")
    if alias.resolve() == view.resolve():
        return
    # Exclusively named sibling; only this link is replaced. A complete old view
    # stays available for rollback. This does not claim a multi-file transaction.
    fd, name = tempfile.mkstemp(prefix=".source-select-", dir=alias.parent)
    os.close(fd)
    temporary = Path(name)
    temporary.unlink()
    try:
        temporary.symlink_to(os.path.relpath(view.resolve(), alias.parent))
        temporary.replace(alias)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def binary_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(view: Path, overlay: Path, binary: Path) -> dict:
    receipt = verify_view(view.resolve(), overlay.resolve())
    return {"format": 1, "view_sha256": receipt["view_sha256"],
            "input_sha256": receipt["input_sha256"],
            "source_realpath": str(view.resolve()), "binary_sha256": binary_hash(binary)}


def verify_build(view: Path, overlay: Path, binary: Path, manifest: Path) -> dict:
    current = binding(view, overlay, binary)
    stored = json.loads(manifest.read_text())
    if stored.get("generated_source") != current:
        raise IntegrationError("binary and complete generated source do not match successful build")
    for key, expression in (("source_commit", "HEAD"), ("source_tree", "HEAD^{tree}")):
        actual = subprocess.check_output(
            ["git", "-C", str(overlay), "rev-parse", expression], text=True).strip()
        if stored.get(key) != actual:
            raise IntegrationError("successful build belongs to another port revision")
    return current


def verify_staged_build(expected: dict, view: Path, overlay: Path, binary: Path,
                        manifest: Path, staged_binary: Path) -> dict:
    current = verify_build(view, overlay, binary, manifest)
    if current != expected or binary_hash(staged_binary) != expected['binary_sha256']:
        raise IntegrationError('build changed while preparing candidate or staged binary differs')
    return current


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--lock", type=Path, required=True)
    run.add_argument("args", nargs=argparse.REMAINDER)
    isolated = commands.add_parser("isolated")
    isolated.add_argument("args", nargs=argparse.REMAINDER)
    worker = commands.add_parser('_domain-worker', help=argparse.SUPPRESS)
    worker.add_argument('supervisor', type=int)
    worker.add_argument('args', nargs=argparse.REMAINDER)
    owner = commands.add_parser("check-owner")
    owner.add_argument("--lock", type=Path, required=True)
    pick = commands.add_parser("select")
    pick.add_argument("--alias", type=Path, required=True)
    pick.add_argument("--lock", type=Path, required=True)
    for name in ("verify", "bind", "verify-build"):
        entry = commands.add_parser(name)
        entry.add_argument("--view", type=Path, required=True)
        entry.add_argument("--overlay", type=Path, required=True)
        if name != "verify":
            entry.add_argument("--binary", type=Path, required=True)
            entry.add_argument("--manifest", type=Path, required=True)
    pick.add_argument("--view", type=Path, required=True)
    pick.add_argument("--overlay", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == '_domain-worker':
            command = args.args[1:] if args.args[:1] == ['--'] else args.args
            domain_worker(args.supervisor, command)
        if args.command == "isolated":
            command = args.args[1:] if args.args[:1] == ["--"] else args.args
            return supervise(command, independent_environment())
        if args.command == "run":
            command = args.args[1:] if args.args[:1] == ["--"] else args.args
            return own(args.lock, command)
        if args.command == "check-owner":
            require_owner(args.lock)
            return 0
        if args.command == "select":
            select(args.view, args.alias, args.overlay, args.lock)
        elif args.command == "verify":
            verify_view(args.view.resolve(), args.overlay.resolve())
        elif args.command == "verify-build":
            verify_build(args.view, args.overlay, args.binary, args.manifest)
        else:
            result = json.loads(args.manifest.read_text())
            result["generated_source"] = binding(args.view, args.overlay, args.binary)
            args.manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0
    except (IntegrationError, OSError, ValueError) as error:
        print("source-view error: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
