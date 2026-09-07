#pragma once
#include <cstddef>
#include <cstdint>

namespace cth3ds {
// R54 read-only LCD-buffer decoder. This does not share the texture uploader's
// Morton addressing or its byte-swap helper. Format numbers follow libctru's
// GSP framebuffer enum. The saved pointer is captured BEFORE FrameEnd swaps it.
inline unsigned gpu_lcd_pixel_size(unsigned format) noexcept {
  return format==0?4U:format==1?3U:format<=4?2U:0U;
}
inline bool gpu_lcd_rgb(const std::uint8_t* data,std::size_t size,unsigned format,
                        unsigned logical_width,unsigned logical_height,
                        unsigned x,unsigned y,std::uint32_t& rgb) noexcept {
  const unsigned bytes=gpu_lcd_pixel_size(format);
  if(!data||!bytes||!logical_width||!logical_height||x>=logical_width||y>=logical_height)return false;
  const std::size_t pixel=static_cast<std::size_t>(x)*logical_height+(logical_height-1U-y);
  if(pixel>=size/bytes)return false;
  const auto* p=data+pixel*bytes;
  std::uint32_t r{},g{},b{};
  if(format==0){r=p[3];g=p[2];b=p[1];}
  else if(format==1){r=p[2];g=p[1];b=p[0];}
  else {
    const std::uint32_t value=static_cast<std::uint32_t>(p[0])|(static_cast<std::uint32_t>(p[1])<<8U);
    const auto five=[](std::uint32_t v){return (v<<3U)|(v>>2U);};
    if(format==2){r=five((value>>11U)&31U);const auto q=(value>>5U)&63U;g=(q<<2U)|(q>>4U);b=five(value&31U);}
    else if(format==3){r=five((value>>11U)&31U);g=five((value>>6U)&31U);b=five((value>>1U)&31U);}
    else {r=((value>>12U)&15U)*17U;g=((value>>8U)&15U)*17U;b=((value>>4U)&15U)*17U;}
  }
  rgb=r|(g<<8U)|(b<<16U);return true;
}
// Saturated, flat regions avoid nearest-neighbour ties and 16-bit quantisation.
// This reference describes the drawn scene, not a copy of UV/readback formulae.
inline std::uint32_t gpu_diagnostic_scene(unsigned x,unsigned y) noexcept {
  if(x>=640U||y>=480U)return 0xff000000U;
  if(x<320U)return y<240U?0xff0000ffU:0xffff0000U;
  return y<240U?0xff00ff00U:0xff00ffffU;
}
} // namespace cth3ds
