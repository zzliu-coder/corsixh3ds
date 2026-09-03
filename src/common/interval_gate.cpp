#include "cth3ds/interval_gate.hpp"

#include <algorithm>
#include <limits>

namespace cth3ds {

IntervalGate::IntervalGate(std::uint64_t interval_us) noexcept
    : interval_us_(std::max<std::uint64_t>(1U, interval_us)) {}

void IntervalGate::reset(std::uint64_t now_us, bool fire_immediately) noexcept {
  initialized_ = true;
  last_seen_us_ = now_us;
  next_deadline_us_ = fire_immediately ? now_us : now_us + interval_us_;
}

bool IntervalGate::due(std::uint64_t now_us) noexcept {
  if (!initialized_) {
    reset(now_us, true);
  }
  if (now_us < last_seen_us_) {
    reset(now_us, true);
  }
  last_seen_us_ = now_us;
  if (now_us < next_deadline_us_) {
    return false;
  }
  if (now_us > std::numeric_limits<std::uint64_t>::max() - interval_us_) {
    next_deadline_us_ = std::numeric_limits<std::uint64_t>::max();
  } else {
    next_deadline_us_ = now_us + interval_us_;
  }
  return true;
}

}  // namespace cth3ds
