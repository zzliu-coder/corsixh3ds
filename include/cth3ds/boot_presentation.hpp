#pragma once

#include "cth3ds/framebuffer_scaler.hpp"
#include "cth3ds/presentation_masks.hpp"

namespace cth3ds {

// Only presentation owns this state. Stage numbers and simulation readiness
// intentionally have no influence. Fatal remains latched until runtime reset.
enum class PresentationMode { BootText, BootArtwork, Game, Error };
class BootPresentation {
 public:
  PresentationMode mode() const noexcept { return mode_; }
  void artwork() noexcept { if (mode_ == PresentationMode::BootText) mode_ = PresentationMode::BootArtwork; }
  void game() noexcept { if (mode_ != PresentationMode::Error) mode_ = PresentationMode::Game; }
  void error() noexcept { mode_ = PresentationMode::Error; }
  void reset() noexcept { mode_ = PresentationMode::BootText; }
 private:
  PresentationMode mode_{PresentationMode::BootText};
};

struct ArtworkSlice { RectI source, destination; };
// The original disc occupies (163,84)-(474,395). Remove only its black margins:
// 352x352 -> 320x320, split at the hinge; retain the original notice separately.
// Both disc halves share 10/11 scale. GameView stays untouched.
inline constexpr ArtworkSlice kArtworkTop{{144, 64, 352, 176}, {40, 80, 320, 160}};
inline constexpr ArtworkSlice kArtworkBottom{{144, 240, 352, 176}, {0, 0, 320, 160}};
inline constexpr ArtworkSlice kArtworkNotice{{0, 432, 640, 48}, {0, 184, 320, 24}};
inline constexpr std::uint32_t kArtworkBackground = 0xff000000U;

inline bool copy_boot_artwork(const std::uint32_t* source, int source_pitch,
                             std::uint32_t* destination, int width, int pitch,
                             bool top, std::uint32_t background,
                             bool swap_bytes = false) noexcept {
  if (!source || !destination || source_pitch < 640 || width != (top ? 400 : 320) || pitch < width)
    return false;
  for (int y = 0; y < 240; ++y)
    for (int x = 0; x < width; ++x) destination[y * pitch + x] = background;
  const auto slice = top ? kArtworkTop : kArtworkBottom;
  const bool ok = scale_rgba_view(source, 640, 480, source_pitch, slice.source,
                        destination + slice.destination.y * pitch + slice.destination.x,
                        slice.destination.w, slice.destination.h, pitch, swap_bytes);
  if (top || !ok) return ok;
  const auto notice = kArtworkNotice;
  return scale_rgba_view(source, 640, 480, source_pitch, notice.source,
                        destination + notice.destination.y * pitch + notice.destination.x,
                        notice.destination.w, notice.destination.h, pitch, swap_bytes);
}

// A plot callback makes the same constant alpha mask usable for SDL pixels,
// the existing 13-high SoftwareCanvas strip, and host render verification.
template<class Plot>
inline void paint_fixed_mask(const presentation_masks::Mask& mask, int left, int top, Plot plot) {
  for (int y = 0; y < mask.height; ++y) for (int x = 0; x < mask.width; ++x) {
    const unsigned i = static_cast<unsigned>(y * mask.width + x);
    const auto pair = mask.data[i / 2];
    const unsigned alpha = (i % 2 ? pair & 15U : pair >> 4U) * 17U;
    if (alpha) plot(left + x, top + y, alpha);
  }
}
} // namespace cth3ds
