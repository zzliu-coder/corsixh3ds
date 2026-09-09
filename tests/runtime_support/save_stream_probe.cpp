#include "lua.hpp"
#include "th_lua.h"
#include "persist_lua.h"
#include "cth3ds/atomic_save.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <cerrno>
#include <climits>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <new>
#include <string>

// INSERT_COMPAT
namespace reference {
// INSERT_REFERENCE
}
namespace candidate {
// INSERT_CANDIDATE
}

static bool tracking_cpp;
static std::size_t cpp_largest, cpp_total, cpp_live, cpp_peak;
struct alignas(std::max_align_t) Allocation {std::size_t size; bool measured;};
void* operator new(std::size_t n) {
  auto* allocation=static_cast<Allocation*>(std::malloc(sizeof(Allocation)+n));
  if(!allocation)throw std::bad_alloc();
  allocation->size=n;allocation->measured=tracking_cpp;
  if(tracking_cpp){cpp_largest=std::max(cpp_largest,n);cpp_total+=n;cpp_live+=n;cpp_peak=std::max(cpp_peak,cpp_live);}
  return allocation+1;
}
void operator delete(void* p)noexcept {
  if(!p)return;
  auto* allocation=static_cast<Allocation*>(p)-1;
  if(allocation->measured)cpp_live-=allocation->size;
  std::free(allocation);
}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete[](void* p)noexcept{::operator delete(p);}
void operator delete(void* p,std::size_t)noexcept{::operator delete(p);}
void operator delete[](void* p,std::size_t)noexcept{::operator delete(p);}

struct Heap {
  std::size_t live{},peak{},largest{},denied{},limit{};
  bool measured{},block{};
};
static Heap heap;
static void* allocate(void*,void* old,std::size_t old_size,std::size_t size) {
  if(!old)old_size=0;
  if(!size){heap.live-=old_size;std::free(old);return nullptr;}
  if(heap.measured)heap.largest=std::max(heap.largest,size);
  if(size>old_size && (heap.block || (heap.limit && size>heap.limit))){++heap.denied;return nullptr;}
  auto* next=std::realloc(old,size);
  if(next){heap.live=heap.live-old_size+size;if(heap.measured)heap.peak=std::max(heap.peak,heap.live);}
  return next;
}

