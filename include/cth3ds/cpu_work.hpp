#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

namespace cth3ds {
enum class CpuWork : std::uint8_t { Temperature, Pathfind, InputState, InputAction, World, UI, ThermalStructure, ThermalSnapshot, ThermalArithmetic, GpuUpload, GpuPrepare, WorldCalendar, WorldAnimations, WorldHospitals, WorldEntities, WorldMap, WorldUI, WorldDispatch, MemoryObserve, SampleStaff, SamplePatient, SampleObject, SampleOther, Count };
inline constexpr std::array<const char*,static_cast<std::size_t>(CpuWork::Count)> kCpuWorkNames{{"temperature","pathfind","input_state","input_action","world","ui","thermal_structure","thermal_snapshot","thermal_arithmetic","gpu_upload","gpu_prepare","world_calendar","world_animations","world_hospitals","world_entities","world_map","world_ui","world_dispatch","memory_observe","sample_entity_staff","sample_entity_patient","sample_entity_object","sample_entity_other"}};
struct CpuCounter { std::uint64_t calls{}, total_us{}, max_us{}, units{}; };
struct CpuWorkCounters {
  std::array<CpuCounter,static_cast<std::size_t>(CpuWork::Count)> rows{};
  std::uint64_t (*clock_us)() noexcept = nullptr;
  bool enabled{true};
  // R54 diagnostic split is opt-in: the normal scan still copies its snapshot
  // in the same pass. Subphase totals are included in Temperature and World.
  bool thermal_phase_profile{false};
  bool thermal_uniform_fast{true};
  bool thermal_structure_fast{true};
  std::uint64_t thermal_updates{},thermal_scans{},thermal_rebuilds{},thermal_bytes{};
};
inline CpuWorkCounters cpu_work;
// Main-thread inclusive timers. Overlapping categories must not be summed as
// CPU load. No timer/SD write per tile, path node, pixel or input producer.
class CpuWorkScope {
 public:
  explicit CpuWorkScope(CpuWork kind, std::uint64_t units=1, bool selected=true) noexcept
      : row_(selected && cpu_work.enabled && cpu_work.clock_us ? &cpu_work.rows[static_cast<std::size_t>(kind)] : nullptr),
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
