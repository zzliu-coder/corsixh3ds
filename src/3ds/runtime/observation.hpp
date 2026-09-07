#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include "cth3ds/telemetry.hpp"
#include "cth3ds/memory_telemetry.hpp"
#include "cth3ds/simulation_clock.hpp"
#include "cth3ds/slow_events.hpp"

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
  Telemetry timing;
  MemoryTelemetry memory;
  SlowEvents slow;
  std::array<char,96> scene{};
  bool window_has_operation{}, window_scene_changed{};
  bool terminal{}, terminal_saved{}, flush_requested{};
  std::uint64_t compact_us{}, full_us{}, timer_events{}, logic_callbacks{}, logic_failures{};
  bool due(std::uint64_t now, bool force) const noexcept;
  void observe(const char* site, const MemoryObservation& observation) noexcept;
  void flush(const ObservationInputs& inputs, const ObservationOutput& output, bool force) noexcept;
 private:
  struct OperationSample {std::array<char,24> site{};MemoryObservation observation;};
  std::array<OperationSample,64> operations{};
  std::size_t operation_count{};
  std::uint64_t operation_overflow{};
};
} // namespace cth3ds
