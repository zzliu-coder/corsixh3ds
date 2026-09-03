from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from check_upstream_lua_api import check_upstream, load_contract, main  # noqa: E402


class UpstreamLuaApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract_path = ROOT / "config" / "corsixth-lua-api-v0.70.1.json"
        self.contract = load_contract(self.contract_path)

    def create_fixture(self, root: Path, omit: str | None = None) -> None:
        for entry in self.contract["contracts"]:
            path = root / entry["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            literals = [value for value in entry["required_literals"] if value != omit]
            path.write_text("\n".join(literals) + "\n", encoding="utf-8")

    def test_complete_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.create_fixture(root)
            self.assertEqual(check_upstream(root, self.contract), [])
            self.assertEqual(main([str(root), "--contract", str(self.contract_path)]), 0)

    def test_missing_method_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            omitted = "function GameUI:setZoom"
            self.create_fixture(root, omit=omitted)
            missing = check_upstream(root, self.contract)
            self.assertEqual([(item.path, item.literal) for item in missing], [
                ("CorsixTH/Lua/game_ui.lua", omitted)
            ])
            self.assertEqual(main([str(root), "--contract", str(self.contract_path), "--json"]), 1)

    def test_contract_is_pinned_to_upstream_manifest(self) -> None:
        pins = json.loads((ROOT / "config" / "upstream-pins.json").read_text(encoding="utf-8"))
        self.assertEqual(self.contract["upstream_tag"], pins["corsixth"]["tag"])
        self.assertEqual(self.contract["upstream_commit"], pins["corsixth"]["commit"])


if __name__ == "__main__":
    unittest.main()
