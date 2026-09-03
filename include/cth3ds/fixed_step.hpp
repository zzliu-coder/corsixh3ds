#pragma once

#include <cstdint>

namespace cth3ds {

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

}  // namespace cth3ds