static std::array<uint8_t,4*1024*1024> payload;
struct NativeBlock {std::size_t length;unsigned mode;uint32_t checksum;};
static luaL_Stream* active_file;
static int native_write(lua_State* L) {
  auto* block=static_cast<NativeBlock*>(lua_touserdata(L,1));
  auto* writer=static_cast<lua_persist_writer*>(lua_touserdata(L,2));
  lua_getglobal(L,"writers");lua_pushvalue(L,2);lua_pushboolean(L,1);lua_rawset(L,-3);lua_pop(L,1);
  if(block->mode==1)throw std::bad_alloc();
  if(block->mode==2){heap.block=true;lua_pushlstring(L,reinterpret_cast<const char*>(payload.data()),131072);}
  if(block->mode==3)return luaL_error(L,"injected __persist failure 100%%");
  if(block->mode==4){
    assert(active_file&&active_file->f);
    std::fclose(active_file->f);active_file->f=nullptr;active_file->closef=nullptr;
  }
  if(block->mode==5){
    writer->set_error("FIRST ERROR 100% retained");
    writer->set_error("SECOND ERROR must not replace first");
  }
  if(block->mode==6){writer->write_byte_stream(payload.data(),static_cast<std::size_t>(-1));return 0;}
  if(block->mode==7)throw 17;
  writer->write_uint(static_cast<uint64_t>(block->length));
  if(block->mode==8){
    const auto half=block->length/2;
    writer->write_byte_stream(payload.data(),half);
    lua_gc(L,LUA_GCCOLLECT,0);lua_gc(L,LUA_GCCOLLECT,0);
    writer->write_byte_stream(payload.data()+half,block->length-half);
    return 0;
  }
  writer->write_byte_stream(payload.data(),block->length);
  return 0;
}
static int native_read(lua_State* L) {
  auto* block=static_cast<NativeBlock*>(lua_touserdata(L,1));
  auto* reader=static_cast<lua_persist_reader*>(lua_touserdata(L,2));
  uint64_t length=0;assert(reader->read_uint(length));assert(length<=payload.size());
  block->length=static_cast<std::size_t>(length);block->mode=0;block->checksum=0;
  uint8_t scratch[4096];std::size_t offset=0;
  while(offset<length){const auto count=std::min<std::size_t>(sizeof(scratch),length-offset);
    assert(reader->read_byte_stream(scratch,count));
    assert(std::memcmp(scratch,payload.data()+offset,count)==0);
    for(std::size_t i=0;i<count;++i)block->checksum=block->checksum*33+scratch[i];offset+=count;}
  lua_pushboolean(L,0);return 1;
}
static int native_make(lua_State* L) {
  const auto length=static_cast<std::size_t>(luaL_checkinteger(L,1));assert(length<=payload.size());
  const auto mode=static_cast<unsigned>(luaL_optinteger(L,2,0));
  auto* block=static_cast<NativeBlock*>(lua_newuserdata(L,sizeof(NativeBlock)));
  *block={length,mode,0};lua_getglobal(L,"NativeMeta");lua_setmetatable(L,-2);return 1;
}
static int native_length(lua_State* L) {
  auto* block=static_cast<NativeBlock*>(lua_touserdata(L,1));
  lua_pushinteger(L,static_cast<lua_Integer>(block->length));return 1;
}

// A genuine stdio FILE with an injectable backing-device boundary. Product
// fwrite/fflush code is compiled unchanged; only this host device can fail.
struct Device {FILE* backing;std::size_t accepted{},cut{},largest{};unsigned calls{};bool fail_close{};};
static unsigned device_open,device_closed;
static std::size_t device_max_request;
static int device_write(void* context,const char* data,int count) {
  auto* device=static_cast<Device*>(context);++device->calls;
  device->largest=std::max(device->largest,static_cast<std::size_t>(count));
  device_max_request=std::max(device_max_request,static_cast<std::size_t>(count));
  if(device->accepted>=device->cut){errno=ENOSPC;return -1;}
  const auto accepted=std::min<std::size_t>(count,device->cut-device->accepted);
  const auto written=std::fwrite(data,1,accepted,device->backing);device->accepted+=written;
  return static_cast<int>(written);
}
static int device_close(void* context) {
  auto* device=static_cast<Device*>(context);const bool fail=device->fail_close;
  const int result=std::fclose(device->backing);delete device;--device_open;++device_closed;
  if(fail){errno=EIO;return EOF;}return result;
}
#if !defined(__APPLE__)
static ssize_t device_write_linux(void* context,const char* data,size_t count){return device_write(context,data,static_cast<int>(count));}
#endif
static int stream_close(lua_State* L) {
  auto* stream=static_cast<luaL_Stream*>(luaL_checkudata(L,1,LUA_FILEHANDLE));
  const int status=std::fclose(stream->f);stream->f=nullptr;return luaL_fileresult(L,status==0,nullptr);
}
static int open_device(lua_State* L) {
  const auto cut=static_cast<std::size_t>(luaL_checkinteger(L,1));
  const bool fail_close=lua_toboolean(L,2)!=0;
  auto* stream=static_cast<luaL_Stream*>(lua_newuserdata(L,sizeof(luaL_Stream)));
  stream->f=nullptr;stream->closef=nullptr;luaL_setmetatable(L,LUA_FILEHANDLE);
  auto* device=new Device{std::tmpfile(),0,cut,0,0,fail_close};assert(device->backing);
#if defined(__APPLE__)
  stream->f=funopen(device,nullptr,device_write,nullptr,device_close);
#else
  cookie_io_functions_t functions{};functions.write=device_write_linux;functions.close=device_close;
  stream->f=fopencookie(device,"wb",functions);
#endif
  assert(stream->f);stream->closef=stream_close;++device_open;return 1;
}

