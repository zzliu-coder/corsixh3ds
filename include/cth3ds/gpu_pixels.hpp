#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include "cth3ds/gpu_layout.hpp"

namespace cth3ds {
// Source blocks stay below 64 KiB RGBA / 16 KiB indexed. No full-screen
// allocation is needed by the indexed background path.
inline constexpr int gpu_source_extent=128;
// Image-owned prepared pixels: full 8x8 tiles in PICA order, followed by
// compact edge tiles. Storage is exactly w*h*4, even for a 1x1 glyph.
// Preparation replaces the old RGBA copy; it never adds a second image.
inline constexpr unsigned gpu_morton_x(unsigned n) noexcept {
  return (n&1U)|((n>>1U)&2U)|((n>>2U)&4U);
}
inline constexpr unsigned gpu_morton_y(unsigned n) noexcept {
  return ((n>>1U)&1U)|((n>>2U)&2U)|((n>>3U)&4U);
}
inline void gpu_prepare_pixels(std::uint32_t* output,const std::uint32_t* source,
                               unsigned stride,unsigned width,unsigned height) noexcept {
  for(unsigned y=0;y<height;y+=8)for(unsigned x=0;x<width;x+=8) {
    const unsigned w=std::min(8U,width-x),h=std::min(8U,height-y);
    for(unsigned n=0;n<64;++n) {
      const auto tx=gpu_morton_x(n),ty=gpu_morton_y(n);
      if(tx<w&&ty<h)*output++=gpu_pixel(source[(y+ty)*stride+x+tx]);
    }
  }
}
inline void gpu_upload_prepared(std::uint32_t* output,unsigned texture_width,
                                unsigned x,unsigned y,const std::uint32_t* source,
                                unsigned width,unsigned height) noexcept {
  // Page allocator guarantees 8-pixel alignment, hence disjoint destination
  // tiles while earlier draws are queued. Eviction still requires completion.
  for(unsigned row=0;row<height;row+=8)for(unsigned col=0;col<width;col+=8) {
    auto* tile=output+gpu_tile_offset(x+col,y+row,texture_width);
    const auto w=std::min(8U,width-col),h=std::min(8U,height-row);
    if(w==8&&h==8){std::memcpy(tile,source,64*sizeof(*source));source+=64;}
    else for(unsigned n=0;n<64;++n)
      if(gpu_morton_x(n)<w&&gpu_morton_y(n)<h)tile[n]=*source++;
  }
}
inline void gpu_prepare_indices(std::uint8_t* output,const std::uint8_t* source,
                                unsigned image_width,unsigned image_height,
                                unsigned sx,unsigned sy,unsigned width,unsigned height,
                                bool flip_x=false,bool flip_y=false) noexcept {
  for(unsigned y=0;y<height;y+=8)for(unsigned x=0;x<width;x+=8){
    const unsigned w=std::min(8U,width-x),h=std::min(8U,height-y);
    for(unsigned n=0;n<64;++n){
      const auto tx=gpu_morton_x(n),ty=gpu_morton_y(n);
      if(tx<w&&ty<h){
        const unsigned px=sx+x+tx,py=sy+y+ty;
        *output++=source[(flip_y?image_height-1-py:py)*image_width+
                         (flip_x?image_width-1-px:px)];
      }
    }
  }
}
inline void gpu_upload_indices(std::uint32_t* output,unsigned texture_width,
                               unsigned x,unsigned y,const std::uint8_t* source,
                               unsigned width,unsigned height,const std::uint32_t* palette) noexcept {
  // palette is already in PICA colour order. All source alpha values survive.
  for(unsigned row=0;row<height;row+=8)for(unsigned col=0;col<width;col+=8){
    auto* tile=output+gpu_tile_offset(x+col,y+row,texture_width);
    const auto w=std::min(8U,width-col),h=std::min(8U,height-row);
    if(w==8&&h==8)for(unsigned n=0;n<64;++n)tile[n]=palette[*source++];
    else for(unsigned n=0;n<64;++n)
      if(gpu_morton_x(n)<w&&gpu_morton_y(n)<h)tile[n]=palette[*source++];
  }
}
} // namespace cth3ds
