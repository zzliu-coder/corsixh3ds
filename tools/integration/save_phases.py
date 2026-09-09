"""Separate the real save stages without changing permanence or file format."""
from sound_lifetime import replace_exact

def transforms(root):
    path = 'CorsixTH/Lua/persistance.lua'
    text = (root/path).read_text()
    if 'CORSIXTH_3DS_SAVE_PHASES_R61' not in text:
        text = replace_exact(text,
            '    return persist.dump(state, MakePermanentObjectsTable(false))',
            '''    -- CORSIXTH_3DS_SAVE_PHASES_R61
    if TH3DS then TH3DS.observe_memory("save","permanent-before","permanent","Operation") end
    local permanent = MakePermanentObjectsTable(false)
    if TH3DS then TH3DS.observe_memory("save","permanent-after","permanent","Operation") end
    if TH3DS then TH3DS.observe_memory("save","writer-before","persist","Operation") end
    local result, err, obj = persist.dump(state, permanent)
    if TH3DS then TH3DS.observe_memory("save","writer-after","persist","Operation") end
    return result, err, obj''', 'save permanent and writer phases')
        # Keep the upstream helper's TWO complete collections and stopped-GC
        # weak-key traversal. Time it as one region, without wrapping it again.
        text = replace_exact(text, '    pause_gc_and_use_weak_keys(function(p)',
            '''    if TH3DS then TH3DS.observe_memory("save","weak-gc-before","permanent","Operation") end
    pause_gc_and_use_weak_keys(function(p)
      if TH3DS then TH3DS.observe_memory("save","weak-gc-after","permanent","Operation") end''',
            'save weak reference collection phase')
        for stage, line in (
            ('write', '  local wrote,result,write_error=pcall(f.write,f,data)'),
            ('close', '  local closed,close_result,close_error=pcall(f.close,f)')):
            text = replace_exact(text, line,
                f'  if TH3DS then TH3DS.observe_memory("save","{stage}-before","state-file","Operation") end\n'
                + line
                + f'\n  if TH3DS then TH3DS.observe_memory("save","{stage}-after","state-file","Operation") end',
                'save '+stage+' timing')
    if 'CORSIXTH_3DS_PERSIST_OBSERVER_R68' not in text:
        anchor='local IS_3DS = native_ok and TH3DS.is_platform()\n'
        text=replace_exact(text,anchor,anchor+'''-- CORSIXTH_3DS_PERSIST_OBSERVER_R68: declared before permanent-table helpers.
local function observePersistence(site,phase,resource)
  if not TH3DS or not TH3DS.observe_memory then return end
  local owner=TheApp and TheApp._3ds and TheApp._3ds.operations
  local operation=owner and owner.current
  if operation then return owner:diagnostic(operation,phase,TH3DS.observe_memory,site,phase,resource,"Operation") end
  return pcall(TH3DS.observe_memory,site,phase,resource,"Operation")
end
''','shared persistence observation owner')
        for phase in ('weak-gc-before','weak-gc-after'):
            text=replace_exact(text,
                f'if TH3DS then TH3DS.observe_memory("save","{phase}","permanent","Operation") end',
                f'observePersistence("save","{phase}","permanent")','weak GC observation '+phase)
        for phase in ('parse-before','parse-after','afterLoad-before','afterLoad-after'):
            text=replace_exact(text,
                f'if TH3DS then TH3DS.observe_memory("reload", "{phase}", "persist", "Operation") end',
                f'observePersistence("reload","{phase}","persist")','load observation '+phase)
    yield path, text
