#pragma once

#include <cstddef>
#include <cstdint>

using Uint8 = std::uint8_t;
using Uint16 = std::uint16_t;
using Uint32 = std::uint32_t;
using Uint64 = std::uint64_t;

struct SDL_Window {};
struct SDL_PixelFormat { Uint32 format; };
struct SDL_Surface {
  Uint32 flags;
  SDL_PixelFormat* format;
  int w;
  int h;
  int pitch;
  void* pixels;
};

struct SDL_MouseMotionEvent {
  Uint32 type; Uint32 timestamp; Uint32 windowID; Uint32 which;
  Uint32 state; int x; int y; int xrel; int yrel;
};
struct SDL_MouseButtonEvent {
  Uint32 type; Uint32 timestamp; Uint32 windowID; Uint32 which;
  Uint8 button; Uint8 state; Uint8 clicks; Uint8 padding1; int x; int y;
};
struct SDL_MouseWheelEvent { Uint32 type; Uint32 timestamp; Uint32 windowID; };
struct SDL_TouchFingerEvent { Uint32 type; Uint32 timestamp; Uint32 touchId; Uint32 fingerId; float x; float y; float dx; float dy; float pressure; Uint32 windowID; };
struct SDL_WindowEvent { Uint32 type; Uint32 timestamp; Uint32 windowID; Uint8 event; };
union SDL_Event {
  Uint32 type;
  SDL_MouseMotionEvent motion;
  SDL_MouseButtonEvent button;
  SDL_MouseWheelEvent wheel;
  SDL_TouchFingerEvent tfinger;
  SDL_WindowEvent window;
};

constexpr Uint32 SDL_WINDOW_SHOWN = 1U << 0U;
constexpr Uint32 SDL_WINDOW_FULLSCREEN = 1U << 1U;
constexpr Uint32 SDL_MOUSEMOTION = 0x400U;
constexpr Uint32 SDL_MOUSEBUTTONDOWN = 0x401U;
constexpr Uint32 SDL_MOUSEBUTTONUP = 0x402U;
constexpr Uint32 SDL_MOUSEWHEEL = 0x403U;
constexpr Uint32 SDL_FINGERDOWN = 0x700U;
constexpr Uint32 SDL_FINGERUP = 0x701U;
constexpr Uint32 SDL_FINGERMOTION = 0x702U;
constexpr Uint32 SDL_WINDOWEVENT = 0x200U;
constexpr Uint32 SDL_QUIT = 0x100U;
constexpr Uint32 SDL_PIXELFORMAT_RGBA32 = 0x16462004U;
constexpr Uint32 SDL_PIXELFORMAT_RGBA8888 = 0x16462004U;
constexpr Uint8 SDL_BUTTON_LEFT = 1U;
constexpr Uint8 SDL_BUTTON_RIGHT = 3U;
constexpr Uint8 SDL_PRESSED = 1U;
constexpr Uint8 SDL_RELEASED = 0U;
#define SDL_HINT_TOUCH_MOUSE_EVENTS "SDL_TOUCH_MOUSE_EVENTS"

#define SDL_WINDOWPOS_CENTERED_DISPLAY(display) (0x2FFF0000U | static_cast<Uint32>(display))
#define SDL_MUSTLOCK(surface) ((surface)->flags & 1U)

inline SDL_Window* SDL_CreateWindow(const char*, int, int, int, int, Uint32) {
  static SDL_Window window;
  return &window;
}
inline void SDL_DestroyWindow(SDL_Window*) {}
inline Uint32 SDL_GetWindowID(SDL_Window*) { return 2U; }
inline SDL_Surface* SDL_GetWindowSurface(SDL_Window*) {
  static SDL_PixelFormat format{SDL_PIXELFORMAT_RGBA32};
  static std::uint8_t pixels[320U * 240U * 4U]{};
  static SDL_Surface surface{0U, &format, 320, 240, 320 * 4, pixels};
  return &surface;
}
inline int SDL_LockSurface(SDL_Surface*) { return 0; }
inline void SDL_UnlockSurface(SDL_Surface*) {}
inline int SDL_ConvertPixels(int, int, Uint32, const void*, int, Uint32, void*, int) { return 0; }
inline Uint32 SDL_MapRGBA(SDL_PixelFormat*, Uint8 r, Uint8 g, Uint8 b, Uint8 a) {
  return (static_cast<Uint32>(r) << 24U) | (static_cast<Uint32>(g) << 16U) |
         (static_cast<Uint32>(b) << 8U) | static_cast<Uint32>(a);
}
inline int SDL_FillRect(SDL_Surface*, const void*, Uint32) { return 0; }
inline int SDL_UpdateWindowSurface(SDL_Window*) { return 0; }
inline const char* SDL_GetError() { return "stub"; }
inline Uint64 SDL_GetPerformanceFrequency() { return 1000000U; }
inline Uint64 SDL_GetPerformanceCounter() { static Uint64 counter = 0; return counter += 16666U; }
inline Uint32 SDL_GetTicks() { return 1U; }
inline int SDL_PushEvent(SDL_Event*) { return 1; }
inline void SDL_SetHint(const char*, const char*) {}