struct Measurement {std::size_t lua_peak{},lua_largest{},cpp_peak{},cpp_largest{},cpp_total{};};
static Measurement measurement;
static int protected_dump(lua_State* L) {
  // All input graph, file and Lua source allocations precede measurement.
  luaL_checkstack(L,256,"probe stack");
  active_file=static_cast<luaL_Stream*>(luaL_checkudata(L,3,LUA_FILEHANDLE));
  lua_settop(L,3);lua_getglobal(L,"candidate");lua_getfield(L,-1,"dump_file");lua_remove(L,-2);
  for(int i=1;i<=3;++i)lua_pushvalue(L,i);
  const auto start=heap.live;heap.peak=start;heap.largest=0;heap.denied=0;heap.limit=128*1024;
  heap.measured=true;tracking_cpp=true;cpp_largest=cpp_total=cpp_peak=0;assert(cpp_live==0);
  lua_gc(L,LUA_GCSTOP,0);
  const int status=lua_pcall(L,3,LUA_MULTRET,0);
  heap.measured=false;heap.block=false;heap.limit=0;tracking_cpp=false;active_file=nullptr;
  measurement={heap.peak-start,heap.largest,cpp_peak,cpp_largest,cpp_total};
  lua_pushboolean(L,status==LUA_OK);lua_insert(L,4);return lua_gettop(L)-3;
}
static int stats(lua_State* L) {
  lua_pushinteger(L,static_cast<lua_Integer>(measurement.lua_peak));
  lua_pushinteger(L,static_cast<lua_Integer>(measurement.lua_largest));
  lua_pushinteger(L,static_cast<lua_Integer>(measurement.cpp_peak));
  lua_pushinteger(L,static_cast<lua_Integer>(measurement.cpp_largest));
  lua_pushinteger(L,static_cast<lua_Integer>(measurement.cpp_total));
  lua_pushinteger(L,device_open);lua_pushinteger(L,device_closed);
  lua_pushinteger(L,static_cast<lua_Integer>(device_max_request));return 8;
}
static int host_atomic_commit(lua_State* L) {
  const char* temporary=luaL_checkstring(L,1);const char* final_path=luaL_checkstring(L,2);
  bool ok=false;char error[512]{};
  {
    const auto result=cth3ds::atomic_commit_existing(temporary,final_path,true);
    ok=result.ok;std::snprintf(error,sizeof(error),"%s",result.error.c_str());
  }
  lua_pushboolean(L,ok);lua_pushstring(L,error);return 2;
}
static void run(lua_State* L,const char* source) {
  if(luaL_dostring(L,source)){std::fprintf(stderr,"Lua probe failed: %s\n",lua_tostring(L,-1));std::abort();}
}
int main(int argc,char** argv) {
  assert(argc>=3);
  for(std::size_t i=0;i<payload.size();++i)payload[i]=static_cast<uint8_t>((i*31+i/257)%256);
  auto* L=lua_newstate(allocate,nullptr);assert(L);luaL_openlibs(L);
  lua_pushglobaltable(L);lua_pushcclosure(L,reference::luaopen_persist,1);lua_call(L,0,1);lua_setglobal(L,"reference");
  lua_pushglobaltable(L);lua_pushcclosure(L,candidate::luaopen_persist,1);lua_call(L,0,1);lua_setglobal(L,"candidate");
  lua_pushstring(L,argv[1]);lua_setglobal(L,"closure_path");
  lua_pushstring(L,argv[2]);lua_setglobal(L,"directory");
  lua_pushinteger(L,ENOSPC);lua_setglobal(L,"enospc");
  lua_newtable(L);lua_pushinteger(L,sizeof(NativeBlock));lua_setfield(L,-2,"__depersist_size");
  lua_pushcfunction(L,native_write);lua_setfield(L,-2,"__persist");
  lua_pushcfunction(L,native_read);lua_setfield(L,-2,"__depersist");lua_setglobal(L,"NativeMeta");
  for(const auto& binding:std::array<luaL_Reg,6>{{{"native_make",native_make},{"native_length",native_length},
      {"open_device",open_device},{"protected_dump",protected_dump},{"stats",stats},
      {"host_atomic_commit",host_atomic_commit}}}){
    lua_pushcfunction(L,binding.func);lua_setglobal(L,binding.name);
  }
  run(L,R"(
    reference.dofile(closure_path);candidate.dofile(closure_path)
    writers=setmetatable({},{__mode='k'})
    permanent={[_G]='global',[math.sin]='sin',[NativeMeta]='native'}
    inverse={global=_G,sin=math.sin,native=NativeMeta}
    path=directory..'/stream.tmp'
    function collect()collectgarbage('restart');collectgarbage('collect');collectgarbage('collect')end
    function disk(graph)
      local f=assert(io.open(path,'wb'));assert(f:setvbuf('no'))
      local called,ok,bytes,flushes=protected_dump(graph,permanent,f)
      assert(called and ok,tostring(ok)..' '..tostring(bytes));assert(f:close())
      local input=assert(io.open(path,'rb'));local data=assert(input:read('*a'));assert(input:close())
      assert(bytes==#data and flushes==math.ceil(bytes/16384))
      return data
    end
    local shared={answer=42};local graph={a=shared,b=shared,fn=make_closure(shared),c=math.sin,
      n=17.25,s='a\0b'..string.rep('key-',100),bool=false,native=native_make(33000)}
    graph.self=graph;graph.alias=graph.native
    local tail=graph;for i=1,96 do tail.child={};tail=tail.child end
    local original=assert(reference.dump(graph,permanent))
    local updated=assert(candidate.dump(graph,permanent))
    local file=disk(graph);assert(original==updated and updated==file)
    for _,bytes in ipairs{original,updated,file}do
      for _,reader in ipairs{reference,candidate}do
        local restored=assert(reader.load(bytes,inverse))
        assert(restored.self==restored and restored.a==restored.b and restored.fn()==42)
        assert(restored.c==math.sin and restored.bool==false and restored.s==graph.s)
        assert(restored.native==restored.alias and native_length(restored.native)==33000)
        local n=0;while restored.child do restored=restored.child;n=n+1 end;assert(n==96)
      end
    end
    collect();assert(next(writers)==nil)
    print('PASS format cross-read: original/string/file bytes identical, aliases/closures/native userdata')
    local gc_graph={native=native_make(40000,8)}
    assert(disk(gc_graph)==reference.dump(gc_graph,permanent));collect()
    assert(next(writers)==nil)
    for _,size in ipairs{0,1,16383,16384,16385,32768,32769,1048576}do
      local block=native_make(size);local graph={block=block,alias=block,text=string.rep('x\0',size//2)}
      local bytes=disk(graph);assert(bytes==reference.dump(graph,permanent))
      for _,reader in ipairs{reference,candidate}do
        local restored=assert(reader.load(bytes,inverse))
        assert(native_length(restored.block)==size and restored.block==restored.alias and restored.text==graph.text)
      end
      collect()
    end
    print('PASS native block boundaries: 0/1/16383/16384/16385/32768/32769/1048576 and NUL strings')
    -- Device faults exercise unchanged native fwrite and fflush through FILE.
    local cases={{0,'no','write'},{3,'no','write'},{16384+7,'no','write'},
                 {40000,'no','write'},{0,'full','flush'}}
    for _,case in ipairs(cases)do
      local f=open_device(case[1]);assert(f:setvbuf(case[2],65536))
      local called,ok,err=protected_dump({native=native_make(case[2]=='full' and 100 or 45000)},permanent,f)
      assert(not called or not ok)
      assert(tostring(err or ok):find(case[3],1,true),tostring(err or ok))
      assert(tostring(err or ok):find('errno='..enospc,1,true))
      f:close();collect();assert(select(6,stats())==0)
    end
    local f=open_device(1000000,true);assert(f:setvbuf('no'))
    local called,ok=protected_dump({native=native_make(33000)},permanent,f);assert(called and ok)
    assert(not f:close(),'injected fclose failure must remain visible to owner')
    collect();assert(select(6,stats())==0)
    assert(select(8,stats())<=16384,'sink write request exceeded its bound')
    f=assert(io.open(path,'wb'));assert(f:close())
    assert(not pcall(candidate.dump_file,{},permanent,f))
    assert(not pcall(candidate.dump_file,{},permanent,{}))
    f=assert(io.open(path,'rb'));local status,result=pcall(candidate.dump_file,{a=1},permanent,f)
    assert(not status or not result);assert(f:close());collect()
    print('PASS real FILE failures: short/zero/ENOSPC/fflush/close/closed/readonly; caller owns close')
    for _,case in ipairs{{1,'native allocation'},{2,'memory'},{3,'100%'},{4,'closed file'},
                         {5,'FIRST ERROR 100% retained'},{6,'output size overflow'},
                         {7,'native serialization exception'}}do
      local f=assert(io.open(path,'wb'));assert(f:setvbuf('no'))
      local called,ok,err=protected_dump({native=native_make(40000,case[1])},permanent,f)
      assert(not called or not ok)
      assert(tostring(err or ok):find(case[2],1,true),tostring(err or ok))
      if case[1]~=4 then assert(f:close())end
      collect();assert(next(writers)==nil)
      assert(#disk({native=native_make(123)})>123);collect()
    end
    local f=assert(io.open(path,'wb'));assert(f:setvbuf('no'))
    local called,ok=protected_dump({bad=coroutine.create(function()end)},permanent,f)
    assert(not called or not ok);assert(f:close());collect()
    assert(next(writers)==nil)
    print('PASS failed writer GC and retry: C++ bad_alloc/LuaOOM/__persist/thread/first-error/closed-mid-stream')
    local peaks={}
    for _,size in ipairs{262144,1048576,4194304}do
      collect();local input={native=native_make(size)}
      local f=assert(io.open(path,'wb'));assert(f:setvbuf('no'))
      local called,ok,bytes,flushes=protected_dump(input,permanent,f)
      assert(called and ok);local lp,ll,cp,cl,ct=stats()
      assert(lp<65536 and ll<32768 and cp==0 and cl==0 and ct==0)
      assert(bytes>size and flushes==math.ceil(bytes/16384))
      assert(next(writers)~=nil,'stopped GC should retain bounded writer until collection')
      assert(f:close());collect();assert(next(writers)==nil)
      peaks[#peaks+1]=lp
      print(string.format('MEMORY bytes=%d lua_delta_peak=%d lua_max_request=%d cpp_peak=%d cpp_total=%d flushes=%d',
        bytes,lp,ll,cp,ct,flushes))
    end
    assert(math.max(table.unpack(peaks))-math.min(table.unpack(peaks))<4096)
    for i=1,30 do assert(#disk({native=native_make(40000)})>40000);collect();assert(next(writers)==nil)end
    assert(select(6,stats())==0)
    print('PASS output memory bound: 16KiB buffer, no payload C++ allocations, no output Lua string, 30 GC cycles')
  )");
  run(L,"collect();package.loaded.persist=candidate");
  for(int i=3;i<argc;++i){
    if(luaL_dofile(L,argv[i])){std::fprintf(stderr,"Additional Lua probe failed (%s): %s\n",argv[i],lua_tostring(L,-1));std::abort();}
  }
  lua_close(L);assert(heap.live==0);assert(cpp_live==0);assert(device_open==0);
}
