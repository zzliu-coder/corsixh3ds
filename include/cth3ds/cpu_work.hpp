#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

namespace cth3ds {
enum class CpuWork : std::uint8_t { Temperature, Pathfind, InputState, InputAction, World, UI, Count };
inline constexpr std::array<const char*,6> kCpuWorkNames{{"temperature","pathfind","input_state","input_action","world","ui"}};
struct CpuCounter { std::uint64_t calls{}, total_us{}, max_us{}, units{}; };
struct CpuWorkCounters {
  std::array<CpuCounter,6> rows{};
  std::uint64_t (*clock_us)() noexcept = nullptr;
  bool enabled{true};
};
inline CpuWorkCounters cpu_work;
// Main-thread inclusive timers. Overlapping categories must not be summed as
// CPU load. No timer/SD write per tile, path node, pixel or input producer.
class CpuWorkScope {
 public:
  explicit CpuWorkScope(CpuWork kind, std::uint64_t units=1) noexcept
      : row_(cpu_work.enabled && cpu_work.clock_us ? &cpu_work.rows[static_cast<std::size_t>(kind)] : nullptr),
        began_(row_ ? cpu_work.clock_us() : 0), units_(units) {}
  ~CpuWorkScope() { if(row_) {
    const auto now=cpu_work.clock_us(); const auto elapsed=now>=began_?now-began_:0;
    ++row_->calls;row_->total_us+=elapsed;row_->units+=units_;
    if(elapsed>row_->max_us)row_->max_us=elapsed;
  }}
  CpuWorkScope(const CpuWorkScope&)=delete;
  CpuWorkScope& operator=(const CpuWorkScope&)=delete;
 private:
  CpuCounter* row_; std::uint64_t began_,units_;
};
// Valid only inside one synchronous input drain. Every Lua action invalidates
// it; native-only view changes preserve it. A new drain always starts dirty.
class InputRefreshGate {
 public:
  template<class Query> void refresh(Query&& query) { if(dirty_) {query();dirty_=false;} }
  void invalidate() noexcept {dirty_=true;}
 private: bool dirty_{true};
};
} // namespace cth3ds
