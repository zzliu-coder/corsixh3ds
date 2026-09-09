#pragma once

#include <cstdint>

namespace cth3ds {

// Refresh cadence for the optional legacy lower-screen Panel only.
// Game simulation and presentation are owned by their separate clocks.
class PanelRefreshGate {
 public:
  explicit PanelRefreshGate(std::uint64_t frame_us = 50000) noexcept;

  [[nodiscard]] bool due(std::uint64_t now_us) noexcept;
  void reset() noexcept;
  void request_redraw() noexcept { redraw_requested_ = true; }

 private:
  std::uint64_t frame_us_{50000};
  std::uint64_t next_frame_us_{0};
  bool initialized_{false};
  bool redraw_requested_{true};
};

}  // namespace cth3ds
