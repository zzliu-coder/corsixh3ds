// Fixed R73 reference from commit 17603cb2ba832d57de7d3926b680cf6d5fabe610.
// Only namespace and local include handling differ from the original files.
#pragma once

#include <cstdint>

namespace r73_original {

class FrameScheduler {
 public:
  struct Decision {
    int simulation_steps{0};
    bool render_top{false};
    bool render_bottom{false};
    bool dropped_time{false};
  };

  FrameScheduler(std::uint64_t simulation_step_us = 18000,
                 std::uint64_t top_frame_us = 33333,
                 std::uint64_t bottom_frame_us = 50000,
                 int max_catchup_steps = 4);

  [[nodiscard]] Decision advance(std::uint64_t now_us) noexcept;
  void reset(std::uint64_t now_us = 0) noexcept;
  void request_redraw() noexcept { redraw_requested_ = true; }

 private:
  std::uint64_t simulation_step_us_{18000};
  std::uint64_t top_frame_us_{33333};
  std::uint64_t bottom_frame_us_{50000};
  int max_catchup_steps_{4};
  bool initialized_{false};
  bool redraw_requested_{true};
  std::uint64_t last_time_us_{0};
  std::uint64_t simulation_accumulator_us_{0};
  std::uint64_t next_top_frame_us_{0};
  std::uint64_t next_bottom_frame_us_{0};
};

}  // namespace r73_original


#include <algorithm>

namespace r73_original {

FrameScheduler::FrameScheduler(std::uint64_t simulation_step_us,
                               std::uint64_t top_frame_us,
                               std::uint64_t bottom_frame_us,
                               int max_catchup_steps)
    : simulation_step_us_(std::max<std::uint64_t>(1, simulation_step_us)),
      top_frame_us_(std::max<std::uint64_t>(1, top_frame_us)),
      bottom_frame_us_(std::max<std::uint64_t>(1, bottom_frame_us)),
      max_catchup_steps_(std::max(1, max_catchup_steps)) {}

void FrameScheduler::reset(std::uint64_t now_us) noexcept {
  initialized_ = false;
  redraw_requested_ = true;
  last_time_us_ = now_us;
  simulation_accumulator_us_ = 0;
  next_top_frame_us_ = now_us;
  next_bottom_frame_us_ = now_us;
}

FrameScheduler::Decision FrameScheduler::advance(std::uint64_t now_us) noexcept {
  Decision decision;
  if (!initialized_) {
    initialized_ = true;
    last_time_us_ = now_us;
    next_top_frame_us_ = now_us + top_frame_us_;
    next_bottom_frame_us_ = now_us + bottom_frame_us_;
    decision.render_top = true;
    decision.render_bottom = true;
    redraw_requested_ = false;
    return decision;
  }

  const std::uint64_t elapsed = now_us >= last_time_us_ ? now_us - last_time_us_ : 0;
  last_time_us_ = now_us;
  simulation_accumulator_us_ += elapsed;

  while (simulation_accumulator_us_ >= simulation_step_us_ &&
         decision.simulation_steps < max_catchup_steps_) {
    simulation_accumulator_us_ -= simulation_step_us_;
    ++decision.simulation_steps;
  }
  if (simulation_accumulator_us_ >= simulation_step_us_) {
    simulation_accumulator_us_ %= simulation_step_us_;
    decision.dropped_time = true;
  }

  if (redraw_requested_ || now_us >= next_top_frame_us_) {
    decision.render_top = true;
    do {
      next_top_frame_us_ += top_frame_us_;
    } while (next_top_frame_us_ <= now_us);
  }
  if (redraw_requested_ || now_us >= next_bottom_frame_us_) {
    decision.render_bottom = true;
    do {
      next_bottom_frame_us_ += bottom_frame_us_;
    } while (next_bottom_frame_us_ <= now_us);
  }
  redraw_requested_ = false;
  return decision;
}

}  // namespace r73_original
