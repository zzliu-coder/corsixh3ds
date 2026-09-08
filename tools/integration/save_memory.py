"""Bound the serializer's largest temporary index allocation; format unchanged."""
from sound_lifetime import replace_exact

BUCKET=r'''
  // R59: strong keys are retained exactly as before, split over 256 tables.
  // A large hospital no longer requires a single doubled hash allocation
  // while its previous index allocation is still live. Bucket order is never
  // serialized; the original visitation order and object IDs are unchanged.
  void push_cache_for(int index) {
    std::uint32_t hash=2166136261U;
    if(lua_type(L,index)==LUA_TSTRING) {
      size_t length=0;const auto* s=lua_tolstring(L,index,&length);
      for(size_t i=0;i<length;++i)hash=(hash^static_cast<unsigned char>(s[i]))*16777619U;
    } else {
      auto pointer=reinterpret_cast<std::uintptr_t>(lua_topointer(L,index));
      pointer^=pointer>>16U;pointer^=pointer>>8U;hash=static_cast<std::uint32_t>(pointer>>3U);
    }
    const int slot=2+static_cast<int>(hash&255U);
    lua_getfenv(L,1);
    lua_rawgeti(L,-1,slot);
    if(lua_isnil(L,-1)) {
      lua_pop(L,1);lua_createtable(L,1,8);
      lua_pushvalue(L,2);lua_rawseti(L,-2,1);
      lua_pushvalue(L,-1);lua_rawseti(L,-3,slot);
    }
    lua_remove(L,-2);
  }
'''

def transforms(root):
    path='CorsixTH/Src/persist_lua.cpp'
    text=(root/path).read_text()
    if BUCKET not in text:
        begin=text.index('class lua_persist_basic_writer :')
        end=text.index('class lua_persist_basic_reader',begin)
        writer=text[begin:end]
        writer=replace_exact(writer,'  void fast_write_stack_object(int iIndex) override {',
                             BUCKET+'\n  void fast_write_stack_object(int iIndex) override {','segmented save index')
        # Only the two seen-object lookup sites, not userdata environments.
        writer=replace_exact(writer,'    // Check for no cycle\n    lua_getfenv(L, 1);',
                             '    // Check for no cycle\n    push_cache_for(iIndex);','fast writer index')
        writer=replace_exact(writer,'      lua_getfenv(L, 1);\n      lua_pushvalue(L, iIndex);',
                             '      push_cache_for(iIndex);\n      lua_pushvalue(L, iIndex);','general writer index')
        writer=replace_exact(writer,'    lua_checkstack(L, top + 5);',
                             '    luaL_checkstack(L, 12, "save graph too deep");','checked writer stack')
        writer=replace_exact(writer,'        lua_checkstack(L, 20);',
                             '        luaL_checkstack(L, 20, "save userdata stack exhausted");','checked fast writer stack')
        text=text[:begin]+writer+text[end:]
        text=replace_exact(text,'#include <cstring>','#include <cstring>\n#include <cstdint>','index integer types')
    yield path,text
