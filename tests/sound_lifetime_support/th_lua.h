#pragma once
#include "lua.hpp"
#include <new>
#include <utility>
#include <cstdint>
constexpr int luaT_environindex=lua_upvalueindex(1);
// Exact construction order of upstream luaT_new/luaT_stdnew. Type registration
// below is intentionally narrowed to valid sound userdata used by this suite.
template <typename T,typename... Ts> T* luaT_new(lua_State* L,Ts... args) {
  return new(lua_newuserdata(L,sizeof(T))) T(args...);
}
template <typename T,typename... Args> T* luaT_stdnew(lua_State* L,int mt_idx=luaT_environindex,bool env=false,Args&&... args) {
  T* p=luaT_new<T>(L,std::forward<Args>(args)...);
  lua_pushvalue(L,mt_idx); lua_setmetatable(L,-2);
  if(env) {lua_newtable(L);lua_setfenv(L,-2);} return p;
}
template <typename T> T* luaT_testuserdata(lua_State* L,int index=1) {
  luaL_checktype(L,index,LUA_TUSERDATA); return static_cast<T*>(lua_touserdata(L,index));
}
inline const uint8_t* luaT_checkfile(lua_State* L,int i,size_t* n) {
  return reinterpret_cast<const uint8_t*>(luaL_checklstring(L,i,n));
}
// Exact pinned implementation of luaT_setenvfield.
inline void luaT_setenvfield(lua_State* L,int index,const char* k) {
  lua_getfenv(L,index);lua_pushstring(L,k);lua_pushvalue(L,-3);
  lua_settable(L,-3);lua_pop(L,2);
}
