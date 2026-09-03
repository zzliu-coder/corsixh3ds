#include "cth3ds/software_canvas.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstring>
#include <fstream>
#include <sstream>

#include "cth3ds/screen_layout.hpp"

namespace cth3ds {
namespace {

using Glyph = std::array<std::uint8_t, 7>;

Glyph glyph_for(char character) noexcept {
  const char c = static_cast<char>(std::toupper(static_cast<unsigned char>(character)));
  switch (c) {
    case 'A': return {0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11};
    case 'B': return {0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E};
    case 'C': return {0x0F, 0x10, 0x10, 0x10, 0x10, 0x10, 0x0F};
    case 'D': return {0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E};
    case 'E': return {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F};
    case 'F': return {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10};
    case 'G': return {0x0F, 0x10, 0x10, 0x17, 0x11, 0x11, 0x0F};
    case 'H': return {0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11};
    case 'I': return {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x1F};
    case 'J': return {0x07, 0x02, 0x02, 0x02, 0x12, 0x12, 0x0C};
    case 'K': return {0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11};
    case 'L': return {0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F};
    case 'M': return {0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11};
    case 'N': return {0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11};
    case 'O': return {0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E};
    case 'P': return {0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10};
    case 'Q': return {0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D};
    case 'R': return {0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11};
    case 'S': return {0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E};
    case 'T': return {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04};
    case 'U': return {0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E};
    case 'V': return {0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04};
    case 'W': return {0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A};
    case 'X': return {0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11};
    case 'Y': return {0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04};
    case 'Z': return {0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F};
    case '0': return {0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E};
    case '1': return {0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E};
    case '2': return {0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F};
    case '3': return {0x1E, 0x01, 0x01, 0x0E, 0x01, 0x01, 0x1E};
    case '4': return {0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02};
    case '5': return {0x1F, 0x10, 0x10, 0x1E, 0x01, 0x01, 0x1E};
    case '6': return {0x0E, 0x10, 0x10, 0x1E, 0x11, 0x11, 0x0E};
    case '7': return {0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08};
    case '8': return {0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E};
    case '9': return {0x0E, 0x11, 0x11, 0x0F, 0x01, 0x01, 0x0E};
    case '-': return {0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00};
    case '+': return {0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00};
    case ':': return {0x00, 0x04, 0x04, 0x00, 0x04, 0x04, 0x00};
    case '/': return {0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10};
    case '.': return {0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C};
    case '$': return {0x04, 0x0F, 0x14, 0x0E, 0x05, 0x1E, 0x04};
    case '%': return {0x19, 0x1A, 0x02, 0x04, 0x08, 0x0B, 0x13};
    case '!': return {0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04};
    case '?': return {0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04};
    case ' ': return {};
    default: return {0x1F, 0x11, 0x15, 0x11, 0x15, 0x11, 0x1F};
  }
}

constexpr Rgba kBackground{18, 25, 32, 255};
constexpr Rgba kPanel{37, 49, 61, 255};
constexpr Rgba kPanelRaised{52, 68, 82, 255};
constexpr Rgba kAccent{233, 180, 63, 255};
constexpr Rgba kText{239, 242, 244, 255};
constexpr Rgba kMuted{164, 177, 188, 255};
constexpr Rgba kDanger{214, 76, 70, 255};
constexpr Rgba kGrid{69, 91, 105, 255};
constexpr Rgba kWorldFloor{126, 164, 100, 255};
constexpr Rgba kWorldWall{217, 210, 181, 255};
constexpr Rgba kWorldRoom{126, 176, 193, 255};

std::string truncate(const std::string& value, std::size_t maximum) {
  return value.size() <= maximum ? value : value.substr(0, maximum);
}

}  // namespace

SoftwareCanvas::SoftwareCanvas(int width, int height)
    : width_(std::max(1, width)),
      height_(std::max(1, height)),
      pixels_(static_cast<std::size_t>(std::max(1, width)) *
                  static_cast<std::size_t>(std::max(1, height)) * 4U,
              0U) {}

void SoftwareCanvas::clear(Rgba color) noexcept {
  if (color.r == color.g && color.g == color.b && color.b == color.a) {
    std::memset(pixels_.data(), color.r, pixels_.size());
    return;
  }
  fill_rect({0, 0, width_, height_}, color);
}

void SoftwareCanvas::pixel(int x, int y, Rgba color) noexcept {
  if (x < 0 || y < 0 || x >= width_ || y >= height_) {
    return;
  }
  const std::size_t index =
      (static_cast<std::size_t>(y) * static_cast<std::size_t>(width_) +
       static_cast<std::size_t>(x)) *
      4U;
  pixels_[index] = color.r;
  pixels_[index + 1U] = color.g;
  pixels_[index + 2U] = color.b;
  pixels_[index + 3U] = color.a;
}

void SoftwareCanvas::fill_rect(RectI rect, Rgba color) noexcept {
  const int left = clamp_int(rect.x, 0, width_);
  const int top = clamp_int(rect.y, 0, height_);
  const int right = clamp_int(rect.right(), 0, width_);
  const int bottom = clamp_int(rect.bottom(), 0, height_);
  if (left >= right || top >= bottom) {
    return;
  }
  // Fill whole rows at a time. The previous per-pixel path re-clamped and
  // re-indexed on every pixel, which cost roughly 200k calls for a single
  // full-screen clear on a 268 MHz ARM11.
  const std::size_t span = static_cast<std::size_t>(right - left);
  const std::size_t stride = static_cast<std::size_t>(width_) * 4U;
  std::uint8_t* first_row =
      pixels_.data() + static_cast<std::size_t>(top) * stride +
      static_cast<std::size_t>(left) * 4U;
  for (std::size_t i = 0; i < span; ++i) {
    first_row[i * 4U] = color.r;
    first_row[i * 4U + 1U] = color.g;
    first_row[i * 4U + 2U] = color.b;
    first_row[i * 4U + 3U] = color.a;
  }
  // Every later row is a straight copy of the first one.
  const std::size_t row_bytes = span * 4U;
  for (int y = top + 1; y < bottom; ++y) {
    std::memcpy(pixels_.data() + static_cast<std::size_t>(y) * stride +
                    static_cast<std::size_t>(left) * 4U,
                first_row, row_bytes);
  }
}

void SoftwareCanvas::stroke_rect(RectI rect, Rgba color, int thickness) noexcept {
  const int safe = std::max(1, thickness);
  fill_rect({rect.x, rect.y, rect.w, safe}, color);
  fill_rect({rect.x, rect.bottom() - safe, rect.w, safe}, color);
  fill_rect({rect.x, rect.y, safe, rect.h}, color);
  fill_rect({rect.right() - safe, rect.y, safe, rect.h}, color);
}

void SoftwareCanvas::line(Vec2i from, Vec2i to, Rgba color) noexcept {
  int x0 = from.x;
  int y0 = from.y;
  const int x1 = to.x;
  const int y1 = to.y;
  const int dx = std::abs(x1 - x0);
  const int sx = x0 < x1 ? 1 : -1;
  const int dy = -std::abs(y1 - y0);
  const int sy = y0 < y1 ? 1 : -1;
  int error = dx + dy;
  for (;;) {
    pixel(x0, y0, color);
    if (x0 == x1 && y0 == y1) {
      break;
    }
    const int twice = 2 * error;
    if (twice >= dy) {
      error += dy;
      x0 += sx;
    }
    if (twice <= dx) {
      error += dx;
      y0 += sy;
    }
  }
}

void SoftwareCanvas::glyph(int x, int y, char character, Rgba color,
                           int scale) noexcept {
  const Glyph data = glyph_for(character);
  const int safe_scale = std::max(1, scale);
  for (int row = 0; row < 7; ++row) {
    for (int column = 0; column < 5; ++column) {
      const std::uint8_t mask = static_cast<std::uint8_t>(1U << (4U - static_cast<unsigned int>(column)));
      if ((data[static_cast<std::size_t>(row)] & mask) != 0U) {
        fill_rect({x + column * safe_scale, y + row * safe_scale,
                   safe_scale, safe_scale}, color);
      }
    }
  }
}

void SoftwareCanvas::text(int x, int y, const std::string& value, Rgba color,
                          int scale) noexcept {
  const int safe_scale = std::max(1, scale);
  int cursor = x;
  for (const char character : value) {
    glyph(cursor, y, character, color, safe_scale);
    cursor += 6 * safe_scale;
  }
}

void SoftwareCanvas::text_centered(RectI area, const std::string& value,
                                   Rgba color, int scale) noexcept {
  const int safe_scale = std::max(1, scale);
  const int width = static_cast<int>(value.size()) * 6 * safe_scale - safe_scale;
  const int height = 7 * safe_scale;
  text(area.x + (area.w - width) / 2, area.y + (area.h - height) / 2,
       value, color, safe_scale);
}

bool SoftwareCanvas::write_ppm(const std::filesystem::path& path,
                               std::string& error) const {
  std::ofstream output(path, std::ios::binary | std::ios::trunc);
  if (!output) {
    error = "cannot create PPM image";
    return false;
  }
  output << "P6\n" << width_ << ' ' << height_ << "\n255\n";
  for (std::size_t i = 0; i < pixels_.size(); i += 4U) {
    output.put(static_cast<char>(pixels_[i]));
    output.put(static_cast<char>(pixels_[i + 1U]));
    output.put(static_cast<char>(pixels_[i + 2U]));
  }
  if (!output) {
    error = "failed while writing PPM image";
    return false;
  }
  return true;
}

void render_bottom_ui(SoftwareCanvas& canvas, const BottomUiController& ui) {
  const BottomUiState& state = ui.state();
  canvas.clear(kBackground);
  canvas.fill_rect(ScreenLayout::status_bar(), kPanel);

  std::ostringstream cash;
  cash << '$' << state.cash;
  canvas.text(4, 3, truncate(cash.str(), 15U), kText);
  std::ostringstream date;
  date << state.day << '/' << state.month << '/' << state.year;
  canvas.text(112, 3, date.str(), kMuted);

  std::ostringstream system;
  if (state.battery_level >= 0) {
    system << "B" << state.battery_level << (state.charging ? "+" : "");
  } else {
    system << "B?";
  }
  system << " W" << (state.wifi_strength >= 0 ? std::to_string(state.wifi_strength) : "?");
  system << " V" << (state.volume_slider >= 0 ? std::to_string(state.volume_slider) : "?");
  if (state.free_memory_bytes > 0U) {
    system << " M" << (state.free_memory_bytes / (1024U * 1024U));
  }
  if (!state.build_tag.empty()) {
    system << ' ' << state.build_tag;
  }
  canvas.text(4, 14, truncate(system.str(), 31U),
              state.battery_level >= 0 && state.battery_level <= 1 ? kDanger : kMuted);

  static const std::array<const char*, 6> labels{
      "HOME", "BUILD", "STAFF", "PAT", "MONEY", "MSG"};
  for (int i = 0; i < 6; ++i) {
    const RectI rect = ScreenLayout::tab_rect(i);
    const bool active = static_cast<int>(state.active_tab) == i;
    canvas.fill_rect(rect, active ? kAccent : kPanelRaised);
    canvas.stroke_rect(rect, kBackground);
    canvas.text_centered(rect, labels[static_cast<std::size_t>(i)],
                         active ? kBackground : kText);
  }

  const RectI content = ScreenLayout::content_area();
  canvas.fill_rect(content, kPanel);

  if (state.active_tab == BottomTab::Dashboard) {
    const std::array<std::string, 4> rows{
        "BANK  REP " + std::to_string(state.reputation),
        "MAP   QUEUE " + std::to_string(state.queue_count),
        "CASE  PAT " + std::to_string(state.patient_count),
        "RESEARCH STAFF " + std::to_string(state.staff_count),
    };
    for (int row = 0; row < 4; ++row) {
      const RectI area{8, content.y + row * 38 + 4, 304, 32};
      canvas.fill_rect(area, row % 2 == 0 ? kPanelRaised : kPanel);
      canvas.text(16, area.y + 12, rows[static_cast<std::size_t>(row)], kText);
    }
  } else if (state.active_tab == BottomTab::Build) {
    const auto grid = ScreenLayout::build_grid();
    canvas.fill_rect(grid.bounds, kWorldFloor);
    for (int column = 0; column <= grid.columns; ++column) {
      const int x = grid.bounds.x + column * grid.cell_size;
      canvas.line({x, grid.bounds.y}, {x, grid.bounds.bottom()}, kGrid);
    }
    for (int row = 0; row <= grid.rows; ++row) {
      const int y = grid.bounds.y + row * grid.cell_size;
      canvas.line({grid.bounds.x, y}, {grid.bounds.right(), y}, kGrid);
    }
    const RectI preview = ui.room_preview_cells();
    if (!preview.empty()) {
      const RectI pixels = ScreenLayout::grid_rect_to_pixels(preview, grid);
      canvas.fill_rect(pixels, kWorldRoom);
      canvas.stroke_rect(pixels, kAccent, 2);
    }
  } else {
    canvas.text(12, content.y + 14, "SELECTED", kAccent);
    canvas.text(12, content.y + 34, truncate(state.selected_name, 34U), kText);
    canvas.text(12, content.y + 50, truncate(state.selected_status, 34U), kMuted);
    canvas.fill_rect({12, content.y + 76, 296, 24}, kPanelRaised);
    canvas.text(18, content.y + 85, "TOUCH A ROW FOR DETAILS", kText);
  }

  if (!state.notice.empty()) {
    const RectI notice_area{8, content.bottom() - 16, 304, 14};
    canvas.fill_rect(notice_area, state.notice_is_error ? kDanger : kPanelRaised);
    canvas.text(12, notice_area.y + 4, truncate(state.notice, 48U), kText);
  }

  static const std::array<const char*, 4> footer{
      "PAUSE", "SPEED", "MAP", "BACK"};
  for (int i = 0; i < 4; ++i) {
    const RectI rect = ScreenLayout::action_rect(i);
    canvas.fill_rect(rect, i == 0 && state.paused ? kDanger : kPanelRaised);
    canvas.stroke_rect(rect, kBackground);
    std::string label = footer[static_cast<std::size_t>(i)];
    if (i == 1) {
      label += " " + std::to_string(state.game_speed);
    }
    canvas.text_centered(rect, label, kText);
  }
}

void render_top_placeholder(SoftwareCanvas& canvas, const BottomUiState& state,
                            Vec2f camera_offset, float zoom) {
  canvas.clear({24, 34, 40, 255});
  canvas.fill_rect({0, 0, canvas.width(), canvas.height()}, kWorldFloor);

  const int tile_w = std::max(12, static_cast<int>(32.0F * zoom));
  const int tile_h = std::max(6, static_cast<int>(16.0F * zoom));
  const int origin_x = canvas.width() / 2 + static_cast<int>(camera_offset.x);
  const int origin_y = 14 + static_cast<int>(camera_offset.y);
  for (int row = 0; row < 12; ++row) {
    for (int column = 0; column < 12; ++column) {
      const int x = origin_x + (column - row) * tile_w / 2;
      const int y = origin_y + (column + row) * tile_h / 2;
      canvas.line({x, y}, {x + tile_w / 2, y + tile_h / 2}, kGrid);
      canvas.line({x + tile_w / 2, y + tile_h / 2}, {x, y + tile_h}, kGrid);
      canvas.line({x, y + tile_h}, {x - tile_w / 2, y + tile_h / 2}, kGrid);
      canvas.line({x - tile_w / 2, y + tile_h / 2}, {x, y}, kGrid);
    }
  }

  canvas.fill_rect({120, 80, 92, 54}, kWorldRoom);
  canvas.stroke_rect({120, 80, 92, 54}, kWorldWall, 3);
  canvas.fill_rect({230, 112, 72, 42}, {175, 137, 110, 255});
  canvas.stroke_rect({230, 112, 72, 42}, kWorldWall, 3);
  for (int i = 0; i < 12; ++i) {
    const int x = 80 + (i * 29) % 260;
    const int y = 68 + (i * 17) % 130;
    canvas.fill_rect({x, y, 5, 9}, i % 2 == 0 ? kAccent : kDanger);
  }

  canvas.fill_rect({0, 0, canvas.width(), 18}, {18, 25, 32, 230});
  canvas.text(5, 6, "CORSIXTH 3DS SIM", kText);
  canvas.text(192, 6, "$" + std::to_string(state.cash), kText);
  canvas.text(322, 6, state.paused ? "PAUSED" : "RUN", state.paused ? kDanger : kText);
}

}  // namespace cth3ds
