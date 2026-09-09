"""Install the owned final Lua sources from the captured overlay.

Only the fixed upstream input or the selected final file is accepted. Historical
intermediate generated trees remain outside the production assembly contract.
"""
from hashlib import sha256
from pathlib import Path

from .common import IntegrationError


PINNED_INPUTS = {
    "CorsixTH/Lua/entities/humanoids/staff.lua":
        "9beb46ca9bd1749f21746989d113df549f50019845287df95214015e44cc0264",
}


def transforms(root: Path, overlay: Path):
    for name, pinned_sha256 in PINNED_INPUTS.items():
        source = overlay / "upstream_overrides" / name
        final = source.read_bytes()
        current = (root / name).read_bytes()
        if current != final and sha256(current).hexdigest() != pinned_sha256:
            raise IntegrationError(f"final source requires fixed upstream or current final bytes: {name}")
        yield name, final.decode("utf-8")
