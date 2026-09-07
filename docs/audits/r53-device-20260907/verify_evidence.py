"""Verify this fixed review's files and recompute the two benchmark analyses.
This command makes no network/device calls and does not establish product acceptance.
"""
import hashlib
import json
import subprocess
from pathlib import Path
from analyze_benchmark import analyze

root = Path(__file__).resolve().parent
repo = root.parents[2]
manifest = json.loads((root / "hashes.json").read_text())
checked = []
for item in manifest["files"]:
    path = root / item["file"]
    assert path.is_file() and path.resolve().parent == root, item["file"]
    data = path.read_bytes()
    assert len(data) == item["bytes"], item["file"]
    assert hashlib.sha256(data).hexdigest() == item["sha256"], item["file"]
    checked.append(item["file"])
actual = sorted(p.name for p in root.iterdir() if p.is_file() and p.name != "hashes.json")
assert actual == sorted(checked), "Payload inventory differs from hashes.json"
identity = json.loads((root / "identity.json").read_text())
for item in identity["logs"]:
    data = (root / item["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == item["public_sha256"]
    assert len(data.splitlines()) == item["lines"]
for name in ("first", "second"):
    regenerated = analyze((root / (name + "-boot.log")).read_text())
    saved = json.loads((root / (name + "-benchmark.json")).read_text())
    assert regenerated == saved, name
    print(name + ": benchmark analysis matches retained JSON (" + saved["benchmark_protocol"] + ")")
for path, expected in identity["source_files_sha256"].items():
    # Verify against the measured historical commit, even after a future product fix.
    data = subprocess.check_output(
        ["git", "show", identity["product_commit"] + ":" + path], cwd=repo
    )
    assert hashlib.sha256(data).hexdigest() == expected, path
print("PASS: %d evidence payload hashes and fixed product source hashes match." % len(checked))
print("Product status remains GPU FAIL / 30FPS FAIL / emergency HUD defect reproduced.")
print("No independent capture authentication, new build, device launch or save/reload acceptance is implied.")
