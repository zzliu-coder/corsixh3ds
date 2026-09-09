#pragma once
#include <cstdint>
#include <limits>

namespace cth3ds {
// Fixed storage; all durations are actual sampled ticks, never extrapolated.
struct GpuSubmitSample {
  enum Counter { Calls, Culled, Errors, Pieces, Whole, Multi, Partial, Hits,
    Uploads, Switches, ObjectCheckpoint, CommandCheckpoint, EvictCheckpoint,
    Sampled, Rejected, FloorCalls, Floors, Frames, Count };
  std::uint64_t count[Count]{}, ticks[4][4]{};
  std::uint64_t floor_ticks{}, floor_start{}, bridge_start{}, begin_us{}, end_us{}, samples[4]{};
  std::uint32_t ordinal{}, phase{};
  int last_page{-1};
  bool enabled{}, eligible{}, overflow{}, rollback{}, bridge{}, selected{}, floor{};
  void add(std::uint64_t& dst,std::uint64_t n=1) noexcept {
    if(n>std::numeric_limits<std::uint64_t>::max()-dst){overflow=true;dst=UINT64_MAX;}
    else dst+=n;
  }
  void inc(Counter c) noexcept {if(enabled)add(count[c]);}
  bool choose() noexcept {return enabled && ((ordinal++ & 63U)==phase);}
  void frame() noexcept {if(enabled){inc(Frames);phase=(phase+1)&63U;ordinal=0;last_page=-1;}}
  void begin(std::uint64_t us) noexcept {*this={};begin_us=us;enabled=true;eligible=true;}
  void end(std::uint64_t us,bool ok) noexcept {if(!enabled)return;end_us=us;enabled=false;eligible=ok&&us>=begin_us&&!overflow&&!rollback&&!floor&&!bridge&&!count[Errors];selected=false;}
  std::uint64_t delta(std::uint64_t a,std::uint64_t b) noexcept {
    if(b<a){rollback=true;return 0;}return b-a;
  }
};
static_assert(sizeof(GpuSubmitSample)<=512,"GPU sample must stay bounded");
}
