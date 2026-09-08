#pragma once
#include <algorithm>
#include <cstdint>

namespace cth3ds {

// Scheduling policy only: World retains its original five speed/tick rules.
// No callback, thread, allocation, or wall-clock I/O inside this component.
class SimulationClock {
 public:
  static constexpr std::uint64_t step_us = 18000;
  static constexpr std::uint64_t budget_us = 24000;
  static constexpr unsigned max_steps = 4;
  static constexpr std::uint64_t max_debt_us = step_us * 8;
  struct Statistics {
    std::uint64_t steps{}, dropped_us{}, rebases{}, budget_exits{}, debt_us{};
    std::uint64_t completed_steps{}, failed_steps{};
  };
  void reset() noexcept { *this = {}; }
  // Save/load, applet, HOME/lid and scene replacement must never be caught up.
  void interrupt() noexcept { rebase_ = true; debt_us_ = 0; }
  void begin(std::uint64_t now) noexcept {
    batch_started_ = now; batch_steps_ = 0;
    if (!initialized_ || rebase_ || now < last_us_) {
      initialized_ = true; rebase_ = false; last_us_ = now; debt_us_ = 0;
      ++stats_.rebases;
      return;
    }
    const auto elapsed = now - last_us_;
    last_us_ = now;
    const auto accepted = std::min(elapsed, max_debt_us - debt_us_);
    debt_us_ += accepted;
    stats_.dropped_us += elapsed - accepted;
  }
  bool take_step(std::uint64_t now) noexcept {
    if (rebase_ || debt_us_ < step_us || batch_steps_ >= max_steps) return false;
    // One expensive callback can exceed the budget; yield before the next.
    if (batch_steps_ && (now < batch_started_ || now - batch_started_ >= budget_us)) {
      ++stats_.budget_exits;
      return false;
    }
    debt_us_ -= step_us; ++batch_steps_; ++stats_.steps;
    return true;
  }
  Statistics statistics() const noexcept { auto s=stats_; s.debt_us=debt_us_; return s; }
  void complete_step(bool success) noexcept {
    if(success)++stats_.completed_steps;
    else ++stats_.failed_steps;
  }
 private:
  std::uint64_t last_us_{}, batch_started_{}, debt_us_{};
  unsigned batch_steps_{};
  bool initialized_{}, rebase_{};
  Statistics stats_{};
};
}  // namespace cth3ds
