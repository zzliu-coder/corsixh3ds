#include "cth3ds/log_format.hpp"
#include "cth3ds/bounded_log.hpp"
#include <cassert>
#include <climits>
#include <cstdio>
#include <random>
#include <string>
#include <limits>

static std::size_t checked{},fast_count{};
static void compare(const char* pattern,...) {
  char actual[2048], expected[2048];
  std::va_list args,copy;va_start(args,pattern);va_copy(copy,args);
  std::size_t count=0;
  const bool fast=cth3ds::log_detail::format(actual,2046,count,pattern,copy);
  va_end(copy);
  const int total=std::vsnprintf(expected,2047,pattern,args);va_end(args);
  assert(total>=0);
  if(fast) {
    ++fast_count;
    assert(count==std::min<std::size_t>(2047,static_cast<std::size_t>(total)));
    assert(!std::memcmp(actual,expected,std::min<std::size_t>(2046,count)));
  }
  ++checked;
}
int main() {
  // Actual vararg widths follow each conversion, rather than a host-sized cast.
  static_assert(sizeof(unsigned long long)==8);
#ifdef __3DS__
  static_assert(sizeof(unsigned)==4 && sizeof(unsigned long)==4 && sizeof(std::size_t)==4);
#endif
  compare("%d %d %d %u %lu %llu",INT_MIN,INT_MAX,0,UINT_MAX,ULONG_MAX,ULLONG_MAX);
  for(const auto* f:{"%zu","%08u","%.0f","%lld","%.*d","%x","%p"})
    assert(!cth3ds::log_detail::supported(f));
  assert(!cth3ds::log_detail::supported("%"));
  assert(!cth3ds::log_detail::supported("%l"));
  assert(!cth3ds::log_detail::supported("%ll"));
  compare("a%%b %s end","");compare("%.*s",0,"abc");
  compare("%.*s",2,"中文");compare("%.*s",99,"embedded\0ignored");
  compare("%.*s suffix",-1,"negative");compare("%s",static_cast<const char*>(nullptr));
  for(const std::size_t n:{0U,1U,2044U,2045U,2046U,2047U,2048U,4096U}) {
    const std::string value(n,'x');compare("%s",value.c_str());
    compare("%s: %llu",value.c_str(),ULLONG_MAX);compare("%.*s",static_cast<int>(n),value.c_str());
    compare("%s%d",value.c_str(),INT_MIN);
    compare("%s%s",value.c_str(),"中文");
  }
  std::mt19937_64 random(71);
  for(unsigned i=0;i<10000;++i) {
    const auto u=random();
    compare("u=%llu long=%lu short=%u signed=%d %% text=%.*s",static_cast<unsigned long long>(u),
      static_cast<unsigned long>(u),static_cast<unsigned>(u),static_cast<int>(u),
      static_cast<int>(i%8),"abcdefgh");
  }
  // INSERT_LITERAL_CASES
  std::printf("PASS differential cases=%lu fast=%lu long_bytes=%lu size_t_bytes=%lu Costs=%lu BoundedLog=%lu\n",
    static_cast<unsigned long>(checked),static_cast<unsigned long>(fast_count),
    static_cast<unsigned long>(sizeof(unsigned long)),static_cast<unsigned long>(sizeof(std::size_t)),
    static_cast<unsigned long>(sizeof(cth3ds::BoundedLog::Costs)),static_cast<unsigned long>(sizeof(cth3ds::BoundedLog)));
}
