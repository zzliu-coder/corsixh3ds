#pragma once

#include <SDL.h>
#include "cth3ds/events.hpp"

namespace cth3ds {

// Owns only the viewing rectangle, never the game canvas, windows or cursor.
// App.ui supplies the authoritative pointer at each input/present boundary.
// Runtime retains SDL locking/submission, notices, clocks and lifecycle order.
class GameView {
 public:
  void reset_canvas(int width, int height) noexcept;
  void focus(int x, int y) noexcept;
  void inspect(int x, int y, Vec2i pointer) noexcept;
  // Return whether changing context/size needs a redraw.
  bool set_context(InputContext context) noexcept;
  bool toggle() noexcept;
  // Return only displacement left after clamping; menus never pan the map.
  Vec2f move(Vec2f delta, Vec2i pointer) noexcept;
  void follow(Vec2i pointer) noexcept;
  [[nodiscard]] bool activation_needs_focus(ActionType action, Vec2i pointer) const noexcept;
  [[nodiscard]] RectI bounds() const noexcept { return bounds_; }
  [[nodiscard]] InputContext context() const noexcept { return context_; }

  static bool valid_output(const SDL_Surface* source, const SDL_Surface* output,
                           int width, int height) noexcept;
  // Caller validates and locks the borrowed surfaces. Neither function allocates.
  bool copy_top(const SDL_Surface* source, SDL_Surface* output) const noexcept;
  bool copy_bottom(const SDL_Surface* source, SDL_Surface* output) const noexcept;

 private:
  RectI bounds_{120, 120, 400, 240};
  Vec2f remainder_{};
  Vec2i previous_pointer_{};
  InputContext context_{InputContext::World};
  bool wide_{false}, map_context_{false}, detail_wide_{false}, initialized_{false};
};

}  // namespace cth3ds
