from __future__ import annotations

import hashlib
import json
import os
import concurrent.futures
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
TESTS = ROOT / "tests"
for entry in (TOOLS, TESTS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from test_th3ds_resource_packer import make_fixture
from th3ds_container import INDEX_ENTRY_SIZE, inspect_package
from th3ds_convert import build_resource_tree
from th3ds_resource import canonical_json
from th3ds_sound import PACK_ENTRY, PACK_HEADER
from th3ds_sprite import ENTRY as SPRITE_ENTRY
from th3ds_sprite import HEADER as SPRITE_HEADER


def container_hash(data: bytes) -> bytes:
    mutable = bytearray(data)
    mutable[0xA8:0xC8] = bytes(32)
    return hashlib.sha256(mutable).digest()


def rebuild_package(
    data: bytearray,
    *,
    catalog: bool = False,
    payload: bool = False,
    resources: bool = False,
) -> None:
    manifest_offset, manifest_size = struct.unpack_from("<QQ", data, 0x20)
    index_offset, count = struct.unpack_from("<QI", data, 0x30)
    metadata_offset, metadata_size = struct.unpack_from("<QQ", data, 0x40)
    data_offset, data_size = struct.unpack_from("<QQ", data, 0x50)
    if resources:
        for row in range(count):
            position = index_offset + row * INDEX_ENTRY_SIZE
            resource_offset = struct.unpack_from("<Q", data, position + 0x20)[0]
            stored_size = struct.unpack_from("<I", data, position + 0x28)[0]
            data[position + 0x40 : position + 0x60] = hashlib.sha256(
                data[resource_offset : resource_offset + stored_size]
            ).digest()
        catalog = True
    manifest = json.loads(data[manifest_offset : manifest_offset + manifest_size])
    if catalog:
        digest = hashlib.sha256(
            data[index_offset : index_offset + count * INDEX_ENTRY_SIZE]
            + data[metadata_offset : metadata_offset + metadata_size]
        ).hexdigest()
        data[0x68:0x88] = bytes.fromhex(digest)
        manifest["catalog"]["catalog_sha256"] = digest
    if payload:
        digest = hashlib.sha256(data[data_offset : data_offset + data_size]).hexdigest()
        data[0x88:0xA8] = bytes.fromhex(digest)
        manifest["catalog"]["payload_sha256"] = digest
    encoded = canonical_json(manifest)
    if len(encoded) != manifest_size:
        raise AssertionError("mutation changed package manifest size")
    data[manifest_offset : manifest_offset + manifest_size] = encoded
    data[0xA8:0xC8] = bytes(32)
    data[0xA8:0xC8] = container_hash(data)


def refresh_bundle(root: Path, package_name: str = "core.th3ds") -> None:
    path = root / "bundle.th3ds.json"
    value = json.loads(path.read_bytes())
    package = (root / package_name).read_bytes()
    row = next(item for item in value["packages"] if item["path"] == package_name)
    row["size"] = len(package)
    row["container_sha256"] = package[0xA8:0xC8].hex() if len(package) >= 0xC8 else "0" * 64
    value["bundle_sha256"] = "0" * 64
    value["bundle_sha256"] = hashlib.sha256(canonical_json(value)).hexdigest()
    path.write_bytes(canonical_json(value))


def stored_payload(package: bytes, resource_id: str) -> bytes:
    index_offset, count = struct.unpack_from("<QI", package, 0x30)
    wanted = bytes.fromhex(resource_id)
    for row in range(count):
        position = index_offset + row * INDEX_ENTRY_SIZE
        if package[position : position + 16] != wanted:
            continue
        payload_offset = struct.unpack_from("<Q", package, position + 0x20)[0]
        payload_size = struct.unpack_from("<I", package, position + 0x28)[0]
        return package[payload_offset : payload_offset + payload_size]
    raise AssertionError(f"resource payload not found: {resource_id}")


class Th3dsRuntimeCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        probe = os.environ.get("CTH3DS_RUNTIME_PROBE")
        if not probe or not Path(probe).is_file():
            raise unittest.SkipTest("CTH3DS_RUNTIME_PROBE is unavailable")
        cls.probe = Path(probe)
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        source, languages, atlas = make_fixture(cls.root)
        (source / "DATA" / "LANG-7.DAT").write_bytes(b"fallback-language-fixture")
        cls.valid = cls.root / "valid"
        build_resource_tree(source, cls.valid, language_dir=languages, glyph_atlases=[atlas])
        cls.fallback = cls.root / "fallback"
        build_resource_tree(
            source,
            cls.fallback,
            language_dir=languages,
            selected_language="Unused",
            glyph_atlases=[atlas],
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def clone(self, name: str) -> Path:
        destination = self.root / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(self.valid, destination)
        return destination

    def run_probe(self, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.probe), "mount", str(root / "bundle.th3ds.json"), *extra],
            text=True,
            capture_output=True,
            check=False,
        )

    def mutate_core(self, name: str, mutation, **rebuild) -> Path:
        root = self.clone(name)
        path = root / "core.th3ds"
        data = bytearray(path.read_bytes())
        mutation(data)
        if rebuild:
            rebuild_package(data, **rebuild)
        path.write_bytes(data)
        refresh_bundle(root)
        return root

    def mutate_package_manifest(self, root: Path, package_name: str, mutation) -> None:
        path = root / package_name
        data = bytearray(path.read_bytes())
        manifest_offset, manifest_size = struct.unpack_from("<QQ", data, 0x20)
        manifest = json.loads(data[manifest_offset : manifest_offset + manifest_size])
        mutation(data, manifest)
        encoded = canonical_json(manifest)
        self.assertEqual(len(encoded), manifest_size)
        data[manifest_offset : manifest_offset + manifest_size] = encoded
        rebuild_package(data)
        path.write_bytes(data)
        refresh_bundle(root, package_name)

    def add_fallback_language(self, root: Path) -> None:
        fallback_bundle = json.loads(
            (self.fallback / "bundle.th3ds.json").read_bytes()
        )
        fallback_row = next(
            row for row in fallback_bundle["packages"]
            if row["path"] == "lang/xx.th3ds"
        )
        (root / "lang" / "xx.th3ds").write_bytes(
            (self.fallback / "lang" / "xx.th3ds").read_bytes()
        )
        bundle_path = root / "bundle.th3ds.json"
        bundle = json.loads(bundle_path.read_bytes())
        bundle["fallback_language"] = "xx"
        bundle["packages"].append(fallback_row)
        bundle["packages"].sort(key=lambda row: row["path"])
        bundle["bundle_sha256"] = "0" * 64
        bundle["bundle_sha256"] = hashlib.sha256(canonical_json(bundle)).hexdigest()
        bundle_path.write_bytes(canonical_json(bundle))

    def assert_runtime_error(self, root: Path, expected: str) -> None:
        result = self.run_probe(root)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stderr)

    def test_deterministic_python_packer_round_trips_through_cpp_runtime(self) -> None:
        result = self.run_probe(self.valid)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("packages=2", result.stdout)
        core = inspect_package((self.valid / "core.th3ds").read_bytes())
        entry = core["entries"][0]
        typed = self.run_probe(
            self.valid, str(entry["resource_id"]), str(entry["kind"])
        )
        self.assertEqual(typed.returncode, 0, typed.stderr)
        self.assertIn(f"stored={entry['stored_size']}", typed.stdout)

    def test_generated_bundle_runs_the_production_session_vertical_slice(self) -> None:
        core = inspect_package((self.valid / "core.th3ds").read_bytes())
        entry = next(item for item in core["entries"] if item["kind"] == "UI_BITMAP")
        cycles = int(os.environ.get("CTH3DS_RUNTIME_CYCLES", "3"))
        workers = min(cycles, int(os.environ.get("CTH3DS_RUNTIME_WORKERS", "1")))
        counts = [cycles // workers + (1 if index < cycles % workers else 0)
                  for index in range(workers)]

        def run(count: int) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    str(self.probe),
                    "session",
                    str(self.valid / "bundle.th3ds.json"),
                    entry["resource_id"],
                    entry["kind"],
                    str(count),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(run, counts))
        for result, count in zip(results, counts):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"session_cycles={count}", result.stdout)
            self.assertIn("ledger=baseline", result.stdout)
            self.assertIn("packages=0 entries=0 leases=0 pins=0", result.stdout)

    def test_audio_and_sprite_runtime_reads_are_bounded_and_nonresident(self) -> None:
        package = (self.valid / "core.th3ds").read_bytes()
        core = inspect_package(package)
        for kind in ("AUDIO_BANK", "SPRITE_SHEET"):
            with self.subTest(kind=kind):
                entry = next(item for item in core["entries"] if item["kind"] == kind)
                payload = stored_payload(package, entry["resource_id"])
                if kind == "AUDIO_BANK":
                    _magic, _version, count, entry_size, _flags, index_offset, data_offset = PACK_HEADER.unpack_from(payload)
                    self.assertEqual(entry_size, PACK_ENTRY.size)
                    cursor = index_offset
                    first = PACK_ENTRY.unpack_from(payload, cursor)
                    block_offset, block_size = int(first[6]), int(first[7])
                    self.assertLessEqual(block_size, 4096 * 2 * 2)
                else:
                    _magic, _version, count, entry_size, _compression, data_offset = SPRITE_HEADER.unpack_from(payload)
                    self.assertEqual(entry_size, SPRITE_ENTRY.size)
                    first = SPRITE_ENTRY.unpack_from(payload, SPRITE_HEADER.size)
                    block_offset, block_size = int(first[0]), int(first[1])
                    self.assertLessEqual(int(first[6]), 65_536)
                index_bytes = int(data_offset)
                self.assertEqual(index_bytes >= int(index_offset if kind == "AUDIO_BANK" else SPRITE_HEADER.size), True)
                reads = ((0, index_bytes), (block_offset, block_size))
                for read_offset, read_bytes in reads:
                    if read_bytes == 0:
                        continue
                    result = subprocess.run(
                        [
                            str(self.probe),
                            "stream",
                            str(self.valid / "bundle.th3ds.json"),
                            entry["resource_id"],
                            kind,
                            str(read_offset),
                            str(read_bytes),
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f"stream_bytes={read_bytes}", result.stdout)
                    self.assertIn("entries=0 payload=0 audio=0 sprite=0", result.stdout)

    def test_legacy_version_reserved_endian_bounds_and_alignment_fail_closed(self) -> None:
        cases = [
            (
                "legacy",
                lambda data: data.__setitem__(slice(0, 8), b"CTH3DPK1"),
                {},
                "E_LEGACY_AUDIT_PACK",
            ),
            (
                "major",
                lambda data: struct.pack_into("<H", data, 0x0A, 2),
                {},
                "E_FORMAT_MAJOR",
            ),
            (
                "reserved",
                lambda data: data.__setitem__(0xF0, 1),
                {},
                "E_HEADER_RESERVED",
            ),
            (
                "endian",
                lambda data: struct.pack_into("<I", data, 0x10, 0x04030201),
                {},
                "E_UNSUPPORTED_FEATURE",
            ),
            (
                "overflow",
                lambda data: struct.pack_into("<Q", data, 0x58, 0xFFFFFFFFFFFFFFFF),
                {},
                "E_FORMAT_BOUNDS",
            ),
            (
                "alignment",
                lambda data: data.__setitem__(
                    struct.unpack_from("<Q", data, 0x30)[0] + 0x1C, 5
                ),
                {"catalog": True},
                "E_FORMAT_BOUNDS",
            ),
            (
                "flags",
                lambda data: struct.pack_into(
                    "<I",
                    data,
                    struct.unpack_from("<Q", data, 0x30)[0] + 0x14,
                    8,
                ),
                {"catalog": True},
                "E_UNSUPPORTED_FEATURE",
            ),
            (
                "metadata-range",
                lambda data: struct.pack_into(
                    "<Q",
                    data,
                    struct.unpack_from("<Q", data, 0x30)[0] + 0x30,
                    0xFFFFFFFFFFFFFFFF,
                ),
                {"catalog": True},
                "E_FORMAT_BOUNDS",
            ),
        ]
        for name, mutation, rebuild, expected in cases:
            with self.subTest(name=name):
                self.assert_runtime_error(
                    self.mutate_core(f"bad-{name}", mutation, **rebuild), expected
                )

    def test_compatible_minor_is_accepted_and_unknown_feature_is_rejected(self) -> None:
        compatible = self.clone("compatible-minor")
        self.mutate_package_manifest(
            compatible,
            "core.th3ds",
            lambda data, manifest: (
                struct.pack_into("<H", data, 0x0C, 1),
                manifest["format"].__setitem__("minor", 1),
            ),
        )
        core_container = (compatible / "core.th3ds").read_bytes()[0xA8:0xC8].hex()
        self.mutate_package_manifest(
            compatible,
            "lang/en.th3ds",
            lambda _data, manifest: manifest["dependencies"][0].__setitem__(
                "container_sha256", core_container
            ),
        )
        result = self.run_probe(compatible)
        self.assertEqual(result.returncode, 0, result.stderr)

        unknown = self.mutate_core(
            "unknown-required-feature",
            lambda data: struct.pack_into("<I", data, 0xEC, 1),
        )
        self.assert_runtime_error(unknown, "E_UNSUPPORTED_FEATURE")

    def test_role_group_and_dependency_semantics_fail_closed(self) -> None:
        wrong_role = self.clone("wrong-role-path")
        bundle_path = wrong_role / "bundle.th3ds.json"
        bundle = json.loads(bundle_path.read_bytes())
        bundle["packages"][0]["role"] = "level"
        bundle["bundle_sha256"] = "0" * 64
        bundle["bundle_sha256"] = hashlib.sha256(canonical_json(bundle)).hexdigest()
        bundle_path.write_bytes(canonical_json(bundle))
        self.assert_runtime_error(wrong_role, "E_PACKAGE_MISMATCH")

        bad_group = self.clone("bad-group-membership")
        self.mutate_package_manifest(
            bad_group,
            "core.th3ds",
            lambda _data, manifest: manifest["groups"][0].__setitem__("id", 9),
        )
        self.assert_runtime_error(bad_group, "E_PACKAGE_MISMATCH")

        self_dependency = self.clone("self-dependency")
        language_path = self_dependency / "lang" / "en.th3ds"
        data = bytearray(language_path.read_bytes())
        index_offset, count = struct.unpack_from("<QI", data, 0x30)
        metadata_offset = struct.unpack_from("<Q", data, 0x40)[0]
        changed = False
        for row in range(count):
            entry = index_offset + row * INDEX_ENTRY_SIZE
            dependency_count = struct.unpack_from("<H", data, entry + 0x3C)[0]
            if dependency_count:
                resource_id = data[entry : entry + 16]
                relative = struct.unpack_from("<Q", data, entry + 0x30)[0]
                data[metadata_offset + relative : metadata_offset + relative + 16] = resource_id
                changed = True
                break
        self.assertTrue(changed)
        rebuild_package(data, catalog=True)
        language_path.write_bytes(data)
        refresh_bundle(self_dependency, "lang/en.th3ds")
        self.assert_runtime_error(self_dependency, "E_PACKAGE_MISMATCH")

    def test_selected_language_full_validation_rolls_back_then_falls_back(self) -> None:
        root = self.clone("selected-fallback")
        self.add_fallback_language(root)
        self.mutate_package_manifest(
            root,
            "lang/en.th3ds",
            lambda _data, manifest: manifest["groups"][0].__setitem__("id", 9),
        )
        result = self.run_probe(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("packages=2", result.stdout)

        (root / "lang" / "xx.th3ds").unlink()
        self.assert_runtime_error(root, "E_PACKAGE_MISSING")

    def test_duplicate_id_and_outer_codec_are_rejected(self) -> None:
        def duplicate(data: bytearray) -> None:
            index_offset, count = struct.unpack_from("<QI", data, 0x30)
            self.assertGreaterEqual(count, 2)
            data[index_offset + INDEX_ENTRY_SIZE : index_offset + INDEX_ENTRY_SIZE + 16] = data[
                index_offset : index_offset + 16
            ]

        self.assert_runtime_error(
            self.mutate_core("duplicate-id", duplicate, catalog=True), "E_ID_DUPLICATE"
        )

        def codec(data: bytearray) -> None:
            index_offset = struct.unpack_from("<Q", data, 0x30)[0]
            struct.pack_into("<H", data, index_offset + 0x12, 1)

        self.assert_runtime_error(
            self.mutate_core("unsupported-codec", codec, catalog=True),
            "E_UNSUPPORTED_CODEC",
        )

    def test_bundle_container_catalog_payload_resource_and_source_hashes_are_enforced(self) -> None:
        bundle_root = self.clone("bundle-hash")
        bundle = json.loads((bundle_root / "bundle.th3ds.json").read_bytes())
        bundle["selected_language"] = "zz"
        (bundle_root / "bundle.th3ds.json").write_bytes(canonical_json(bundle))
        self.assert_runtime_error(bundle_root, "E_HASH_BUNDLE")

        noncanonical = self.clone("bundle-noncanonical")
        bundle_path = noncanonical / "bundle.th3ds.json"
        bundle_path.write_bytes(bundle_path.read_bytes() + b" ")
        self.assert_runtime_error(noncanonical, "E_FORMAT_CANONICAL_JSON")

        container_root = self.clone("container-hash")
        container_path = container_root / "core.th3ds"
        container = bytearray(container_path.read_bytes())
        container[0xA8] ^= 1
        container_path.write_bytes(container)
        refresh_bundle(container_root)
        self.assert_runtime_error(container_root, "E_HASH_CONTAINER")

        def catalog(data: bytearray) -> None:
            index_offset = struct.unpack_from("<Q", data, 0x30)[0]
            data[index_offset + 0x40] ^= 1

        self.assert_runtime_error(
            self.mutate_core("catalog-hash", catalog, catalog=False), "E_HASH_CATALOG"
        )

        def payload(data: bytearray) -> None:
            data_offset = struct.unpack_from("<Q", data, 0x50)[0]
            data[data_offset] ^= 1

        self.assert_runtime_error(
            self.mutate_core("payload-hash", payload, payload=False), "E_HASH_PAYLOAD"
        )
        self.assert_runtime_error(
            self.mutate_core("resource-hash", payload, payload=True),
            "E_HASH_RESOURCE",
        )

        def source(data: bytearray) -> None:
            data[0xC8] ^= 1

        self.assert_runtime_error(
            self.mutate_core("source-hash", source), "E_SOURCE_SET_MIXED"
        )

    def test_truncation_package_identity_and_manifest_budget_fail_closed(self) -> None:
        truncated = self.clone("truncated")
        path = truncated / "core.th3ds"
        path.write_bytes(path.read_bytes()[:-7])
        refresh_bundle(truncated)
        self.assert_runtime_error(truncated, "E_FORMAT_BOUNDS")

        identity = self.clone("package-id")
        bundle_path = identity / "bundle.th3ds.json"
        bundle = json.loads(bundle_path.read_bytes())
        bundle["packages"][0]["package_id"] = "0" * 32
        bundle["bundle_sha256"] = "0" * 64
        bundle["bundle_sha256"] = hashlib.sha256(canonical_json(bundle)).hexdigest()
        bundle_path.write_bytes(canonical_json(bundle))
        self.assert_runtime_error(identity, "E_PACKAGE_MISMATCH")

        def budget(data: bytearray) -> None:
            manifest_offset, manifest_size = struct.unpack_from("<QQ", data, 0x20)
            manifest = json.loads(data[manifest_offset : manifest_offset + manifest_size])
            manifest["budgets"]["audio_bytes"] += 1
            encoded = canonical_json(manifest)
            self.assertEqual(len(encoded), manifest_size)
            data[manifest_offset : manifest_offset + manifest_size] = encoded

        self.assert_runtime_error(
            self.mutate_core("budget", budget, catalog=False), "E_BUDGET_AUDIO"
        )

        symlinked = self.clone("symlinked-package")
        core = symlinked / "core.th3ds"
        real = symlinked / "core-real.th3ds"
        core.rename(real)
        try:
            core.symlink_to(real.name)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        self.assert_runtime_error(symlinked, "E_PACKAGE_MISMATCH")

    def test_repository_tracks_no_runtime_game_packages_or_original_payloads(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.splitlines()
        forbidden_suffixes = (".th3ds", ".th3ds.json")
        self.assertFalse([path for path in tracked if path.endswith(forbidden_suffixes)])
        forbidden_names = ("sound-0.dat", "lang-0.dat", "hospital.exe")
        self.assertFalse(
            [path for path in tracked if Path(path).name.casefold() in forbidden_names]
        )


if __name__ == "__main__":
    unittest.main()
