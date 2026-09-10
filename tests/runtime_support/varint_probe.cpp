#include <cstdint>
#include <cstddef>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include "persist_lua.h"

static bool watched=false;
static std::size_t allocations=0;
void* operator new(std::size_t n) {
  if(watched)++allocations;
  if(auto* p=std::malloc(n?n:1))return p;
  throw std::bad_alloc();
}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p) noexcept {std::free(p);}
void operator delete[](void* p) noexcept {std::free(p);}
// GCC and sized-deallocation Clang must release through the same allocator.
void operator delete(void* p, std::size_t) noexcept {std::free(p);}
void operator delete[](void* p, std::size_t) noexcept {std::free(p);}
struct Sink final:lua_persist_writer {
  uint8_t bytes[10]{};std::size_t size{};
  lua_State* get_stack()override{return nullptr;}
  void write_stack_object(int)override{std::abort();}
  void fast_write_stack_object(int)override{std::abort();}
  void set_error(const char*)override{std::abort();}
  void write_byte_stream(const uint8_t* p,std::size_t n)override{
    if(n>sizeof(bytes))std::abort();size=n;std::memcpy(bytes,p,n);
  }
  template<class T>void emit(T n){
    watched=true;write_uint(n);watched=false;
    std::putchar(static_cast<int>(size));std::fwrite(bytes,1,size,stdout);
  }
  void emit_signed(int n){
    watched=true;write_int(n);watched=false;
    std::putchar(static_cast<int>(size));std::fwrite(bytes,1,size,stdout);
  }
};
int main(){
  Sink sink;
  for(uint64_t value:{uint64_t(0),uint64_t(1),uint64_t(127),uint64_t(128),
      uint64_t(16383),uint64_t(16384),UINT64_MAX}){
    sink.emit(uint8_t(value));sink.emit(uint16_t(value));sink.emit(uint32_t(value));sink.emit(value);
  }
  for(unsigned bit=7;bit<64;bit+=7){
    const uint64_t value=uint64_t(1)<<bit;
    sink.emit(value-1);sink.emit(value);sink.emit(value+1);
  }
  uint64_t value=12345;
  for(int i=0;i<2000;++i){
    value=value*6364136223846793005ULL+1442695040888963407ULL;
    sink.emit(uint8_t(value));sink.emit(uint16_t(value));sink.emit(uint32_t(value));sink.emit(value);
  }
  for(int n:{INT_MIN,-128,-1,0,1,127,128,INT_MAX})sink.emit_signed(n);
  std::fprintf(stderr,"allocations=%zu\n",allocations);
}
