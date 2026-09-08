#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

namespace cth3ds {
enum class CpuWork : std::uint8_t { Temperature, Pathfind, InputState, InputAction, World, UI, ThermalStructure, ThermalSnapshot, ThermalArithmetic, GpuUpload, GpuPrepare, WorldCalendar, WorldAnimations, WorldHospitals, WorldEntities, WorldMap, WorldUI, WorldDispatch, MemoryObserve, SampleStaff, SamplePatient, SampleObject, SampleOther, StaffBase, StaffRest, StaffAttributes, StaffLitter, StaffSpeed, Count };
inline constexpr std::array<const char*,static_cast<std::size_t>(CpuWork::Count)> kCpuWorkNames{{"temperature","pathfind","input_state","input_action","world","ui","thermal_structure","thermal_snapshot","thermal_arithmetic","gpu_upload","gpu_prepare","world_calendar","world_animations","world_hospitals","world_entities","world_map","world_ui","world_dispatch","memory_observe","sample_entity_staff","sample_entity_patient","sample_entity_object","sample_entity_other","sample_staff_base","sample_staff_rest","sample_staff_attributes","sample_staff_litter","sample_staff_speed"}};
struct CpuCounter { std::uint64_t calls{}, total_us{}, max_us{}, units{}; };
struct CpuWorkCounters {
  std::array<CpuCounter,static_cast<std::size_t>(CpuWork::Count)> rows{};
  std::array<CpuCounter,static_cast<std::size_t>(CpuWork::Count)> sample_rows{};
  bool sample_active{};
  std::uint64_t sample_begin{};
  std::uint64_t (*clock_us)() noexcept = nullptr;
  bool enabled{true};
  // Diagnostic split is opt-in; normal mode combines required structure and
  // snapshot passes. Subphase totals are included in Temperature and World.
  bool thermal_phase_profile{false};
  bool thermal_uniform_fast{true};
  bool thermal_structure_fast{true};
  std::uint64_t thermal_updates{},thermal_scans{},thermal_rebuilds{},thermal_bytes{};
  void record(std::size_t index,std::uint64_t began,std::uint64_t ended,std::uint64_t units=1) noexcept {
    const auto elapsed=ended>=began?ended-began:0;
    const auto add=[&](CpuCounter& row){++row.calls;row.total_us+=elapsed;row.units+=units;
      if(elapsed>row.max_us)row.max_us=elapsed;};
    add(rows[index]);
    // Benchmark counters are independent of ten/sixty-second log resets and
    // accept only scopes wholly contained in the explicit sample window.
    if(sample_active&&began>=sample_begin&&ended>=began)add(sample_rows[index]);
  }
};
inline CpuWorkCounters cpu_work;
// Main-thread inclusive timers. Overlapping categories must not be summed as
// CPU load. No timer/SD write per tile, path node, pixel or input producer.
class CpuWorkScope {
 public:
  explicit CpuWorkScope(CpuWork kind, std::uint64_t units=1, bool selected=true) noexcept
      : selected_(selected && cpu_work.enabled && cpu_work.clock_us), kind_(kind),
        began_(selected_ ? cpu_work.clock_us() : 0), units_(units) {}
  ~CpuWorkScope() { if(selected_) {
    const auto now=cpu_work.clock_us();
    cpu_work.record(static_cast<std::size_t>(kind_),began_,now,units_);
  }}
  CpuWorkScope(const CpuWorkScope&)=delete;
  CpuWorkScope& operator=(const CpuWorkScope&)=delete;
 private:
  bool selected_; CpuWork kind_; std::uint64_t began_,units_;
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
