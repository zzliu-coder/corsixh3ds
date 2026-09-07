"""Complete candidate Lua adapter against the pinned UIWatch constructor."""
import json
from pathlib import Path
import unittest
import test_lua_runtime
ROOT=Path(__file__).resolve().parents[1]
class InputPolicyTests(unittest.TestCase):
    def test_full_adapter_with_pinned_watch(self):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        script=(ROOT/'tests/runtime_support/r54_input_policy.lua').read_text()
        test_lua_runtime.LuaRuntimeTests().run_lua('arg={[1]='+json.dumps(str(ROOT),ensure_ascii=False)+'}\n'+script)
if __name__=='__main__':unittest.main()
