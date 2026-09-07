#pragma once
#include "cth3ds/gpu_api.hpp"
#ifdef CORSIXTH_3DS_GPU
namespace cth3ds {
inline std::uint32_t gpu_draw_colour(SDL_Renderer* renderer) {
  Uint8 r{},g{},b{},a{};SDL_GetRenderDrawColor(renderer,&r,&g,&b,&a);
  SDL_BlendMode blend;SDL_GetRenderDrawBlendMode(renderer,&blend);
  if(blend==SDL_BLENDMODE_NONE)a=255;
  return r|(static_cast<std::uint32_t>(g)<<8U)|(static_cast<std::uint32_t>(b)<<16U)|
    (static_cast<std::uint32_t>(a)<<24U);
}
inline int gpu_sdl_clear(SDL_Renderer* renderer) {
  return gpu_active()?(gpu_clear(gpu_draw_colour(renderer))?0:-1):SDL_RenderClear(renderer);
}
inline int gpu_sdl_fill(SDL_Renderer* renderer,const SDL_Rect* rectangle) {
  return gpu_active()?(gpu_fill(rectangle,gpu_draw_colour(renderer))?0:-1):SDL_RenderFillRect(renderer,rectangle);
}
inline int gpu_sdl_line(SDL_Renderer* renderer,int x1,int y1,int x2,int y2) {
  return gpu_active()?(gpu_line(x1,y1,x2,y2,gpu_draw_colour(renderer))?0:-1):SDL_RenderDrawLine(renderer,x1,y1,x2,y2);
}
inline int gpu_sdl_clip(SDL_Renderer* renderer,const SDL_Rect* rectangle) {
  if(gpu_active())gpu_clip(rectangle);
  return SDL_RenderSetClipRect(renderer,rectangle);
}
inline int gpu_sdl_read(SDL_Renderer* renderer,const SDL_Rect* rectangle,Uint32 format,void* pixels,int pitch) {
  if(!gpu_active())return SDL_RenderReadPixels(renderer,rectangle,format,pixels,pitch);
  if(rectangle)return SDL_SetError("GPU screenshot requires complete canvas");
  auto* surface=SDL_CreateRGBSurfaceWithFormatFrom(pixels,640,480,SDL_BITSPERPIXEL(format),pitch,format);
  const bool ok=surface&&gpu_read_pixels(surface);SDL_FreeSurface(surface);return ok?0:-1;
}
} // namespace cth3ds
// All macros are private to th_gfx_sdl.cpp, after the real SDL declarations.
#define SDL_RenderClear cth3ds::gpu_sdl_clear
#define SDL_RenderFillRect cth3ds::gpu_sdl_fill
#define SDL_RenderDrawLine cth3ds::gpu_sdl_line
#define SDL_RenderSetClipRect cth3ds::gpu_sdl_clip
#define SDL_RenderReadPixels cth3ds::gpu_sdl_read
#endif
