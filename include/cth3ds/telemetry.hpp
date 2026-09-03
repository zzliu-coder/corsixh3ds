#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>

namespace cth3ds {

struct PerformanceSnapshot {
  double average_frame_ms{0.0};
  double p95_frame_ms{0.0};
  double maximum_frame_ms{0.0};
  std::uint64_t dropped_frames{0};
  std::size_t texture_bytes{0};
  std::size_t linear_bytes{0};
};

class Telemetry {
 public:
  explicit Telemetry(std::size_t history_size = 240);

  void record_frame(std::uint64_t duration_us, bool dropped) noexcept;
  void set_memory(std::size_t texture_bytes, std::size_t linear_bytes) noexcept;
  [[nodiscard]] PerformanceSnapshot snapshot() const;
  void clear() noexcept;

 private:
  std::size_t history_size_{240};
  std::deque<std::uint64_t> frame_times_us_{};
  std::uint64_t dropped_frames_{0};
  std::size_t texture_bytes_{0};
  std::size_t linear_bytes_{0};
};

}  // namespace cth3ds
