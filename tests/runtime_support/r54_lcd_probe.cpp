#include "cth3ds/gpu_diagnostics.hpp"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
int main(){
  using namespace cth3ds;
  std::uint64_t checked=0;
  for(unsigned w:{320U,400U})for(unsigned fmt=0;fmt<5;++fmt){
    const unsigned bpp=fmt==0?4:fmt==1?3:2;
    std::vector<std::uint8_t> bytes(w*240*bpp);
    // Independent sequential hardware-buffer encoder, not the production offset.
    auto* out=bytes.data();
    for(unsigned x=0;x<w;++x)for(int y=239;y>=0;--y){
      const unsigned r=(x%3)==0?255:0,g=(unsigned(y)%3)==1?255:0,b=((x+unsigned(y))%5)==0?255:0;
      if(fmt==0){*out++=255;*out++=b;*out++=g;*out++=r;}
      else if(fmt==1){*out++=b;*out++=g;*out++=r;}
      else{
        unsigned v=fmt==2?((r>>3)<<11)|((g>>2)<<5)|(b>>3):
          fmt==3?((r>>3)<<11)|((g>>3)<<6)|((b>>3)<<1)|1:
                 ((r>>4)<<12)|((g>>4)<<8)|((b>>4)<<4)|15;
        *out++=v;*out++=v>>8;
      }
    }
    for(unsigned y=0;y<240;++y)for(unsigned x=0;x<w;++x){
      const unsigned r=x%3==0?255:0,g=y%3==1?255:0,b=(x+y)%5==0?255:0;
      std::uint32_t rgb{};assert(gpu_lcd_rgb(bytes.data(),bytes.size(),fmt,w,240,x,y,rgb));
      assert(rgb==(r|(g<<8)|(b<<16)));++checked;
    }
    std::uint32_t ignored=0;
    assert(!gpu_lcd_rgb(bytes.data(),bytes.size(),fmt,w,240,w,0,ignored));
    assert(!gpu_lcd_rgb(bytes.data(),bytes.size(),fmt,w,240,0,240,ignored));
    assert(!gpu_lcd_rgb(bytes.data(),bytes.size()-1,fmt,w,240,w-1,0,ignored));
    assert(!gpu_lcd_rgb(nullptr,bytes.size(),fmt,w,240,0,0,ignored));
    assert(!gpu_lcd_rgb(bytes.data(),bytes.size(),99,w,240,0,0,ignored));
    assert(!gpu_lcd_rgb(bytes.data(),bytes.size(),fmt,0,240,0,0,ignored));
  }
  std::printf("PASS independent LCD decoder: pixel_checks=%llu formats=5 screens=2 bounds=covered\n",(unsigned long long)checked);
}
