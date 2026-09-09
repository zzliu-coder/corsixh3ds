#pragma once
#include <SDL.h>
#include <cstdint>
#include "cth3ds/events.hpp"

namespace cth3ds {
#ifdef CORSIXTH_3DS_GPU
// SDL owns gfxInit/gfxExit. This single owner owns only C3D/C2D and GPU data.
bool gpu_initialize() noexcept;
bool gpu_active() noexcept;
void gpu_shutdown() noexcept;
void gpu_quiesce() noexcept;
bool gpu_begin() noexcept;
bool gpu_clear(std::uint32_t colour) noexcept;
bool gpu_fill(const SDL_Rect*,std::uint32_t colour) noexcept;
bool gpu_line(int,int,int,int,std::uint32_t colour) noexcept;
void gpu_clip(const SDL_Rect*) noexcept;
SDL_Texture* gpu_image_create(SDL_Renderer*,int,int,const std::uint32_t*) noexcept;
SDL_Texture* gpu_image_create_indexed(SDL_Renderer*,int,int,const std::uint8_t*,
                                    const std::uint32_t*,bool,bool) noexcept;
void gpu_image_destroy(SDL_Texture*) noexcept;
void gpu_images_release(SDL_Renderer*) noexcept;
int gpu_image_draw(SDL_Texture*,const SDL_Rect*,const SDL_FRect*,SDL_RendererFlip) noexcept;
bool gpu_top(RectI view) noexcept;
bool gpu_bottom(RectI view,const std::uint32_t* rgba,int overlay_height) noexcept;
bool gpu_read_pixels(SDL_Surface*) noexcept;
void gpu_log_statistics() noexcept;
void gpu_submit_sample_begin(std::uint64_t boundary_us) noexcept;
void gpu_submit_sample_end(std::uint64_t boundary_us,bool eligible) noexcept;
void gpu_submit_sample_log() noexcept;
void gpu_submit_bridge_begin() noexcept;
void gpu_submit_bridge_end() noexcept;
void gpu_submit_floor_begin() noexcept;
void gpu_submit_floor_end() noexcept;
struct GpuSubmitBridgeScope {
  GpuSubmitBridgeScope() noexcept {gpu_submit_bridge_begin();}
  ~GpuSubmitBridgeScope() {gpu_submit_bridge_end();}
};
struct GpuSubmitFloorScope {
  GpuSubmitFloorScope() noexcept {gpu_submit_floor_begin();}
  ~GpuSubmitFloorScope() {gpu_submit_floor_end();}
};
#endif
} // namespace cth3ds
