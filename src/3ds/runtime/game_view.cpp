#include "game_view.hpp"

#include <algorithm>
#include "cth3ds/framebuffer_scaler.hpp"

namespace cth3ds {

void GameView::reset_canvas(int width, int height) noexcept {
  initialized_ = false;
  if (width > 0 && height > 0) {
    bounds_.x = (width - 400) / 2;
    bounds_.y = (height - 240) / 2;
  }
}

void GameView::focus(int x, int y) noexcept {
  bounds_.x = std::clamp(x - bounds_.w / 2, 0, 640 - bounds_.w);
  bounds_.y = std::clamp(y - bounds_.h / 2, 0, 480 - bounds_.h);
  initialized_ = false;
}

bool GameView::set_context(InputContext context) noexcept {
  if (context != context_) {
    context_ = context;
    detail_wide_ = false;  // newly entered dialogs start readable
  }
  map_context_ = context == InputContext::World || context == InputContext::BuildRoom ||
                 context == InputContext::PlaceObject;
  const bool wide = map_context_ ? wide_ : detail_wide_;
  const int width = wide ? 480 : 400;
  const int height = wide ? 288 : 240;
  if (width == bounds_.w) return false;
  const int x = bounds_.x + bounds_.w / 2, y = bounds_.y + bounds_.h / 2;
  bounds_.w = width;
  bounds_.h = height;
  focus(x, y);
  return true;
}

bool GameView::toggle() noexcept {
  if (map_context_) wide_ = !wide_;
  else detail_wide_ = !detail_wide_;
  return set_context(context_);
}

void GameView::move(Vec2f delta, Vec2i pointer) noexcept {
  remainder_.x += delta.x;
  remainder_.y += delta.y;
  const int x = static_cast<int>(remainder_.x), y = static_cast<int>(remainder_.y);
  remainder_.x -= static_cast<float>(x);
  remainder_.y -= static_cast<float>(y);
  bounds_.x = std::clamp(bounds_.x + x, 0, 640 - bounds_.w);
  bounds_.y = std::clamp(bounds_.y + y, 0, 480 - bounds_.h);
  previous_pointer_ = pointer;
  initialized_ = true;
}

void GameView::follow(Vec2i pointer) noexcept {
  if (!initialized_ || pointer.x != previous_pointer_.x || pointer.y != previous_pointer_.y) {
    const auto origin = follow_pointer_viewport({bounds_.x, bounds_.y}, pointer,
                                               640, 480, bounds_.w, bounds_.h);
    bounds_.x = origin.x;
    bounds_.y = origin.y;
  }
  previous_pointer_ = pointer;
  initialized_ = true;
}

bool GameView::activation_needs_focus(ActionType action, Vec2i pointer) const noexcept {
  const bool activates = action == ActionType::Confirm || action == ActionType::PlaceItem ||
                         action == ActionType::RotateObject || action == ActionType::ShowDetails;
  return activates && (pointer.x < bounds_.x || pointer.y < bounds_.y ||
                       pointer.x >= bounds_.x + bounds_.w || pointer.y >= bounds_.y + bounds_.h);
}

bool GameView::valid_output(const SDL_Surface* source, const SDL_Surface* output,
                            int width, int height) noexcept {
  if (!source || !source->pixels || !source->format || source->w != 640 || source->h != 480 ||
      source->pitch < 640 * 4 || source->pitch % 4 != 0 ||
      !output || !output->pixels || !output->format || output->w != width || output->h != height ||
      output->pitch < width * 4 || output->pitch % 4 != 0) return false;
  const auto src = source->format->format, dst = output->format->format;
  return (src == SDL_PIXELFORMAT_ABGR8888 || src == SDL_PIXELFORMAT_RGBA8888) &&
         (dst == SDL_PIXELFORMAT_ABGR8888 || dst == SDL_PIXELFORMAT_RGBA8888);
}

bool GameView::copy_top(const SDL_Surface* source, SDL_Surface* output) const noexcept {
  return scale_rgba_view(static_cast<const std::uint32_t*>(source->pixels),
      640, 480, source->pitch / 4, bounds_,
      static_cast<std::uint32_t*>(output->pixels), 400, 240, output->pitch / 4,
      source->format->format != output->format->format);
}

bool GameView::copy_bottom(const SDL_Surface* source, SDL_Surface* output) const noexcept {
  if (!halve_rgba(static_cast<const std::uint32_t*>(source->pixels), source->w,
                  source->h, source->pitch / 4, static_cast<std::uint32_t*>(output->pixels),
                  output->pitch / 4, source->format->format != output->format->format)) return false;
  auto* pixels = static_cast<std::uint32_t*>(output->pixels);
  const int pitch = output->pitch / 4;
  const int x = bounds_.x / 2, y = bounds_.y / 2;
  const auto color = SDL_MapRGBA(output->format, 255, 255, 255, 255);
  const int width = bounds_.w / 2, height = bounds_.h / 2;
  for (int dx = 0; dx < width; ++dx) {
    pixels[y * pitch + x + dx] = color;
    pixels[(y + height - 1) * pitch + x + dx] = color;
  }
  for (int dy = 0; dy < height; ++dy) {
    pixels[(y + dy) * pitch + x] = color;
    pixels[(y + dy) * pitch + x + width - 1] = color;
  }
  return true;
}

}  // namespace cth3ds
