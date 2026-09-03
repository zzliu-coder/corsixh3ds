#include "cth3ds/telemetry.hpp"

#include <algorithm>
#include <numeric>
#include <vector>

namespace cth3ds {

Telemetry::Telemetry(std::size_t history_size)
    : history_size_(std::max<std::size_t>(1U, history_size)) {}

void Telemetry::record_frame(std::uint64_t duration_us, bool dropped) noexcept {
  frame_times_us_.push_back(duration_us);
  if (frame_times_us_.size() > history_size_) {
    frame_times_us_.pop_front();
  }
  if (dropped) {
    ++dropped_frames_;
  }
}

void Telemetry::set_memory(std::size_t texture_bytes,
                           std::size_t linear_bytes) noexcept {
  texture_bytes_ = texture_bytes;
  linear_bytes_ = linear_bytes;
}

PerformanceSnapshot Telemetry::snapshot() const {
  PerformanceSnapshot result;
  result.dropped_frames = dropped_frames_;
  result.texture_bytes = texture_bytes_;
  result.linear_bytes = linear_bytes_;
  if (frame_times_us_.empty()) {
    return result;
  }
  const std::uint64_t total =
      std::accumulate(frame_times_us_.begin(), frame_times_us_.end(), std::uint64_t{0});
  result.average_frame_ms = static_cast<double>(total) /
                            static_cast<double>(frame_times_us_.size()) / 1000.0;
  std::vector<std::uint64_t> sorted(frame_times_us_.begin(), frame_times_us_.end());
  std::sort(sorted.begin(), sorted.end());
  const std::size_t p95_index = (sorted.size() - 1U) * 95U / 100U;
  result.p95_frame_ms = static_cast<double>(sorted[p95_index]) / 1000.0;
  result.maximum_frame_ms = static_cast<double>(sorted.back()) / 1000.0;
  return result;
}

void Telemetry::clear() noexcept {
  frame_times_us_.clear();
  dropped_frames_ = 0;
  texture_bytes_ = 0;
  linear_bytes_ = 0;
}

}  // namespace cth3ds
