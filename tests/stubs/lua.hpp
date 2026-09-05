#pragma once

#include <cstddef>
#include <cstdint>

struct lua_State {};
using lua_Integer = std::int64_t;
using lua_Number = double;
using lua_CFunction = int (*)(lua_State*);

constexpr int LUA_OK = 0;
constexpr int LUA_TTABLE = 5;
constexpr int LUA_TNUMBER = 3;
constexpr int LUA_TSTRING = 4;
inline int lua_type(lua_State*,int){return 0;}
inline lua_Number lua_tonumber(lua_State*,int){return 0;}
constexpr int LUA_GCCOUNT = 3;
constexpr int LUA_GCCOUNTB = 4;

inline int lua_gettop(lua_State*) { return 0; }
inline int lua_gc(lua_State*, int what, ...) { return what == LUA_GCCOUNT ? 512 : 0; }
inline void lua_settop(lua_State*, int) {}
inline void lua_getglobal(lua_State*, const char*) {}
inline void lua_getfield(lua_State*, int, const char*) {}
inline void lua_setfield(lua_State*, int, const char*) {}
inline int lua_istable(lua_State*, int) { return 1; }
inline int lua_isfunction(lua_State*, int) { return 1; }
inline int lua_isboolean(lua_State*, int) { return 0; }
inline int lua_isnumber(lua_State*, int) { return 0; }
inline int lua_isstring(lua_State*, int) { return 0; }
inline int lua_isnoneornil(lua_State*, int) { return 1; }
inline int lua_toboolean(lua_State*, int) { return 0; }
inline lua_Integer lua_tointeger(lua_State*, int) { return 0; }
inline const char* lua_tostring(lua_State*, int) { return nullptr; }
inline void lua_pop(lua_State*, int) {}
inline void lua_newtable(lua_State*) {}
inline void lua_pushlstring(lua_State*, const char*, std::size_t) {}
inline void lua_pushnumber(lua_State*, lua_Number) {}
inline void lua_pushinteger(lua_State*, lua_Integer) {}
inline void lua_pushboolean(lua_State*, int) {}
inline void lua_pushnil(lua_State*) {}
inline void lua_pushstring(lua_State*, const char*) {}
inline void lua_pushvalue(lua_State*, int) {}
inline void lua_pushcclosure(lua_State*, lua_CFunction, int) {}
#define lua_pushcfunction(L, f) lua_pushcclosure((L), (f), 0)
inline int lua_pcall(lua_State*, int, int, int) { return LUA_OK; }
inline void luaL_checktype(lua_State*, int, int) {}
inline const char* luaL_checkstring(lua_State*, int) { return "stub"; }
inline lua_Integer luaL_checkinteger(lua_State*, int) { return 0; }
inline const char* luaL_optstring(lua_State*, int, const char* fallback) { return fallback; }
inline void lua_pushlightuserdata(lua_State*, void*) {}
inline void* lua_touserdata(lua_State*, int) { return nullptr; }
inline void lua_call(lua_State*, int, int) {}
inline int lua_error(lua_State*) { return 0; }
inline int luaL_error(lua_State*, const char*, ...) { return 0; }
inline int luaL_loadbuffer(lua_State*, const char*, std::size_t, const char*) { return LUA_OK; }
