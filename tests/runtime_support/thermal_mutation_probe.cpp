#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <list>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
#include "cth3ds/thermal_grid.hpp"
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
#define ZoneScoped
#define CORSIXTH_3DS 1
// INSERT_FLAGS
enum class object_type {radiator=44};
enum tile_layer : uint8_t {ground,north_wall,west_wall,ui};
struct map_tile {
  map_tile_flags flags{};
  std::uint16_t aiTemperature[2]{},tile_layers[4]{},iRoomId{},iParcelId{};
  std::list<object_type> objects;
};
struct level_map {
  std::vector<map_tile> cells{64};
  cth3ds::ThermalGrid thermal_cache;
  int current{};
  unsigned invalidations{};
  void invalidate_thermal_structure() {++invalidations;thermal_cache.invalidate_structure();}
  int get_width() const{return 8;} int get_height() const{return 8;}
  map_tile* get_tile(int x,int y){return x>=0&&x<8&&y>=0&&y<8?get_tile_unchecked(x,y):nullptr;}
  map_tile* get_tile_unchecked(int x,int y){return &cells[static_cast<std::size_t>(y*8+x)];}
  map_tile* get_original_tile_unchecked(int,int){static map_tile original;return &original;}
  // Secondary updates are explicit seams: each primary Lua mutation must
  // notify independently, so one owner's omission cannot be masked by another.
  void update_pathfinding(){} void update_shadows(){}
};
template<class T>T* luaT_testuserdata(lua_State* L){return static_cast<T*>(lua_touserdata(L,1));}
// INSERT_MUTATORS
static level_map map;
static int check(lua_State* L) {
  const bool changed=lua_toboolean(L,1)!=0;
  auto reference=map.cells;
  cth3ds::ThermalGrid full;
  const auto scans=cth3ds::cpu_work.thermal_scans;
  map.thermal_cache.update(map.cells.data(),8,8,map.current,map.current^1,10000,58000,object_type::radiator,false);
  assert(cth3ds::cpu_work.thermal_scans==scans+(changed?1:0));
  full.update(reference.data(),8,8,map.current,map.current^1,10000,58000,object_type::radiator);
  for(std::size_t i=0;i<reference.size();++i)
    for(int slot=0;slot<2;++slot)assert(map.cells[i].aiTemperature[slot]==reference[i].aiTemperature[slot]);
  map.current^=1;return 0;
}
int main() {
  for(std::size_t i=0;i<map.cells.size();++i) {
    auto& c=map.cells[i];c.flags={};c.flags.hospital=true;
    c.aiTemperature[0]=static_cast<uint16_t>(i*711);c.aiTemperature[1]=17;
  }
  auto* L=luaL_newstate();assert(L);luaL_openlibs(L);
  lua_pushlightuserdata(L,&map);lua_setglobal(L,"map");
  // INSERT_REGISTRATION
  lua_pushcfunction(L,check);lua_setglobal(L,"check");
  const char* script=R"(
check(true)
for i=1,30 do check(false) end
set(map,3,3,{thob=44});check(true);check(false)
remove(map,3,3,44);check(true);check(false)
set(map,4,4,{thob=44});check(true)
erase(map,4,4);check(true)
set(map,4,4,{hospital=false,room=true,travelEast=true});check(true)
mark(map,1,1,3,3,7,1);check(true);check(false)
unmark(map,1,1,3,3);check(true)
for i=1,30 do check(false) end
)";
  const auto status=luaL_dostring(L,script);
  if(status)std::fprintf(stderr,"%s\n",lua_tostring(L,-1));
  assert(status==0 && map.invalidations==7);
  lua_close(L);
  std::puts("PASS real Lua map mutators invalidate thermal structure; stable updates reuse; all values match full scan");
}
