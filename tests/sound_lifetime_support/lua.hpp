#pragma once
// Test-only declarations for the real installed Lua 5.4 C ABI.
#include <cstddef>
#include <cstdint>
extern "C" {
struct lua_State;
using lua_Integer=long long; using lua_Number=double; using lua_KContext=intptr_t;
using lua_CFunction=int(*)(lua_State*);
using lua_KFunction=int(*)(lua_State*,int,lua_KContext);
using lua_Alloc=void*(*)(void*,void*,size_t,size_t);
struct luaL_Reg {const char* name; lua_CFunction func;};
lua_State* lua_newstate(lua_Alloc,void*);
void lua_close(lua_State*);
int lua_gettop(lua_State*);
void lua_settop(lua_State*,int);
void lua_pushvalue(lua_State*,int);
void lua_rotate(lua_State*,int,int);
void lua_copy(lua_State*,int,int);
int lua_type(lua_State*,int);
const char* lua_typename(lua_State*,int);
void* lua_touserdata(lua_State*,int);
const void* lua_topointer(lua_State*,int);
lua_Number lua_tonumberx(lua_State*,int,int*);
lua_Integer lua_tointegerx(lua_State*,int,int*);
const char* lua_tolstring(lua_State*,int,size_t*);
int lua_toboolean(lua_State*,int);
void lua_pushnil(lua_State*);
void lua_pushnumber(lua_State*,lua_Number);
void lua_pushinteger(lua_State*,lua_Integer);
const char* lua_pushlstring(lua_State*,const char*,size_t);
const char* lua_pushstring(lua_State*,const char*);
const char* lua_pushfstring(lua_State*,const char*,...);
void lua_pushcclosure(lua_State*,lua_CFunction,int);
void lua_pushboolean(lua_State*,int);
void lua_pushlightuserdata(lua_State*,void*);
int lua_getglobal(lua_State*,const char*);
void lua_setglobal(lua_State*,const char*);
int lua_getfield(lua_State*,int,const char*);
void lua_setfield(lua_State*,int,const char*);
int lua_rawget(lua_State*,int);
void lua_rawset(lua_State*,int);
void lua_settable(lua_State*,int);
int lua_rawgeti(lua_State*,int,lua_Integer);
void lua_rawseti(lua_State*,int,lua_Integer);
void lua_createtable(lua_State*,int,int);
void* lua_newuserdatauv(lua_State*,size_t,int);
int lua_getmetatable(lua_State*,int);
int lua_setmetatable(lua_State*,int);
int lua_getiuservalue(lua_State*,int,int);
int lua_setiuservalue(lua_State*,int,int);
int lua_pcallk(lua_State*,int,int,int,lua_KContext,lua_KFunction);
int lua_error(lua_State*);
int lua_gc(lua_State*,int,...);
int lua_next(lua_State*,int);
void lua_concat(lua_State*,int);
int lua_isnumber(lua_State*,int);
size_t lua_rawlen(lua_State*,int);
int lua_rawequal(lua_State*,int,int);
int luaL_error(lua_State*,const char*,...);
const char* luaL_checklstring(lua_State*,int,size_t*);
lua_Number luaL_checknumber(lua_State*,int);
lua_Integer luaL_checkinteger(lua_State*,int);
lua_Integer luaL_optinteger(lua_State*,int,lua_Integer);
void luaL_checktype(lua_State*,int,int);
int luaL_newmetatable(lua_State*,const char*);
int luaL_ref(lua_State*,int);
void luaL_unref(lua_State*,int,int);
int luaL_loadstring(lua_State*,const char*);
void luaL_openlibs(lua_State*);
}
#define LUA_VERSION_NUM 504
#define LUA_OK 0
#define LUA_ERRRUN 2
#define LUA_ERRMEM 4
#define LUA_TNIL 0
#define LUA_TNUMBER 3
#define LUA_TTABLE 5
#define LUA_TUSERDATA 7
#define LUA_REGISTRYINDEX (-1001000)
#define LUA_GCCOLLECT 2
#define LUA_GCSTOP 0
#define LUA_GCRESTART 1
#define lua_upvalueindex(i) (LUA_REGISTRYINDEX-(i))
#define lua_pop(L,n) lua_settop((L),-(n)-1)
#define lua_newtable(L) lua_createtable((L),0,0)
#define lua_newuserdata(L,n) lua_newuserdatauv((L),(n),1)
#define lua_getfenv(L,i) lua_getiuservalue((L),(i),1)
#define lua_setfenv(L,i) lua_setiuservalue((L),(i),1)
#define lua_remove(L,i) (lua_rotate((L),(i),-1),lua_pop((L),1))
#define lua_replace(L,i) (lua_copy((L),-1,(i)),lua_pop((L),1))
#define lua_pushliteral(L,s) lua_pushlstring((L),(s),sizeof(s)-1)
#define lua_pushcfunction(L,f) lua_pushcclosure((L),(f),0)
#define lua_tointeger(L,i) lua_tointegerx((L),(i),nullptr)
#define lua_tonumber(L,i) lua_tonumberx((L),(i),nullptr)
#define lua_tostring(L,i) lua_tolstring((L),(i),nullptr)
#define lua_isnil(L,i) (lua_type((L),(i))==LUA_TNIL)
#define luaL_checkstring(L,i) luaL_checklstring((L),(i),nullptr)
#define lua_pcall(L,n,r,e) lua_pcallk((L),(n),(r),(e),0,nullptr)
#define lua_objlen(L,i) lua_rawlen((L),(i))
