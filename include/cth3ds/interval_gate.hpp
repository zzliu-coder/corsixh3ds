#pragma once

#include <cstdint>

namespace cth3ds {

// Small monotonic-time helper. It fires at most once per call and resynchronises
// after long stalls or a clock reset, avoiding catch-up loops in the UI thread.
class IntervalGate {
 public:
  explicit IntervalGate(std::uint64_t interval_us = 1000000U) noexcept;

  void reset(std::uint64_t now_us, bool fire_immediately = false) noexcept;
  [[nodiscard]] bool due(std::uint64_t now_us) noexcept;
  [[nodiscard]] std::uint64_t next_deadline_us() const noexcept {
    return next_deadline_us_;
  }
  [[nodiscard]] std::uint64_t interval_us() const noexcept { return interval_us_; }

 private:
  std::uint64_t interval_us_{1000000U};
  std::uint64_t next_deadline_us_{0U};
  std::uint64_t last_seen_us_{0U};
  bool initialized_{false};
};

}  // namespace cth3ds
