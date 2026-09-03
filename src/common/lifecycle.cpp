#include "cth3ds/lifecycle.hpp"

#include <algorithm>

namespace cth3ds {

LifecycleController::LifecycleController(std::uint64_t periodic_autosave_us)
    : periodic_autosave_us_(std::max<std::uint64_t>(1000000, periodic_autosave_us)),
      next_autosave_us_(periodic_autosave_us_) {}

LifecycleDecision LifecycleController::signal(LifecycleSignal signal_value,
                                               std::uint64_t now_us) noexcept {
  LifecycleDecision decision;
  switch (signal_value) {
    case LifecycleSignal::Suspend:
    case LifecycleSignal::Sleep:
      if (state_ == LifecycleState::Suspended ||
          state_ == LifecycleState::SuspendPending ||
          state_ == LifecycleState::ExitPending) {
        break;
      }
      state_ = LifecycleState::SuspendPending;
      decision.pause_simulation = true;
      decision.pause_audio = true;
      if (in_critical_io()) {
        deferred_suspend_save_ = true;
      } else {
        decision.request_autosave = true;
      }
      state_ = LifecycleState::Suspended;
      break;
    case LifecycleSignal::Restore:
    case LifecycleSignal::Wake:
      if (state_ == LifecycleState::Running ||
          state_ == LifecycleState::ExitPending) {
        break;
      }
      state_ = LifecycleState::ResumePending;
      decision.resume_audio = true;
      state_ = LifecycleState::Running;
      next_autosave_us_ = now_us + periodic_autosave_us_;
      break;
    case LifecycleSignal::Exit:
      if (state_ == LifecycleState::ExitPending) {
        break;
      }
      state_ = LifecycleState::ExitPending;
      decision.pause_simulation = true;
      decision.pause_audio = true;
      if (in_critical_io()) {
        // Finish the current filesystem transaction before issuing a final
        // autosave and SDL_QUIT. Exiting halfway through a rename sequence is
        // exactly the failure atomic saves are intended to prevent.
        deferred_suspend_save_ = true;
        deferred_exit_ = true;
      } else {
        decision.request_autosave = true;
        decision.request_exit = true;
      }
      break;
  }
  return decision;
}

void LifecycleController::reset(std::uint64_t now_us) noexcept {
  state_ = LifecycleState::Running;
  next_autosave_us_ = now_us + periodic_autosave_us_;
  critical_io_depth_ = 0;
  deferred_suspend_save_ = false;
  deferred_exit_ = false;
}

LifecycleDecision LifecycleController::tick(std::uint64_t now_us) noexcept {
  LifecycleDecision decision;
  if (state_ == LifecycleState::Running && now_us >= next_autosave_us_) {
    if (in_critical_io()) {
      deferred_suspend_save_ = true;
    } else {
      decision.request_autosave = true;
    }
    do {
      next_autosave_us_ += periodic_autosave_us_;
    } while (next_autosave_us_ <= now_us);
  }
  if (!in_critical_io() && deferred_suspend_save_) {
    deferred_suspend_save_ = false;
    decision.request_autosave = true;
  }
  if (!in_critical_io() && deferred_exit_) {
    deferred_exit_ = false;
    decision.request_exit = true;
  }
  return decision;
}

void LifecycleController::end_critical_io() noexcept {
  if (critical_io_depth_ > 0) {
    --critical_io_depth_;
  }
}

}  // namespace cth3ds
