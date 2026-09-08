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
    yield path, text
