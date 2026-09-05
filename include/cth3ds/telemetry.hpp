#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace cth3ds {

enum class TimingStage : std::uint8_t {
  Event, Runtime, Logic, Render, Top, Bottom, GC, Save, Load, Restore, Count
};
inline constexpr std::array<const char*, 10> kTimingStageNames{{
    "event", "runtime", "logic", "render", "top", "bottom", "gc",
    "save", "load", "restore"}};
enum class PresentResult : std::uint8_t { Success, Failed, Skipped };

struct DurationSummary {
  std::uint64_t count{0}, total_us{0}, maximum_us{0};
  bool total_overflowed{false};
  // Nearest-rank bounds: 100us bins through 100ms, power-of-two tail.
  std::uint64_t p50_lower_us{0}, p50_upper_us{0};
  std::uint64_t p95_lower_us{0}, p95_upper_us{0};
  std::uint64_t p99_lower_us{0}, p99_upper_us{0};
};
class DurationDistribution {
 public:
  void add(std::uint64_t us) noexcept;
  [[nodiscard]] DurationSummary snapshot() const noexcept;
  void clear() noexcept;
 private:
  std::array<std::uint64_t, 1065> bins_{};
  std::uint64_t count_{0}, total_{0}, maximum_{0};
  bool overflowed_{false};
};
struct SpanSummary {
  std::uint64_t completed{0}, failed{0}, inclusive_us{0}, exclusive_us{0};
  std::uint64_t maximum_us{0}, open{0};
};
struct PerformanceSnapshot {
  // Compatibility fields describe legacy duration calls when no present
  // intervals exist. They never imply a successful product frame.
  double average_frame_ms{0.0}, p95_frame_ms{0.0}, maximum_frame_ms{0.0};
  std::uint64_t dropped_frames{0};
  std::size_t texture_bytes{0}, linear_bytes{0};
  DurationSummary intervals{}, legacy_durations{};
  std::array<SpanSummary, 10> stages{};
  std::uint64_t successful_presents{0}, failed_presents{0}, skipped_presents{0};
  std::uint64_t window_begin_us{0}, observed_until_us{0}, elapsed_us{0};
  // Intervals are attributed to their completion window, including a crossing
  // interval in full. Its start can precede window_begin_us; no silent clipping.
  std::uint64_t interval_coverage_begin_us{0}, interval_coverage_end_us{0};
  std::uint64_t open_present_gap_us{0}, invalid_events{0};
  bool has_present_anchor{false};
};

class Telemetry {
 public:
  // Retained for source compatibility. No rolling history or dynamic memory.
  explicit Telemetry(std::size_t history_size = 240) noexcept;
  void record_frame(std::uint64_t duration_us, bool dropped) noexcept;
  void set_memory(std::size_t texture_bytes, std::size_t linear_bytes) noexcept;
  void present_complete(std::uint64_t now_us, PresentResult result) noexcept;
  // One normal-thread LIFO stack, maximum 16 spans. Token 0 means rejected.
  [[nodiscard]] std::uint64_t begin_span(TimingStage stage, std::uint64_t now_us) noexcept;
  bool end_span(std::uint64_t token, std::uint64_t now_us, bool success = true) noexcept;
  [[nodiscard]] PerformanceSnapshot snapshot() const noexcept;
  [[nodiscard]] PerformanceSnapshot snapshot(std::uint64_t now_us) const noexcept;
  // Flush at a quiescent loop/operation boundary after >=60s, using actual
  // elapsed time. Refuses active spans; keeps the successful-present anchor.
  bool reset_window(std::uint64_t now_us) noexcept;
  void clear() noexcept;
 private:
  struct Span { TimingStage stage{}; std::uint64_t token{0}, begin_us{0}; };
  bool advance(std::uint64_t now_us) noexcept;
  DurationDistribution intervals_{}, legacy_{};
  std::array<SpanSummary, 10> stages_{};
  std::array<Span, 16> stack_{};
  std::size_t depth_{0};
  std::uint64_t next_token_{0}, last_us_{0}, window_begin_us_{0};
  std::uint64_t previous_present_us_{0}, coverage_begin_us_{0}, coverage_end_us_{0};
  std::uint64_t successes_{0}, failures_{0}, skipped_{0}, invalid_{0}, dropped_{0};
  std::size_t texture_bytes_{0}, linear_bytes_{0};
  bool started_{false}, has_present_{false}, has_interval_{false};
};

}  // namespace cth3ds
