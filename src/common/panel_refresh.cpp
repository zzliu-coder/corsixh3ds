#include "cth3ds/panel_refresh.hpp"

#include <algorithm>

namespace cth3ds {

PanelRefreshGate::PanelRefreshGate(std::uint64_t frame_us) noexcept
    : frame_us_(std::max<std::uint64_t>(1, frame_us)) {}

void PanelRefreshGate::reset() noexcept {
  initialized_ = false;
  redraw_requested_ = true;
  next_frame_us_ = 0;
}

bool PanelRefreshGate::due(std::uint64_t now_us) noexcept {
  if (!initialized_) {
    initialized_ = true;
    next_frame_us_ = now_us + frame_us_;
    redraw_requested_ = false;
    return true;
  }

  if (redraw_requested_ || now_us >= next_frame_us_) {
    // Preserve the Panel contract: even an early redraw consumes one period.
    // Backwards time keeps the existing deadline; reset is the resume boundary.
    do {
      next_frame_us_ += frame_us_;
    } while (next_frame_us_ <= now_us);
    redraw_requested_ = false;
    return true;
  }
  return false;
}

}  // namespace cth3ds
