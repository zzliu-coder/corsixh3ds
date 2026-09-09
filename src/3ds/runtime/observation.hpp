#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include "cth3ds/telemetry.hpp"
#include "cth3ds/memory_telemetry.hpp"
#include "cth3ds/simulation_clock.hpp"
#include "cth3ds/slow_events.hpp"
#include "cth3ds/frame_tail.hpp"

namespace cth3ds {
// Main-thread observation owns only records. No SDL/Lua/allocator access,
// game callbacks, GC, or writable simulation clock crosses this boundary.
struct ObservationInputs {
  std::uint64_t now{}, heap_available_estimate{}, heap_available_low_water{};
  std::uint64_t lua_bytes{}, linear_free{}, log_time_us{}, workload_time_us{};
  std::uint64_t log_flushes{}, log_bytes{};
  bool log_failed{}, log_truncated{};
  SimulationClock::Statistics clock{};
};
struct ObservationOutput {
  void (*line)(const char*, ...);
  void (*flush)() noexcept;
  void (*display)();
};
class RuntimeObservations {
 public:
  RuntimeObservations() = default;
  RuntimeObservations(const RuntimeObservations&) = delete;
  RuntimeObservations& operator=(const RuntimeObservations&) = delete;
  // Keep this large owner in permanent storage. Reset in place: value
  // assignment creates a temporary larger than the Old 3DS main stack.
  void reset(std::uint64_t now) noexcept;
  Telemetry timing;
  MemoryTelemetry memory;
  SlowEvents slow;
  FrameTail frame_tail;
  std::array<char,96> scene{};
  bool window_has_operation{}, window_scene_changed{};
  bool terminal{}, terminal_saved{}, flush_requested{};
  std::uint64_t compact_us{}, full_us{}, timer_events{}, logic_callbacks{}, logic_failures{};
  bool due(std::uint64_t now, bool force) const noexcept;
  void observe(const char* site, const MemoryObservation& observation) noexcept;
  void flush(const ObservationInputs& inputs, const ObservationOutput& output, bool force) noexcept;
  void sample_mark(const char* event, std::uint64_t now, const ObservationOutput& output,
                   const SimulationClock::Statistics* clock = nullptr) noexcept;
  void sample_present(std::uint64_t now, PresentResult result) noexcept;
  void seal_tail(std::uint64_t now, const ObservationOutput& output,const char* event="SHUTDOWN") noexcept;
  bool sample_open() const noexcept { return sample_active; }
  bool sample_can_close(std::uint64_t now) const noexcept {
    return sample_active && now>=sample_begin && (!sample_anchor || now>=sample_last);
  }
  bool sample_eligible(std::uint64_t now) const noexcept;
 private:
  void report_tail(const char* event,const ObservationOutput& output) const noexcept;
  DurationDistribution sample_intervals;
  std::uint64_t sample_begin{},sample_first{},sample_last{};
  bool sample_active{},sample_valid{},sample_anchor{};
  SimulationClock::Statistics sample_clock_begin{};
  bool sample_clock_valid{};
  struct OperationSample {std::array<char,24> site{};MemoryObservation observation;};
  std::array<OperationSample,64> operations{};
  std::size_t operation_count{};
  std::uint64_t operation_overflow{};
};
} // namespace cth3ds
