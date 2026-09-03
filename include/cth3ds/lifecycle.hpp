#pragma once

#include <cstdint>
#include <vector>

#include "cth3ds/events.hpp"

namespace cth3ds {

enum class LifecycleState {
  Running,
  SuspendPending,
  Suspended,
  ResumePending,
  ExitPending,
};

enum class LifecycleSignal {
  Suspend,
  Sleep,
  Restore,
  Wake,
  Exit,
};

struct LifecycleDecision {
  bool pause_simulation{false};
  bool pause_audio{false};
  bool resume_audio{false};
  bool request_autosave{false};
  bool request_exit{false};
};

class LifecycleController {
 public:
  explicit LifecycleController(std::uint64_t periodic_autosave_us = 60000000);

  [[nodiscard]] LifecycleDecision signal(LifecycleSignal signal,
                                         std::uint64_t now_us) noexcept;
  [[nodiscard]] LifecycleDecision tick(std::uint64_t now_us) noexcept;
  void reset(std::uint64_t now_us) noexcept;
  void begin_critical_io() noexcept { ++critical_io_depth_; }
  void end_critical_io() noexcept;

  [[nodiscard]] LifecycleState state() const noexcept { return state_; }
  [[nodiscard]] bool in_critical_io() const noexcept { return critical_io_depth_ > 0; }

 private:
  LifecycleState state_{LifecycleState::Running};
  std::uint64_t periodic_autosave_us_{60000000};
  std::uint64_t next_autosave_us_{0};
  int critical_io_depth_{0};
  bool deferred_suspend_save_{false};
  bool deferred_exit_{false};
};

}  // namespace cth3ds
