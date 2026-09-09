#pragma once

#include <cstddef>
#include <cstdint>

namespace cth3ds {

// Load-time evidence for exactly one already-created image. No pixel storage,
// filename assumptions, palette lifetime dependency, or per-frame scan.
template<class Colours>
bool opaque_canvas_pixels(const std::uint8_t* pixels, std::size_t bytes,
                          int width, std::uint32_t flags,
                          const Colours& colours) noexcept {
  if (!pixels || width != 640 || bytes != 640U * 480U || flags != 0) return false;
  for (std::size_t i = 0; i < bytes; ++i) {
    if ((colours[pixels[i]] >> 24U) != 255U) return false;
  }
  return true;
}

} // namespace cth3ds
