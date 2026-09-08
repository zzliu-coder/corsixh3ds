#define CORSIXTH_3DS 1
#include <SDL.h>
#include <ft2build.h>
#include FT_FREETYPE_H
#include FT_ERRORS_H
#include FT_GLYPH_H
#include FT_IMAGE_H
#include FT_TYPES_H
#include <algorithm>
#include <cassert>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include "cth3ds/memory_telemetry.hpp"
namespace cth3ds { template<class... T> void runtime_observe_memory(T...) {} }
using argb_colour = uint32_t;
// Only the canvas/bitmap-sprite seams are supplied. FreeType lifetime, UTF-8,
// layout, cache, rasterization, SDL texture creation and drawing are real.
class sprite_sheet {
 public:
  bool get_sprite_size(size_t,int*,int*) { return false; }
  bool get_sprite_average_colour(size_t,argb_colour*) { return false; }
  size_t get_sprite_count() { return 0; }
  void get_sprite_size_unchecked(size_t,int*,int*) {}
};
struct render_target {
  SDL_Renderer* renderer;
  SDL_Texture* create_texture(int w,int h,const uint32_t* pixels) const {
    auto* texture=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ARGB8888,SDL_TEXTUREACCESS_STATIC,w,h);
    assert(texture);assert(SDL_UpdateTexture(texture,nullptr,pixels,w*4)==0);
    SDL_SetTextureBlendMode(texture,SDL_BLENDMODE_BLEND);return texture;
  }
  void draw(SDL_Texture* texture,const SDL_Rect* from,const SDL_Rect* to,int) {
    assert(SDL_RenderCopy(renderer,texture,from,to)==0);
  }
};
// INSERT_HEADER
// INSERT_STRINGS_HEADER
// INSERT_STRINGS
// INSERT_FONT
// INSERT_BACKEND

int main(int argc,char** argv) {
  assert(argc==2);
  std::ifstream file(argv[1],std::ios::binary);
  std::vector<uint8_t> data((std::istreambuf_iterator<char>(file)),{});
  assert(!data.empty());
  assert(SDL_Init(0)==0);
  auto* surface=SDL_CreateRGBSurfaceWithFormat(0,640,480,32,SDL_PIXELFORMAT_ARGB8888);
  auto* renderer=SDL_CreateSoftwareRenderer(surface);assert(renderer);
  render_target target{renderer};
  std::vector<std::unique_ptr<freetype_font>> fonts;
  for(int i=0;i<12;++i) {
    auto font=std::make_unique<freetype_font>();
    assert(font->set_face(data.data(),data.size())==0);
    assert(font->set_ideal_character_size(14,18)==0);
    font->set_font_color(0xffffffff);
    fonts.push_back(std::move(font));
  }
  // The first face formerly released the shared library under later faces.
  fonts.erase(fonts.begin());
  const std::string message=u8"主题医院 医生 护士 保存 123 English//患者就诊与音乐";
  for(int i=0;i<180;++i) {
    auto& font=*fonts[i%fonts.size()];
    auto text=message+std::to_string(i);
    const auto a=font.draw_text_wrapped(&target,text.c_str(),text.size(),0,0,320,6,0);
    const auto b=font.draw_text_wrapped(&target,text.c_str(),text.size(),0,0,320,6,0);
    assert(a.width==b.width&&a.end_y==b.end_y&&a.row_count==b.row_count);
    assert(a.width>0&&a.end_y>0);
    assert(cth3ds::text_cache.bytes<=cth3ds::TextCacheBudget::limit);
  }
  assert(cth3ds::text_cache.evictions>0);
  auto pixel_count=640*480;bool visible=false;
  for(int i=0;i<pixel_count;++i)visible|=(static_cast<uint32_t*>(surface->pixels)[i]&0xffffff)!=0;
  assert(visible);
  for(auto& font:fonts)font->clear_cache();
  assert(cth3ds::text_cache.bytes==0);
  std::string large;
  for(int i=0;i<100;++i)large+=message;
  auto oversize_before=cth3ds::text_cache.oversize;
  const auto measured=fonts.back()->get_text_dimensions(large.c_str(),large.size(),320);
  assert(measured.width>0&&measured.row_count>0);
  assert(cth3ds::text_cache.oversize>oversize_before&&cth3ds::text_cache.bytes==0);
  fonts.back()->draw_text(&target,message.c_str(),message.size(),0,0);
  fonts.clear();assert(cth3ds::text_cache.bytes==0);
  // A new independent lifetime is valid after the last old face is destroyed.
  {freetype_font font;assert(font.set_face(data.data(),data.size())==0);
   assert(font.set_ideal_character_size(14,18)==0);
   assert(font.get_text_dimensions(message.c_str(),message.size(),320).width>0);}
  assert(cth3ds::text_cache.bytes==0);
  SDL_DestroyRenderer(renderer);SDL_FreeSurface(surface);SDL_Quit();
  std::cout<<"PASS real FreeType UTF8 SDL pixels, 12 owners, cache eviction and release\n";
}
