"""Keep a requested recovery save separate from the pre-load safety save."""
from __future__ import annotations

OLD = '''    local recovery = instance.savegame_dir .. "recovery-before-load.sav"
    if instance.world then
      local saved, result = pcall(instance.save, instance, recovery)
      if not saved or result ~= true then return false, "preload recovery save failed: " .. tostring(result) end
    end'''
NEW = '''    -- CORSIXTH_3DS_LOAD_RECOVERY_V1: preserve the file being requested.
    -- FAT names are case-insensitive. Compare the basename conservatively so
    -- directory aliases cannot overwrite the requested recovery or its backup.
    local requested = tostring(filename):gsub("\\\\", "/"):match("([^/]+)$") or ""
    requested = requested:lower()
    local recovery_name = "recovery-before-load.sav"
    if requested == recovery_name or requested == recovery_name .. ".bak" or
       requested == recovery_name .. ".tmp" then
      recovery_name = "recovery-before-load-alt.sav"
    end
    local recovery = instance.savegame_dir .. recovery_name
    instance._3ds_preload_recovery = nil
    if instance.world then
      local saved, result = pcall(instance.save, instance, recovery)
      if not saved or result ~= true then return false, "preload recovery save failed: " .. tostring(result) end
      instance._3ds_preload_recovery = recovery
    end'''

DIAGNOSTIC_OLD = '"; prior progress: recovery-before-load.sav"'
DIAGNOSTIC_NEW = '"; prior progress: "..tostring(TheApp._3ds_preload_recovery or "no prior world")'


def transform(text: str) -> str:
    if text.count(NEW) == 1:
        return text
    if text.count(OLD) != 1:
        raise ValueError('load recovery source anchor mismatch')
    return text.replace(OLD, NEW, 1)


def diagnostic(text: str) -> str:
    if text.count(DIAGNOSTIC_NEW) == 1: return text
    if text.count(DIAGNOSTIC_OLD) != 1:
        raise ValueError('load recovery diagnostic source anchor mismatch')
    return text.replace(DIAGNOSTIC_OLD, DIAGNOSTIC_NEW, 1)


def patch_load_recovery(root, dry_run=False):
    path = root / 'CorsixTH/Lua/persistance.lua'
    old = path.read_text(encoding='utf-8')
    new = diagnostic(old)
    if new == old: return []
    if not dry_run:
        temporary = path.with_name(path.name+'.cth3ds-recovery.tmp')
        with temporary.open('w',encoding='utf-8',newline='\n') as stream: stream.write(new)
        temporary.replace(path)
    return [path.relative_to(root).as_posix()]


def check_load_recovery(root):
    try:
        path = root / 'CorsixTH/Lua/persistance.lua'
        text = path.read_text(encoding='utf-8')
        if diagnostic(text) != text: return ['load recovery diagnostic upgrade missing']
        return []
    except (OSError, ValueError) as exc: return [str(exc)]
