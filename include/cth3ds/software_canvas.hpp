#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

#include "cth3ds/bottom_ui.hpp"
#include "cth3ds/types.hpp"

namespace cth3ds {

struct Rgba {
  std::uint8_t r{0};
  std::uint8_t g{0};
  std::uint8_t b{0};
  std::uint8_t a{255};
};

class SoftwareCanvas {
 public:
  SoftwareCanvas(int width, int height);

  void clear(Rgba color) noexcept;
  void pixel(int x, int y, Rgba color) noexcept;
  void fill_rect(RectI rect, Rgba color) noexcept;
  void stroke_rect(RectI rect, Rgba color, int thickness = 1) noexcept;
  void line(Vec2i from, Vec2i to, Rgba color) noexcept;
  void text(int x, int y, const std::string& value, Rgba color,
            int scale = 1) noexcept;
  void text_centered(RectI area, const std::string& value, Rgba color,
                     int scale = 1) noexcept;

  [[nodiscard]] bool write_ppm(const std::filesystem::path& path,
                               std::string& error) const;
  [[nodiscard]] int width() const noexcept { return width_; }
  [[nodiscard]] int height() const noexcept { return height_; }
  [[nodiscard]] const std::vector<std::uint8_t>& rgba_bytes() const noexcept {
    return pixels_;
  }

 private:
  void glyph(int x, int y, char character, Rgba color, int scale) noexcept;

  int width_{0};
  int height_{0};
  std::vector<std::uint8_t> pixels_{};
};

void render_bottom_ui(SoftwareCanvas& canvas, const BottomUiController& ui);
void render_top_placeholder(SoftwareCanvas& canvas, const BottomUiState& state,
                            Vec2f camera_offset, float zoom);

}  // namespace cth3ds
