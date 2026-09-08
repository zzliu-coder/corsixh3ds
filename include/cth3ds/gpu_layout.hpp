#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>

namespace cth3ds {
// Pure, host-tested storage geometry. Pages use shelf allocation aligned to
// 8x8 PICA tiles; image entries carry a generation, never a dangling page lease.
struct GpuShelf {
  int x{}, y{}, row{};
  bool allocate(int w,int h,int& ox,int& oy) noexcept {
    w=(w+7)&~7; h=(h+7)&~7;
    if(w<=0||h<=0||w>512||h>512)return false;
    int nx=x,ny=y,nr=row;
    if(nx+w>512){nx=0;ny+=nr;nr=0;}
    if(ny+h>512)return false;
    ox=nx;oy=ny;x=nx+w;y=ny;row=std::max(nr,h);return true;
  }
};
// R62: a bounded 64-column skyline fills holes left by mixed-height sprites.
// Each occupied column is tile-aligned; appends never touch a queued tile.
struct GpuSkyline {
  std::uint8_t heights[64]{};
  bool allocate(int w,int h,int& ox,int& oy) noexcept {
    if(w<=0||h<=0||w>512||h>512)return false;
    const int columns=(w+7)/8, rows=(h+7)/8;
    int best=-1, best_y=65, best_waste=4097;
    for(int x=0;x+columns<=64;++x){
      int y=0,sum=0;
      for(int n=0;n<columns;++n){y=std::max(y,int(heights[x+n]));sum+=heights[x+n];}
      const int waste=y*columns-sum;
      if(y+rows<=64 && (y<best_y || (y==best_y && waste<best_waste))){
        best=x;best_y=y;best_waste=waste;
      }
    }
    if(best<0)return false;
    for(int n=0;n<columns;++n)heights[best+n]=static_cast<std::uint8_t>(best_y+rows);
    ox=best*8;oy=best_y*8;return true;
  }
};
inline std::size_t gpu_tile_offset(unsigned x,unsigned y,unsigned width) noexcept {
  const unsigned ix=x&7U,iy=y&7U;
  const unsigned morton=(ix&1U)|((iy&1U)<<1U)|((ix&2U)<<1U)|
    ((iy&2U)<<2U)|((ix&4U)<<2U)|((iy&4U)<<3U);
  return ((y>>3U)*(width>>3U)+(x>>3U))*64U+morton;
}
inline std::uint32_t gpu_pixel(std::uint32_t abgr) noexcept {
  // SDL ABGR8888 numeric AABBGGRR -> PICA RGBA8 numeric RRGGBBAA.
  return ((abgr&255U)<<24U)|((abgr&0xff00U)<<8U)|
    ((abgr&0xff0000U)>>8U)|(abgr>>24U);
}
inline void gpu_upload_rgba(std::uint32_t* output,unsigned texture_width,
                           unsigned x,unsigned y,const std::uint32_t* source,
                           unsigned stride,unsigned width,unsigned height) noexcept {
  // tex3ds/PICA texture storage: source top row is memory row zero; UV top=1.
  // The C2D offscreen canvas also maps logical row y to memory row y.
  // GPU scissor and LCD column storage have separate coordinate conventions.
  for(unsigned row=0;row<height;++row)for(unsigned col=0;col<width;++col)
    output[gpu_tile_offset(x+col,y+row,texture_width)]=gpu_pixel(source[row*stride+col]);
}
} // namespace cth3ds
