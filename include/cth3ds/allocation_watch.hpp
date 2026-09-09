#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>

namespace cth3ds {
// Delegate to Lua's existing allocator. No allocation, logging, clock or Lua
// calls inside the hook, including its failure and emergency-GC paths.
struct AllocationWatch {
  using Allocator=void*(*)(void*,void*,std::size_t,std::size_t);
  Allocator allocator{};
  void* context{};
  std::uint64_t live{},peak{},requests{},failures{},failed_request{},largest_request{};
  void reset(Allocator fn,void* ud,std::uint64_t initial) noexcept {
    allocator=fn;context=ud;live=peak=initial;
    requests=failures=failed_request=largest_request=0;
  }
  static void* allocate(void* ud,void* pointer,std::size_t old,std::size_t size) {
    auto& s=*static_cast<AllocationWatch*>(ud);
    const auto previous=pointer?old:0; // osize is a type tag for new objects.
    ++s.requests;
    s.largest_request=std::max<std::uint64_t>(s.largest_request,size);
    auto* result=s.allocator(s.context,pointer,old,size);
    if(size && !result) {++s.failures;s.failed_request=size;return nullptr;}
    s.live=s.live>=previous?s.live-previous:0;
    s.live+=size;s.peak=std::max(s.peak,s.live);
    return result;
  }
};

struct MemoryObservationGate {
  // R65: detailed heap snapshots may walk allocator metadata. Keep ordinary
  // sprite/texture/audio observations at most four times per second. Operation
  // boundaries, large requests and failures still force an immediate sample;
  // admission checks and AllocationWatch are independent of this gate.
  static constexpr std::uint64_t interval_us=250000;
  std::uint64_t last{},sampled{},skipped{},forced{};
  bool take(std::uint64_t now,bool force) noexcept {
    if(!force && sampled && now>=last && now-last<interval_us) {++skipped;return false;}
    if(force)++forced;
    last=now;++sampled;return true;
  }
};
}
