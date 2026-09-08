#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>

namespace cth3ds {
// Scheduling only. All heap queries and collection remain on the main thread.
struct MemoryPressure {
  std::uint64_t requested{}, last_check{}, last_collection{}, collections{};
  bool checked{}, collecting{};
  void request(std::size_t bytes) noexcept {requested=std::max<std::uint64_t>(requested,bytes);}
  bool due(std::uint64_t now) noexcept {
    if(collecting || (checked && now>=last_check && now-last_check<500000U))return false;
    checked=true;last_check=now;return true;
  }
  bool begin(std::uint64_t now,std::uint64_t available,bool gc_running) noexcept {
    if(collecting || !gc_running || (!requested && available>=8U*1024U*1024U))return false;
    if(collections && now>=last_collection && now-last_collection<2000000U)return false;
    collecting=true;requested=0;last_collection=now;++collections;return true;
  }
};
}
