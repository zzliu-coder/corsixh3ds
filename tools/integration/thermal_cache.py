"""Invalidate cached thermal structure at the pinned map's real mutation owners.

Temperature values are still snapshotted/published on every original update.
The ordinary kernel API defaults to a full scan; only this audited map opts in.
"""
from sound_lifetime import replace_exact

MAP_MUTATORS = (
    'bool level_map::set_size(int iWidth, int iHeight) {',
    'bool level_map::load_blank() {',
    '                                  void* pCallbackToken) {',
    'void level_map::update_pathfinding() {',
    'void level_map::depersist(lua_persist_reader* pReader) {',
)
LUA_MUTATORS = ('l_map_erase_thobs','l_map_remove_cell_thob','l_map_setcellflags',
                'l_map_mark_room','l_map_unmark_room')

def transforms(root):
    path='CorsixTH/Src/th_map.h'
    text=(root/path).read_text()
    old='  void update_temperatures(uint16_t iAirTemperature,'
    new='''#ifdef CORSIXTH_3DS
  void invalidate_thermal_structure() noexcept {thermal_cache.invalidate_structure();}
#endif
''' + old
    if new not in text:text=replace_exact(text,old,new,'thermal invalidation interface')
    yield path,text

    path='CorsixTH/Src/th_map.cpp'
    text=(root/path).read_text()
    for signature in MAP_MUTATORS:
        new=signature+'\n#ifdef CORSIXTH_3DS\n  invalidate_thermal_structure();\n#endif'
        if new not in text:text=replace_exact(text,signature,new,'thermal map mutation')
    yield path,text

    path='CorsixTH/Src/th_lua_map.cpp'
    text=(root/path).read_text()
    owner='  level_map* pMap = luaT_testuserdata<level_map>(L);'
    hook=owner+'\n#ifdef CORSIXTH_3DS\n  pMap->invalidate_thermal_structure();\n#endif'
    for name in LUA_MUTATORS:
        begin=text.index('int '+name+'(lua_State* L) {')
        end=text.index('\n}',begin)+2
        method=text[begin:end]
        if hook not in method:
            text=text[:begin]+replace_exact(method,owner,hook,'thermal Lua mutation '+name)+text[end:]
    yield path,text
