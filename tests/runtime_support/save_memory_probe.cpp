#include "lua.hpp"
#include "th_lua.h"
#include "persist_lua.h"
#include "cth3ds/allocation_watch.hpp"
#include "cth3ds/memory_pressure.hpp"
#include <array>
#include <cerrno>
#include <climits>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <string>
#include <cstdint>
// INSERT_COMPAT
namespace reference {
// INSERT_REFERENCE
}
namespace candidate {
// INSERT_CANDIDATE
}
struct Heap {bool limited{};std::size_t refused{},largest{};};
static int empty_userdata(lua_State* L) {
  lua_newuserdata(L,0);lua_newtable(L);
  lua_pushinteger(L,0);lua_setfield(L,-2,"__depersist_size");lua_setmetatable(L,-2);
  return 1;
}
static void* allocator(void* ud,void* p,size_t old,size_t n) {
  auto& heap=*static_cast<Heap*>(ud);
  if(!n){std::free(p);return nullptr;}
  // Simulate limited contiguous temporary allocations, not total Old-3DS RAM.
  // Final output strings remain allowed, identical for both writers.
  if(heap.limited && n>old && (p || old!=LUA_TSTRING)) {
    heap.largest=std::max(heap.largest,n);
    if(n>128*1024){++heap.refused;return nullptr;}
  }
  return std::realloc(p,n);
}
static void run(lua_State* L,const char* code) {
  const int error=luaL_dostring(L,code);
  if(error){std::fprintf(stderr,"Lua failure: %s\nScript: %.220s\n",lua_tostring(L,-1),code);std::abort();}
}
int main(int argc,char** argv) {
  assert(argc>=2 && argc<=4);
  Heap heap;auto* L=lua_newstate(allocator,&heap);assert(L);luaL_openlibs(L);
  lua_pushglobaltable(L);lua_pushcclosure(L,reference::luaopen_persist,1);lua_call(L,0,1);lua_setglobal(L,"reference");
  lua_pushglobaltable(L);lua_pushcclosure(L,candidate::luaopen_persist,1);lua_call(L,0,1);lua_setglobal(L,"candidate");
  lua_pushstring(L,argv[1]);lua_setglobal(L,"closure_path");
  run(L,"reference.dofile(closure_path)");
  run(L,"candidate.dofile(closure_path)");
  lua_pushcfunction(L,empty_userdata);lua_setglobal(L,"empty_userdata");
  run(L,R"(
    local shared={answer=42};local empty=empty_userdata()
    local graph={a=shared,b=shared,u=empty,v=empty,fn=make_closure(shared),
      c=math.sin, bool=false,n=17.25,s=string.rep('long-key-',100)}
    graph.self=graph;local tail=graph
    for i=1,96 do tail.child={};tail=tail.child end
    local permanents={[_G]='global',[math.sin]='sin'}
    local inverse={global=_G,sin=math.sin}
    for i=1,8 do
      local original=assert(reference.dump(graph,permanents))
      local updated=assert(candidate.dump(graph,permanents));assert(original==updated)
      for _,reader in ipairs{reference,candidate} do
        local value=assert(reader.load(updated,inverse))
        assert(value.self==value and value.a==value.b and value.u==value.v)
        assert(value.fn()==42 and value.c==math.sin and value.bool==false and value.n==17.25)
        local count=0;while value.child do value=value.child;count=count+1 end
        assert(count==96)
      end
      collectgarbage('collect')
    end
  )");
  run(L,R"(
    root={grid={},empty={},string=string.rep('long-value-',80)}
    root.self=root
    for x=1,128 do
      local row={};root.grid[x]=row
      for y=1,128 do row[y]={humanoids={},objects={}} end
    end
    root.alias=root.grid[42][17]
    root.distinct_long_string=string.rep('long-value-',80)
    expected=assert(reference.dump(root,{}))
    actual=assert(candidate.dump(root,{}))
    assert(actual==expected,'serialized byte format changed')
    for _,reader in ipairs{reference,candidate} do
      local restored=assert(reader.load(actual,{}))
      assert(restored.self==restored and restored.alias==restored.grid[42][17])
      assert(restored.string==root.string and restored.distinct_long_string==root.string)
      restored=nil
    end
    collectgarbage('collect')
  )");
  heap.limited=true;
  run(L,"local ok,err=pcall(reference.dump,root,{});assert(not ok and err:find('memory'));collectgarbage('collect')");
  const auto original_largest=heap.largest;assert(heap.refused>0);
  heap.refused=heap.largest=0;
  run(L,"local result=assert(candidate.dump(root,{}));assert(result==expected)");
  assert(heap.refused==0 && heap.largest<=128*1024);
  std::printf("reference_denied_request=%zu candidate_largest_index_request=%zu byte_format=identical graph_tables=49282\n",original_largest,heap.largest);
  heap.limited=false;
  if(argc>=3) {
    if(luaL_dofile(L,argv[2])) {std::fprintf(stderr,"%s\n",lua_tostring(L,-1));std::abort();}
    run(L,R"(
      local encoded=assert(candidate.dump(index_save_graph,index_save_permanents))
      for _,reader in ipairs{reference,candidate} do
        local restored=assert(reader.load(encoded,index_load_permanents))
        assert(restored.index.entity_map[15][16]==restored.alias)
        assert(restored.objects==restored.alias.objects)
        assert(restored.objects[1]==restored.shared and restored.objects[2]==restored.shared)
        restored.index:compact()
        local alias=restored.legacy_alias
        local object=alias[1]
        restored.legacy:removeEntity(2,2,object)
        restored.legacy:compact()
        restored.legacy:addEntity(2,2,object)
        assert(restored.legacy:getObjectsAtCoordinate(2,2)==alias and alias[1]==object)
      end
    )");
  }
  if(argc==4) {
    lua_pushstring(L,argv[3]);lua_setglobal(L,"health_path");
    run(L,R"(
      local H=dofile(health_path)
      class={is=function(e,k)return e.kind==k end};Staff='staff';Patient='patient'
      local queue={{name='walk',must_happen=true},{name='seek_room'}}
      local source={game_log={'Error in timer handler: ',
        "sdmc:/3ds/corsixth/Lua/entities/humanoids/staff.lua:127: use of undeclared variable 'TH3DS'",
        'Recovering from error in timer handler...'},entities={
        {kind=Staff,ticks=false,timer_time=12,timer_function=math.sin,action_queue=queue,profile={wage=105}},
        {kind=Patient,ticks=true,action_queue={{name='wait'}}},
        {kind='object',ticks=false}},saved_queue=queue}
      local permanent={[math.sin]='sin'};local inverse={sin=math.sin}
      local original_bytes=assert(reference.dump(source,permanent))
      local copy=assert(candidate.load(original_bytes,inverse))
      assert(H.repairR62(copy)==1)
      assert(source.entities[1].ticks==false and source.saved_queue==queue)
      assert(reference.dump(source,permanent)==original_bytes,'original mutated')
      local repaired_state=H.fingerprint(copy)
      local repaired_bytes=assert(candidate.dump(copy,permanent))
      for _,reader in ipairs{reference,candidate}do
        local roundtrip=assert(reader.load(repaired_bytes,inverse))
        assert(H.fingerprint(roundtrip)==repaired_state)
        assert(roundtrip.entities[1].action_queue==roundtrip.saved_queue)
        assert(roundtrip.entities[1].timer_function==math.sin and roundtrip.entities[1].profile.wage==105)
        assert(roundtrip.entities[2].ticks==true and roundtrip.entities[3].ticks==false)
      end
      print('PASS native R63 synthetic recovery roundtrip: original bytes unchanged, actions/timers/aliases retained')
    )");
  }
  lua_close(L);
  // Allocation watch keeps the original allocator contract, including type
  // tags on new objects, failed growth (old allocation stays live), and free.
  cth3ds::AllocationWatch watch;watch.reset(allocator,&heap,0);
  auto* p=cth3ds::AllocationWatch::allocate(&watch,nullptr,LUA_TTABLE,64);
  assert(p && watch.live==64);heap.limited=true;
  assert(!cth3ds::AllocationWatch::allocate(&watch,p,64,256*1024));
  assert(watch.live==64 && watch.failures==1 && watch.failed_request==256*1024);
  assert(!cth3ds::AllocationWatch::allocate(&watch,p,64,0) && watch.live==0);
  cth3ds::MemoryObservationGate gate;
  assert(gate.take(1,false));assert(!gate.take(2,false));assert(gate.take(3,true));
  assert(gate.take(50003,false));assert(gate.skipped==1 && gate.sampled==3);
  cth3ds::MemoryPressure pressure;
  assert(pressure.due(1) && !pressure.due(2));
  assert(!pressure.begin(1,16*1024*1024,true));
  pressure.request(1024);pressure.request(512);assert(pressure.requested==1024);
  assert(!pressure.begin(2,16*1024*1024,false) && pressure.requested==1024);
  assert(pressure.begin(3,16*1024*1024,true));
  assert(!pressure.due(600000) && !pressure.begin(600000,0,true));
  pressure.collecting=false;pressure.request(2048);
  assert(pressure.due(600000) && !pressure.begin(600000,0,true));
  assert(pressure.requested==2048);
  assert(pressure.begin(2000003,16*1024*1024,true));
  pressure.collecting=false;assert(pressure.requested==0);
  assert(!pressure.begin(4000003,8*1024*1024,true));
  assert(pressure.begin(4000003,8*1024*1024-1,true));
  std::puts("PASS native save compatibility, strong aliases, bounded index allocations, allocation watcher");
}
