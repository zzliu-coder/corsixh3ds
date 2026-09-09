"""Bind the reception action's permanent identity for state recovery."""
from sound_lifetime import replace_exact

def reception_binding(text):
    marker='CORSIXTH_3DS_RECEPTION_IDENTITY_R65'
    if marker in text:
        return text
    anchor='local action_staff_reception_idle_phase = permanent"action_staff_reception_idle_phase"'
    hook='''-- CORSIXTH_3DS_RECEPTION_IDENTITY_R65: bind the actual permanent closure
-- before any saved action is inspected. App/benchmark load order is irrelevant.
local native_ok, reception_native = pcall(require, "th3ds")
local IS_3DS = native_ok and reception_native.is_platform()
if IS_3DS then
  require("3ds.state_health").bindReceptionInterrupt(action_staff_reception_interrupt)
end

'''
    return replace_exact(text,anchor,hook+anchor,'bind formal reception interrupt identity')

def transforms(root):
    # Older 41-file test inventories omit this unmodified upstream module.
    # Full product assemblies contain it; the dedicated R65 test requires it.
    name='CorsixTH/Lua/humanoid_actions/staff_reception.lua'
    if (root/name).is_file():
        yield name,reception_binding((root/name).read_text())
