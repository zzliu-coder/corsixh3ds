"""AR3 complete assembly and consumer contracts; no ARM/device claims."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import integrate_corsixth as assembly
from integration.generated_view import (RECEIPT, SourceView, inventory,
                                        input_inventory, verify_view, seal_view)
from integration.common import IntegrationError
from integration.final_sources import PINNED_INPUTS
from source_view import binding, verify_build, independent_environment
from support.pinned_upstream import original_sources


class GeneratedViewTests(unittest.TestCase):
    def invoke(self, source, *flags):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return assembly.main([str(source), "--overlay-root", str(ROOT), *map(str, flags)])

    def test_complete_dry_run_and_publish_share_late_transform_and_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = original_sources(root / "original")
            before, overlay = inventory(source), input_inventory(ROOT)
            for name, replacement in (("patch_media", mock.Mock(side_effect=IntegrationError("late"))),
                                      ("check_integrated", mock.Mock(return_value=["final check"]))):
                for mode in (("--dry-run",), ("--output", root / "view")):
                    with self.subTest(stage=name, mode=mode), mock.patch.object(assembly, name, replacement):
                        self.assertEqual(self.invoke(source, *mode), 2)
                        self.assertFalse((root / "view").exists())
                        self.assertEqual(inventory(source), before)
                        self.assertEqual(input_inventory(ROOT), overlay)
            self.assertEqual(self.invoke(source, "--dry-run"), 0)
            self.assertEqual(self.invoke(source, "--output", root / "view"), 0)
            self.assertEqual(self.invoke(root / "view", "--check"), 0)
            self.assertEqual(inventory(source), before)

    def test_complete_identity_includes_world_staff_and_all_lua(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = original_sources(root / "original")
            view = root / "view"
            assembly.generate_private(source, ROOT, view)
            receipt = verify_view(view, ROOT)
            for name in ("world.lua", "entities/humanoids/staff.lua", "persistance.lua",
                         "3ds/operations.lua", "3ds/platform.lua"):
                path = view / "CorsixTH/Lua" / name
                key = path.relative_to(view).as_posix()
                self.assertIn(key, receipt["files"])
                before = path.read_bytes()
                path.write_bytes(before + b"\n-- identity drift")
                with self.assertRaises(IntegrationError):
                    verify_view(view, ROOT)
                path.write_bytes(before)
            self.assertNotIn(RECEIPT, receipt["files"])
            again = root / "repeat"
            assembly.generate_private(view, ROOT, again)
            self.assertEqual(inventory(view), inventory(again))
            self.assertEqual(verify_view(again, ROOT), receipt)
            # Final files are ordinary captured inputs, used from the explicit
            # overlay even when the executing tools live in another checkout.
            from integration.generated_view import snapshot_overlay
            overlay = root / "overlay"
            snapshot_overlay(ROOT, overlay)
            for name in PINNED_INPUTS:
                key = "upstream_overrides/" + name
                self.assertIn(key, receipt["inputs"])
                final = overlay / key
                final.write_bytes(final.read_bytes() + b"\n-- captured overlay identity\n")
            custom = root / "custom"
            assembly.generate_private(source, overlay, custom)
            changed = verify_view(custom, overlay)
            self.assertNotEqual(changed["input_sha256"], receipt["input_sha256"])
            for name in PINNED_INPUTS:
                key = "upstream_overrides/" + name
                self.assertEqual((custom / name).read_bytes(), (overlay / key).read_bytes())
                self.assertEqual(changed["inputs"][key], input_inventory(overlay)[key])
            with self.assertRaises(IntegrationError):
                verify_view(custom, ROOT)

    def test_private_authority_roots_keep_inode_and_reject_links_nonempty_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = original_sources(root / "original")
            empty = root / "empty"; empty.mkdir()
            inode = empty.stat().st_ino
            with mock.patch.object(assembly, "patch_media", side_effect=IntegrationError("late")):
                with self.assertRaises(IntegrationError):
                    assembly.generate_private(source, ROOT, empty)
            self.assertEqual(empty.stat().st_ino, inode)
            self.assertEqual(list(empty.iterdir()), [])
            assembly.generate_private(source, ROOT, empty)
            self.assertEqual(empty.stat().st_ino, inode)
            before = inventory(empty)
            with self.assertRaises(IntegrationError):
                assembly.generate_private(source, ROOT, empty)
            linked = root / "linked"; linked.symlink_to(empty, target_is_directory=True)
            for output in (linked, source / "nested"):
                with self.assertRaises(IntegrationError):
                    assembly.generate_private(source, ROOT, output)
            self.assertEqual(inventory(empty), before)
            with self.assertRaises(IntegrationError):
                assembly.generate_private(linked, ROOT, root / "linked-input")

    def test_publication_failure_and_occupied_output_preserve_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = original_sources(root / "original")
            before = inventory(source)
            with mock.patch("integration.generated_view.os.symlink", side_effect=OSError("publish")):
                self.assertEqual(self.invoke(source, "--output", root / "view"), 2)
            self.assertEqual(list(root.glob(".cth3ds-view-*")), [])
            output = root / "view"; output.mkdir()
            self.assertEqual(self.invoke(source, "--output", output), 2)
            self.assertTrue(output.is_dir())
            self.assertEqual(inventory(source), before)
            self.assertEqual(self.invoke(source), 2)

    def test_legal_whitespace_and_added_input_rejected_identically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = original_sources(root / "original")
            gfx = source / "CorsixTH/Src/th_gfx_sdl.cpp"
            body = gfx.read_text()
            anchor = "bool render_target::start_frame() {"
            self.assertEqual(body.count(anchor), 1)
            gfx.write_text(body.replace(anchor, "bool render_target::start_frame()\n{"))
            before = inventory(source)
            self.assertEqual(self.invoke(source, "--dry-run"), 2)
            self.assertEqual(self.invoke(source, "--output", root / "view"), 2)
            self.assertEqual(inventory(source), before)
            gfx.write_text(body)
            # Unknown edits in either final-source input must fail identically
            # before publication, retaining the exact edited input and overlay.
            for name in PINNED_INPUTS:
                path = source / name
                original = path.read_bytes()
                path.write_bytes(original + b"\n-- unknown upstream edit\n")
                before, overlay = inventory(source), input_inventory(ROOT)
                for flags in (("--dry-run",), ("--output", root / "rejected"),
                              ("--private-output", root / "private-rejected")):
                    with self.subTest(source=name, mode=flags[0]):
                        self.assertEqual(self.invoke(source, *flags), 2)
                        self.assertEqual(inventory(source), before)
                        self.assertEqual(input_inventory(ROOT), overlay)
                        self.assertFalse((root / "rejected").exists())
                        self.assertFalse((root / "private-rejected").exists())
                        self.assertEqual(list(root.glob(".cth3ds-view-*")), [])
                path.write_bytes(original)
            # Inventory additions are detected, not only known-file mutations.
            with SourceView(source, ROOT, None) as view:
                (source / "added.txt").write_text("editor race")
                with self.assertRaises(IntegrationError):
                    view.verify_inputs()

    def test_build_binding_rejects_mixed_lua_binary_and_old_port(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = original_sources(root / "original")
            view = root / "view"; assembly.generate_private(source, ROOT, view)
            binary = root / "game"; binary.write_bytes(b"host-test-binary")
            proof = root / "build.json"
            git = lambda ref: subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", ref], text=True).strip()
            record = {"source_commit": git("HEAD"), "source_tree": git("HEAD^{tree}"),
                      "generated_source": binding(view, ROOT, binary)}
            proof.write_text(json.dumps(record))
            verify_build(view, ROOT, binary, proof)
            binary.write_bytes(b"partial-failed-build")
            with self.assertRaises(IntegrationError):
                verify_build(view, ROOT, binary, proof)
            binary.write_bytes(b"host-test-binary")
            record["source_commit"] = "0" * 40; proof.write_text(json.dumps(record))
            with self.assertRaises(IntegrationError):
                verify_build(view, ROOT, binary, proof)
            proof.unlink()
            with self.assertRaises(FileNotFoundError):
                verify_build(view, ROOT, binary, proof)

    def test_owner_serializes_real_processes_and_rejects_forged_fd(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); lock = root / "owner.lock"
            events = root / "events"
            tool = ROOT / "tools/source_view.py"
            code = ("import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
                    "f=p.open('a'); f.write(sys.argv[2]+' begin\\n'); f.flush(); "
                    "time.sleep(.15); f.write(sys.argv[2]+' end\\n'); f.close()")
            def launch(label):
                return subprocess.Popen([sys.executable, str(tool), "run", "--lock", str(lock),
                    "--", sys.executable, "-c", code, str(events), label], env=independent_environment())
            a = launch("A"); b = launch("B")
            self.assertEqual(a.wait(timeout=5), 0); self.assertEqual(b.wait(timeout=5), 0)
            lines = events.read_text().splitlines()
            self.assertIn(lines, (["A begin", "A end", "B begin", "B end"],
                                  ["B begin", "B end", "A begin", "A end"]))
            bad = subprocess.run([sys.executable, str(tool), "check-owner", "--lock", str(lock)],
                env=dict(os.environ, CTH3DS_SOURCE_OWNER_FD="999999"), capture_output=True)
            self.assertEqual(bad.returncode, 2)

    def test_fresh_verifier_consumes_same_real_view_and_rejects_unsafe_roots(self):
        import importlib.util
        import tarfile
        spec = importlib.util.spec_from_file_location("ar3_producer", ROOT / "scripts/verify_runtime_core_v2.py")
        producer = importlib.util.module_from_spec(spec); spec.loader.exec_module(producer)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); original = original_sources(root / "original")
            archive = root / "pin-fixture.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(original, arcname="CorsixTH-" + assembly.UPSTREAM_COMMIT)
            snapshot = root / "snapshot"; generated = root / "generated"; generated.mkdir()
            inode = generated.stat().st_ino
            up, combined = producer.prepare_sources(ROOT, archive, snapshot, generated,
                root / "up.json", root / "generated.json", "test-real-kernel")
            self.assertEqual(up["file_count"], 44)
            self.assertEqual(generated.stat().st_ino, inode)
            self.assertEqual(combined["file_count"], len(inventory(generated)))
            verify_view(generated, ROOT)
            alias = root / "alias"; alias.symlink_to(root / "absent")
            for target in (generated, alias):
                with self.assertRaises(RuntimeError):
                    producer.prepare_sources(ROOT, archive, root / "new-snapshot", target,
                        root / "new-up.json", root / "new-generated.json", "reject")
                self.assertFalse((root / "new-snapshot").exists())
            link = generated / "forbidden"; link.symlink_to(root / "up.json")
            with self.assertRaises(RuntimeError):
                producer.source_tree(generated, "test", "generated", "source_xbuild_integrated")
            link.unlink()
            os.link(generated / "CMakeLists.txt", generated / "hard-link")
            with self.assertRaises(RuntimeError):
                producer.source_tree(generated, "test", "generated", "source_xbuild_integrated")

    def test_production_clean_failure_removes_previous_success_receipt(self):
        # Shell control-flow probe only. Fake command-line tools refuse at clean;
        # this cannot produce an ARM artifact or an ARM pass claim.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); original = original_sources(root / "original")
            external = root / "external"; external.mkdir()
            assembly.generate_private(original, ROOT, external / "CorsixTH")
            build = root / "build"; build.mkdir()
            deps = root / "deps"; deps.mkdir()
            (deps / "cth3ds-dependencies.json").write_text("{}")
            devkit = root / "devkit"; (devkit / "cmake").mkdir(parents=True)
            (devkit / "cmake/3DS.cmake").write_text("# never configured by an ARM compiler")
            commands = root / "commands"; commands.mkdir()
            for name in ("arm-none-eabi-gcc", "arm-none-eabi-g++", "arm-none-eabi-ar"):
                command = commands / name; command.write_text("#!/bin/sh\nexit 88\n"); command.chmod(0o755)
            trace = root / "cmake.trace"
            cmake = commands / "cmake"
            cmake.write_text("#!/bin/sh\n"
                "if [ \"$1\" = --version ]; then echo TEST-CONTROL-PROBE; exit 0; fi\n"
                "printf '%s\\n' \"$*\" >> \"$AR3_TRACE\"\n"
                "case \"$*\" in *'--target clean'*) exit 47;; *'--target corsixth_3dsx'*) exit 89;; esac\n"
                "exit 0\n")
            cmake.chmod(0o755)
            success = root / "previous-success.json"; success.write_text("{}")
            env = dict(independent_environment(), CTH3DS_EXTERNAL_DIR=str(external), CTH3DS_BUILD_DIR=str(build),
                CTH3DS_DEPS_PREFIX=str(deps), CTH3DS_BUILD_MANIFEST=str(success),
                CTH3DS_BUILD_EVIDENCE_DIR=str(root / "diagnostics"), DEVKITPRO=str(devkit),
                AR3_TRACE=str(trace), PATH=str(commands) + os.pathsep + os.environ["PATH"])
            env.pop("CTH3DS_SOURCE_OWNER_FD", None)
            run = subprocess.run(["bash", str(ROOT / "scripts/build_3ds.sh"), "--skip-bootstrap"],
                cwd=root, env=env, capture_output=True, text=True, timeout=45)
            self.assertEqual(run.returncode, 47, run.stdout + run.stderr)
            self.assertFalse(success.exists())
            calls = trace.read_text()
            self.assertIn("--target clean", calls)
            self.assertNotIn("--target corsixth_3dsx", calls)

    def test_readonly_source_and_overlay_stay_byte_mode_and_time_identical(self):
        from integration.generated_view import snapshot_overlay
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = original_sources(root / "original")
            overlay = root / "overlay"; snapshot_overlay(ROOT, overlay)
            for tree in (source, overlay):
                for path in tree.rglob("*"):
                    if path.is_file(): path.chmod(path.stat().st_mode & ~0o222)
            def snapshot(tree):
                return {str(path.relative_to(tree)): (path.read_bytes(), path.stat().st_mode,
                        path.stat().st_mtime_ns) for path in tree.rglob("*") if path.is_file()}
            before = snapshot(source), snapshot(overlay)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(assembly.main([str(source), "--overlay-root", str(overlay), "--dry-run"]), 0)
                self.assertEqual(assembly.main([str(source), "--overlay-root", str(overlay),
                                                "--private-output", str(root / "complete")]), 0)
            self.assertEqual((snapshot(source), snapshot(overlay)), before)


if __name__ == "__main__":
    unittest.main()
