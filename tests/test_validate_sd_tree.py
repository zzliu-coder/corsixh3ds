from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from validate_sd_tree import (
    ValidationError,
    validate_sd_tree,
    write_boot_contract,
    write_sd_manifest,
)


CANDIDATE_COMMIT = "1" * 40
CANDIDATE_TREE = "2" * 40


def valid_3dsx() -> bytes:
    return b"3DSX" + struct.pack("<HH", 0x20, 4) + bytes(0x20 - 8)


class ValidateSdTreeTests(unittest.TestCase):
    def make_runtime(self, root: Path) -> Path:
        package = root / "package"
        package.mkdir()
        (package / "CorsixTH-3DS.3dsx").write_bytes(valid_3dsx())
        (package / "CorsixTH.lua").write_text("-- synthetic runtime\n", encoding="utf-8")
        (package / "config.txt").write_text("asset_mode = \"th3ds\"\n", encoding="utf-8")
        (package / "cth3ds-overlay-version.txt").write_text("0.6.1\n", encoding="utf-8")
        for name in ("Bitmap", "Campaigns", "Graphics", "Levels", "Lua"):
            directory = package / name
            directory.mkdir()
            (directory / "synthetic.txt").write_text(name, encoding="utf-8")
        return package

    def add_th3ds_family(self, package: Path) -> None:
        fixture = ROOT / "tests" / "runtime_core_v2" / "fixtures" / "no-level"
        resources = package / "resources"
        (resources / "lang").mkdir(parents=True)
        shutil.copy2(fixture / "bundle.json", resources / "bundle.th3ds.json")
        shutil.copy2(fixture / "core.package.bin", resources / "core.th3ds")
        shutil.copy2(fixture / "lang" / "en.package.bin", resources / "lang" / "en.th3ds")

    def seal(self, package: Path, mode: str = "th3ds") -> dict[str, object]:
        write_boot_contract(
            package,
            asset_mode=mode,
            candidate_commit=CANDIDATE_COMMIT,
            candidate_tree=CANDIDATE_TREE,
        )
        write_sd_manifest(package)
        return validate_sd_tree(package)

    def make_valid_th3ds(self, root: Path) -> Path:
        package = self.make_runtime(root)
        self.add_th3ds_family(package)
        self.seal(package)
        return package

    def test_valid_th3ds_tree_is_hash_bound_and_product_candidate_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_valid_th3ds(Path(temporary))
            result = validate_sd_tree(package, require_mode="th3ds")
            self.assertEqual(result["result"], "PASS")
            self.assertEqual(result["asset_mode"], "th3ds")
            self.assertFalse(result["product_ready_eligible"])
            self.assertEqual(result["candidate"]["commit"], CANDIDATE_COMMIT)

    def test_empty_directory_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "empty"
            package.mkdir()
            with self.assertRaises(ValidationError):
                validate_sd_tree(package)

    def test_missing_bundle_and_missing_declared_package_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_runtime(Path(temporary))
            with self.assertRaisesRegex(ValidationError, "bundle"):
                self.seal(package)
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_runtime(Path(temporary))
            self.add_th3ds_family(package)
            (package / "resources" / "lang" / "en.th3ds").unlink()
            with self.assertRaisesRegex(ValidationError, "missing"):
                self.seal(package)

    def test_wrong_hash_and_extra_file_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_valid_th3ds(Path(temporary))
            (package / "CorsixTH.lua").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "identity mismatch"):
                validate_sd_tree(package)
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_valid_th3ds(Path(temporary))
            (package / "undeclared.bin").write_bytes(b"extra")
            with self.assertRaisesRegex(ValidationError, "file set mismatch"):
                validate_sd_tree(package)

    def test_renamed_non_3dsx_fails_even_when_hashes_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_runtime(Path(temporary))
            self.add_th3ds_family(package)
            (package / "CorsixTH-3DS.3dsx").write_bytes(b"wrong file renamed as 3dsx" + bytes(32))
            write_boot_contract(
                package,
                asset_mode="th3ds",
                candidate_commit=CANDIDATE_COMMIT,
                candidate_tree=CANDIDATE_TREE,
            )
            write_sd_manifest(package)
            with self.assertRaisesRegex(ValidationError, "not a 3DSX"):
                validate_sd_tree(package)

    def test_corrupt_package_fails_even_after_manifest_is_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_valid_th3ds(Path(temporary))
            target = package / "resources" / "core.th3ds"
            target.write_bytes(target.read_bytes() + b"tamper")
            with self.assertRaisesRegex(ValidationError, "invalid TH3DS package|does not match bundle"):
                write_boot_contract(
                    package,
                    asset_mode="th3ds",
                    candidate_commit=CANDIDATE_COMMIT,
                    candidate_tree=CANDIDATE_TREE,
                )

    def test_forbidden_game_and_user_data_fail_th3ds_contract(self) -> None:
        for relative in ("game/DATA/original.bin", "save/player.sav"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                package = self.make_runtime(Path(temporary))
                self.add_th3ds_family(package)
                target = package / relative
                target.parent.mkdir(parents=True)
                target.write_bytes(b"must stay outside candidate")
                with self.assertRaisesRegex(ValidationError, "forbidden"):
                    self.seal(package)

    def test_symlink_is_not_a_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.make_runtime(root)
            self.add_th3ds_family(package)
            (root / "outside").write_bytes(valid_3dsx())
            (package / "CorsixTH-3DS.3dsx").unlink()
            os.symlink(root / "outside", package / "CorsixTH-3DS.3dsx")
            with self.assertRaisesRegex(ValidationError, "regular file"):
                self.seal(package)

    def test_loose_mode_is_explicitly_diagnostic_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_runtime(Path(temporary))
            from test_playable_assets import add_loose_fixture
            add_loose_fixture(package,Path(temporary)/"loose-fixture")
            result = self.seal(package, "loose")
            self.assertEqual(result["asset_mode"], "loose")
            self.assertTrue(result["product_ready_eligible"])
            with self.assertRaisesRegex(ValidationError, "required mode"):
                validate_sd_tree(package, require_mode="th3ds")

    def test_contract_tampering_breaks_manifest_linkage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self.make_valid_th3ds(Path(temporary))
            contract_path = package / "boot-contract.json"
            contract = json.loads(contract_path.read_text())
            contract["product_ready_eligible"] = False
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "eligibility|identity mismatch"):
                validate_sd_tree(package)


if __name__ == "__main__":
    unittest.main()
