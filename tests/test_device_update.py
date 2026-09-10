"""In-memory FTP fault tests; no device acceptance or network operations."""
from contextlib import contextmanager
import copy
import json
import fcntl
from pathlib import Path
import posixpath
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import device_update as update


LIVE = "/3ds/corsixth"
CONTROL = "/3ds/ftpd-runner"
LAUNCHER = "a" * 64


class FakeFTP:
    def __init__(self):
        self.files = {}
        self.dirs = {"/", "/3ds", LIVE, CONTROL, LIVE + "/Saves", LIVE + "/Saves/Autosaves", LIVE + "/Lua"}
        self.writes = []
        self.events = []
        self.hook = lambda event, path: None

    def retrlines(self, command, callback):
        path = command.removeprefix("LIST ")
        if path not in self.dirs:
            raise OSError("missing directory " + path)
        self.events.append(("list", path))
        self.hook("list", path)
        entries = {p: True for p in self.dirs if p != "/" and posixpath.dirname(p) == path}
        entries.update({p: False for p in self.files if posixpath.dirname(p) == path})
        for entry, directory in sorted(entries.items()):
            callback(("drwxr-xr-x" if directory else "-rw-r--r--") + " 1 u g 1 Jan 1 00:00 " + posixpath.basename(entry))

    def mkd(self, path):
        self.hook("mkdir", path)
        if path in self.dirs or path in self.files or posixpath.dirname(path) not in self.dirs:
            raise OSError("invalid mkdir")
        self.writes.append(("mkdir", path)); self.dirs.add(path)

    def storbinary(self, command, stream, blocksize=8192, callback=None):
        path = command.removeprefix("STOR ")
        self.hook("before_store", path)
        self.files[path] = b""
        self.writes.append(("store", path))
        while True:
            chunk = stream.read(blocksize)
            if not chunk:
                break
            self.files[path] += chunk
            if callback:
                callback(chunk)
            self.hook("store_chunk", path)
        self.hook("after_store", path)

    def rename(self, source, target):
        self.hook("before_rename", source)
        if source not in self.files or target in self.files or posixpath.dirname(target) not in self.dirs:
            raise OSError("invalid rename")
        self.files[target] = self.files.pop(source)
        self.writes.append(("rename", source, target))
        self.hook("after_rename", source)


class FakeRemote:
    def __init__(self, ftp):
        self.ftp = ftp
        self.identity = {"boot": "boot-one", "launcher_sha256": LAUNCHER}
        self.opened = 0

    @contextmanager
    def connection(self):
        self.opened += 1
        try:
            yield self.ftp
        finally:
            self.opened -= 1

    def live(self, sha):
        return dict(self.identity)

    def get(self, ftp, path, limit):
        self.ftp.hook("get", path)
        if path == CONTROL + "/device.kv":
            return json.dumps(self.identity).encode()
        result = self.ftp.files[path]
        if len(result) > limit:
            raise ValueError("limit")
        return result


class DeviceUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cth3ds-update-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        self.package.mkdir()
        self.ftp = FakeFTP()
        self.remote = FakeRemote(self.ftp)
        self.candidate = {"commit": "b" * 40}
        self.ftp.files.update({LIVE + "/Saves/Slot1.sav": b"new-user-save", LIVE + "/Saves/Autosaves/new.sav": b"auto",
                               LIVE + "/config.txt": b"language=chinese", LIVE + "/hotkeys.txt": b"keys",
                               LIVE + "/settings.ini": b"other-settings", LIVE + "/Lua/old.lua": b"old-lua",
                               LIVE + "/loose-assets.json": b"old-loose-assets", LIVE + "/private-media.json": b"old-private-media",
                               LIVE + "/CorsixTH-3DS.3dsx": b"old-executable", LIVE + "/unrelated.dat": b"large immutable asset"})
        self.original = copy.deepcopy(self.ftp.files)
        self.rows = []
        for name, value in [("Lua/old.lua", b"new-lua"), ("CorsixTH-SC-subset.ttf", b"new-font"),
                            ("loose-assets.json", b"new-loose-assets"), ("private-media.json", b"new-private-media"),
                            ("CorsixTH-3DS.3dsx", b"new-executable")]:
            path = self.package / "files" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
            self.rows.append({"path": name, "size": len(value), "sha256": update.digest(value)})
        self.write_delta()

    def write_delta(self):
        (self.package / "delta.json").write_text(json.dumps({"candidate": self.candidate, "files": self.rows}))

    def args(self):
        return dict(package=self.package, state_dir=self.root / "state", owner_lock=self.root / "device.lock",
                    candidate=self.candidate, source_guard=lambda: None, launcher_sha=LAUNCHER)

    def deploy(self):
        return update.deploy(self.remote, json.loads, **self.args())

    def recover_args(self):
        return dict(state_dir=self.root / "state", owner_lock=self.root / "device.lock")

    def assert_user_untouched(self):
        for path, value in self.original.items():
            if "/Saves/" in path or path.endswith(("config.txt", "hotkeys.txt", "settings.ini", "unrelated.dat")):
                self.assertEqual(self.ftp.files[path], value)
        for operation in self.ftp.writes:
            self.assertFalse(any("/Saves/" in p or p.endswith(("config.txt", "hotkeys.txt", "settings.ini")) for p in operation[1:]))

    def test_dynamic_inventory_new_saves_font_binary_last_and_full_hashes(self):
        # A changed/new save before THIS invocation is authoritative, irrespective
        # of the old release's save count and old hashes.
        for i in range(31):
            self.ftp.files[LIVE + f"/Saves/extra{i}.sav"] = str(i).encode()
        result = self.deploy()
        self.assertEqual(result["phase"], "DEPLOYED_HASH_VERIFIED_NOT_RUN")
        self.assertEqual(len(result["protection"]["files"]), 36)
        self.assertNotIn(LIVE + "/unrelated.dat", result["protection"]["files"])
        for name in ("loose-assets.json", "private-media.json"):
            self.assertNotIn(LIVE + "/" + name, result["protection"]["files"])
            self.assertTrue(self.ftp.files[LIVE + "/" + name].startswith(b"new-"))
        publications = [op[2] for op in self.ftp.writes if op[0] == "rename" and "/.runner-update-" not in op[2]]
        self.assertEqual(publications[-1], LIVE + "/CorsixTH-3DS.3dsx")
        self.assertEqual(self.ftp.files[LIVE + "/CorsixTH-SC-subset.ttf"], b"new-font")
        for row in result["protection"]["files"].values():
            self.assertEqual(update.digest((self.root / "state/protected-blobs" / row["blob"]).read_bytes()), row["sha256"])
        self.assert_user_untouched()
        self.assertEqual(self.remote.opened, 0)

    def test_new_save_appears_during_stage_aborts_before_switch(self):
        def hook(event, path):
            if event == "after_store":
                self.ftp.files[LIVE + "/Saves/arrived.sav"] = b"keep-me"
        self.ftp.hook = hook
        with self.assertRaisesRegex(update.UpdateError, "inventory changed"):
            self.deploy()
        self.assertFalse(any(op[0] == "rename" for op in self.ftp.writes))
        self.assertEqual(self.ftp.files[LIVE + "/Saves/arrived.sav"], b"keep-me")

    def test_existing_save_changes_during_stage_aborts_without_reversion(self):
        def hook(event, path):
            if event == "after_store":
                self.ftp.files[LIVE + "/Saves/Slot1.sav"] = b"newer-session"
        self.ftp.hook = hook
        with self.assertRaisesRegex(update.UpdateError, "content changed"):
            self.deploy()
        self.assertFalse(any(op[0] == "rename" for op in self.ftp.writes))
        self.assertEqual(self.ftp.files[LIVE + "/Saves/Slot1.sav"], b"newer-session")

    def test_upload_disconnect_is_terminal_and_explicit_rollback_preserves_user(self):
        def hook(event, path):
            if event == "store_chunk":
                self.ftp.files[path] = self.ftp.files[path][:3]
                raise ConnectionError("lost STOR reply")
        self.ftp.hook = hook
        with self.assertRaises(ConnectionError):
            self.deploy()
        self.assertEqual(json.loads((self.root / "state/journal.json").read_text())["phase"], "INTERRUPTED_REQUIRES_INSPECTION")
        with self.assertRaisesRegex(update.UpdateError, "existing transaction"):
            self.deploy()
        self.ftp.hook = lambda event, path: None
        report = update.inspect(self.remote, json.loads, **self.recover_args())
        self.assertEqual(report["remote_writes"], 0)
        result = update.rollback(self.remote, json.loads, **self.recover_args())
        self.assertEqual(result["phase"], "ROLLED_BACK_HASH_VERIFIED_NOT_RUN")
        self.assert_user_untouched()

    def test_lost_rename_reply_is_inspected_and_rolls_back_exact_product(self):
        def hook(event, path):
            if event == "after_rename":
                raise ConnectionError("rename committed but reply lost")
        self.ftp.hook = hook
        with self.assertRaises(ConnectionError):
            self.deploy()
        self.ftp.hook = lambda event, path: None
        update.rollback(self.remote, json.loads, **self.recover_args())
        self.assertEqual(self.ftp.files[LIVE + "/Lua/old.lua"], b"old-lua")
        self.assert_user_untouched()

    def test_full_rollback_removes_new_font_preserves_backups_and_no_user_writes(self):
        self.deploy()
        update.rollback(self.remote, json.loads, **self.recover_args())
        self.assertNotIn(LIVE + "/CorsixTH-SC-subset.ttf", self.ftp.files)
        self.assertEqual(self.ftp.files[LIVE + "/CorsixTH-3DS.3dsx"], b"old-executable")
        self.assertTrue(any("/discarded/CorsixTH-SC-subset.ttf" in path for path in self.ftp.files))
        self.assert_user_untouched()

    def test_rollback_refuses_new_user_data_without_any_mutation(self):
        self.deploy()
        self.ftp.files[LIVE + "/Saves/later.sav"] = b"later"
        before = len(self.ftp.writes)
        with self.assertRaisesRegex(update.UpdateError, "inventory changed"):
            update.rollback(self.remote, json.loads, **self.recover_args())
        self.assertEqual(len(self.ftp.writes), before)
        self.assertEqual(self.ftp.files[LIVE + "/Saves/later.sav"], b"later")

    def test_rollback_refuses_foreign_product_or_changed_boot(self):
        self.deploy()
        self.ftp.files[LIVE + "/Lua/old.lua"] = b"third-party-change"
        before = len(self.ftp.writes)
        with self.assertRaisesRegex(update.UpdateError, "unrecognized product"):
            update.rollback(self.remote, json.loads, **self.recover_args())
        self.assertEqual(len(self.ftp.writes), before)
        self.remote.identity["boot"] = "another-boot"
        with self.assertRaisesRegex(update.UpdateError, "boot changed"):
            update.inspect(self.remote, json.loads, **self.recover_args())

    def test_stale_remote_transaction_and_busy_runner_block_all_writes(self):
        self.ftp.dirs.add(LIVE + "/.runner-update-stale")
        with self.assertRaisesRegex(update.UpdateError, "stale device transaction"):
            self.deploy()
        self.assertEqual(self.ftp.writes, [])
        # New receipt location does not authorize ignoring runner ownership.
        args = self.args(); args["state_dir"] = self.root / "another-state"
        self.ftp.files[CONTROL + "/ready"] = b"pending"
        with self.assertRaisesRegex(update.UpdateError, "runner busy"):
            update.deploy(self.remote, json.loads, **args)
        self.assertEqual(self.ftp.writes, [])

    def test_allowlist_traversal_collision_and_previous_identity_fail_closed(self):
        for bad in ("../config.txt", "Saves/Slot1.sav", "Lua/../config.txt", "Lua\\x.lua", "Lua//x.lua", "Lua/x.lua\nDELE",
                    "config.txt", "hotkeys.txt", "arbitrary.json", "Settings/private-media.json"):
            with self.subTest(path=bad):
                with self.assertRaises(update.UpdateError):
                    update._product(bad)
        self.rows.insert(1, dict(self.rows[0]))
        self.write_delta()
        with self.assertRaisesRegex(update.UpdateError, "duplicate"):
            self.deploy()
        self.rows.pop(1)
        self.rows[0]["previous"] = {"sha256": "0" * 64}
        self.write_delta()
        with self.assertRaisesRegex(update.UpdateError, "old product differs"):
            self.deploy()
        self.assertEqual(self.ftp.writes, [])
        # Validate shared directory names before opening a device connection.
        self.rows[0].pop("previous")
        for name in ("Lua/Nested/a.lua", "Lua/nested/b.lua"):
            path = self.package / "files" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
            self.rows.insert(0, {"path": name, "size": 1, "sha256": update.digest(b"x")})
        self.write_delta()
        with self.assertRaisesRegex(update.UpdateError, "case-colliding parent"):
            update._rows(self.package, self.candidate)

    def test_case_alias_and_midtransaction_owner_change_fail_closed(self):
        self.ftp.files[LIVE + "/Saves/slot1.sav"] = b"alias"
        with self.assertRaisesRegex(update.UpdateError, "case collision"):
            self.deploy()
        self.assertEqual(self.ftp.writes, [])
        del self.ftp.files[LIVE + "/Saves/slot1.sav"]
        args = self.args(); args["state_dir"] = self.root / "next-state"
        def hook(event, path):
            if event == "after_store":
                args["owner_lock"].rename(self.root / "replaced.lock")
                args["owner_lock"].write_text("replacement")
        self.ftp.hook = hook
        with self.assertRaisesRegex(update.UpdateError, "owner lock replaced"):
            update.deploy(self.remote, json.loads, **args)
        self.assertFalse(any(op[0] == "rename" for op in self.ftp.writes))

    def test_source_guard_drift_and_payload_drift_cannot_publish(self):
        calls = 0
        def guard():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise update.UpdateError("source changed")
        args = self.args(); args["source_guard"] = guard
        with self.assertRaisesRegex(update.UpdateError, "source changed"):
            update.deploy(self.remote, json.loads, **args)
        self.assertEqual(self.ftp.writes, [])
        args = self.args(); args["state_dir"] = self.root / "payload-state"
        def drift(event, path):
            if event == "after_store":
                (self.package / "files/CorsixTH-3DS.3dsx").write_bytes(b"bad-new-payload")
        self.ftp.hook = drift
        with self.assertRaisesRegex(update.UpdateError, "payload changed before STOR"):
            update.deploy(self.remote, json.loads, **args)
        self.assertFalse(any(op[0] == "rename" for op in self.ftp.writes))

    def test_rollback_disconnect_reinspect_and_explicit_retry_is_product_only(self):
        self.deploy()
        def hook(event, path):
            if event == "after_rename":
                raise ConnectionError("rollback rename reply lost")
        self.ftp.hook = hook
        with self.assertRaises(ConnectionError):
            update.rollback(self.remote, json.loads, **self.recover_args())
        self.ftp.hook = lambda event, path: None
        update.inspect(self.remote, json.loads, **self.recover_args())
        update.rollback(self.remote, json.loads, **self.recover_args())
        self.assertEqual(self.ftp.files[LIVE + "/CorsixTH-3DS.3dsx"], b"old-executable")
        self.assert_user_untouched()

    def test_changed_boot_after_stage_and_global_lock_contention_block_publication(self):
        args = self.args()
        with args["owner_lock"].open("a+") as competing:
            fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.deploy()
        self.assertFalse(args["state_dir"].exists())
        self.assertEqual(self.ftp.writes, [])
        def hook(event, path):
            if event == "after_store":
                self.remote.identity["boot"] = "restarted"
        self.ftp.hook = hook
        with self.assertRaisesRegex(update.UpdateError, "boot changed"):
            self.deploy()
        self.assertFalse(any(op[0] == "rename" for op in self.ftp.writes))

    def test_configuration_scope_includes_new_root_config_and_nested_optional_path(self):
        self.ftp.dirs.add(LIVE + "/Settings")
        self.ftp.files[LIVE + "/Settings/media.cfg"] = b"voice=zh"
        self.ftp.files[LIVE + "/preferences.JSON"] = b"{}"
        args = self.args(); args["extra_config_paths"] = ("Settings/media.cfg", "Settings/optional.cfg")
        result = update.deploy(self.remote, json.loads, **args)
        self.assertIn(LIVE + "/Settings/media.cfg", result["protection"]["files"])
        self.assertIn(LIVE + "/preferences.JSON", result["protection"]["files"])
        self.ftp.files[LIVE + "/Settings/optional.cfg"] = b"new-choice"
        before = len(self.ftp.writes)
        with self.assertRaisesRegex(update.UpdateError, "inventory changed"):
            update.rollback(self.remote, json.loads, **self.recover_args())
        self.assertEqual(len(self.ftp.writes), before)


if __name__ == "__main__":
    unittest.main()
