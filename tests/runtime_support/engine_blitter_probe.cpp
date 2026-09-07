// Generated production create/scale/draw bodies, actual SDL2 software renderer.
#include "cth3ds/sdl_blitter.hpp"
#include <cassert>
#include <chrono>
#include <cstdio>
#include <memory>
#include <stdexcept>
#include <vector>
#define CORSIXTH_3DS 1
#define SDL_DestroyTexture cth3ds::blit_destroy
namespace cth3ds {
enum class MemoryGate{Operation};
template<class... T> void runtime_observe_memory(T...) {}
}
constexpr int thdf_flip_horizontal=1,thdf_flip_vertical=2,thdf_alpha_50=4,thdf_alpha_75=8;
const float frect_overdraw=.01F;
struct render_target {
  SDL_Renderer* renderer;SDL_Surface* game_surface;
  struct Scope {void offset(SDL_FRect&) {}};
  Scope* current_target=nullptr;
  double draw_scale(){return 1;}
  SDL_Texture* create_texture(int,int,const std::uint32_t*) const;
  void draw(SDL_Texture*,const SDL_Rect*,const SDL_Rect*,int);
  void reference_draw(SDL_Texture*,const SDL_Rect*,const SDL_Rect*,int);
};
// INSERT_SCALE
// INSERT_CREATE
// INSERT_DRAW
#undef CORSIXTH_3DS
// INSERT_REFERENCE_DRAW
#undef SDL_DestroyTexture

int main() {
  auto* a=SDL_CreateRGBSurfaceWithFormat(0,640,480,32,SDL_PIXELFORMAT_ABGR8888);
  auto* b=SDL_CreateRGBSurfaceWithFormat(0,640,480,32,SDL_PIXELFORMAT_ABGR8888);
  assert(a && b);auto* ra=SDL_CreateSoftwareRenderer(a);auto* rb=SDL_CreateSoftwareRenderer(b);
  assert(ra && rb);render_target target{ra,a},reference_target{rb,b};
  for(int pattern=0;pattern<2;++pattern) {
    std::vector<Uint32> p(64*64);
    for(int y=0;y<64;++y)for(int x=0;x<64;++x)
      p[y*64+x]=(pattern==0 || (x>25 && x<39 && y>5 && y<60))?0xff4271a3U:0;
    auto* fast=target.create_texture(64,64,p.data());assert(fast);
    auto* ref=SDL_CreateTexture(rb,SDL_PIXELFORMAT_ABGR8888,SDL_TEXTUREACCESS_STATIC,64,64);assert(ref);
    assert(SDL_UpdateTexture(ref,nullptr,p.data(),64*4)==0);
    assert(SDL_SetTextureBlendMode(ref,SDL_BLENDMODE_BLEND)==0);
    for(auto* r:{ra,rb}) {SDL_SetRenderDrawColor(r,20,30,40,255);SDL_RenderClear(r);}
    for(int i=0;i<100;++i) {
      SDL_Rect dst{i*29%650-20,i*23%490-20,64,64};SDL_FRect scaled;
      getScaleRect(&dst,1,&scaled);
      target.draw(fast,nullptr,&dst,0);reference_target.reference_draw(ref,nullptr,&dst,0);
    }
    assert(SDL_RenderFlush(ra)==0 && SDL_RenderFlush(rb)==0);
    for(int i=0;i<640*480;++i)assert(static_cast<Uint32*>(a->pixels)[i]==static_cast<Uint32*>(b->pixels)[i]);
    // Advisory Mac microbenchmark; never a device FPS gate. Same draw rectangles
    // and pixels, warm resources. Reference submits each copy in SW mode.
    auto bench=[&](bool accelerated) {
      const auto begin=std::chrono::steady_clock::now();
      for(int i=0;i<10000;++i) {
        SDL_Rect dst{i*29%550,i*23%390,64,64};
        if(accelerated)target.draw(fast,nullptr,&dst,0);
        else reference_target.reference_draw(ref,nullptr,&dst,0);
      }
      assert(SDL_RenderFlush(accelerated?ra:rb)==0);
      return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-begin).count();
    };
    const auto reference=bench(false),accelerated=bench(true);
    std::printf("HOST_ONLY pattern=%d draws=10000 reference_us=%lld fast_us=%lld\n",pattern,(long long)reference,(long long)accelerated);
    cth3ds::blit_destroy(fast);SDL_DestroyTexture(ref);
  }
  assert(cth3ds::blit_counters.direct==20200 && cth3ds::blit_counters.fallback==0);
  assert(cth3ds::blit_counters.live_images==0 && cth3ds::blit_detail::images==nullptr);
  cth3ds::blit_calibrate(ra,a);
  assert(cth3ds::blit_counters.probe_ran && cth3ds::blit_counters.probe_pixels);
  assert(cth3ds::blit_counters.live_images==0 && cth3ds::blit_counters.live_bytes==0 && cth3ds::blit_counters.span_bytes==0);
  bool qualifies=true;
  for(int i=0;i<2;++i)qualifies=qualifies && cth3ds::blit_counters.probe_reference_us[i]>0 &&
    cth3ds::blit_counters.probe_fast_us[i]*100<=cth3ds::blit_counters.probe_reference_us[i]*90;
  assert(cth3ds::blit_counters.enabled==qualifies);
  cth3ds::blit_counters.reference_forced=true;cth3ds::blit_calibrate(ra,a);
  assert(!cth3ds::blit_counters.enabled);
  std::uint32_t pixel=0xffaabbcc;
  auto* native=cth3ds::blit_create(ra,1,1,&pixel);assert(native && !cth3ds::blit_detail::get(native));
  cth3ds::blit_destroy(native);
  SDL_DestroyRenderer(ra);SDL_DestroyRenderer(rb);SDL_FreeSurface(a);SDL_FreeSurface(b);
  std::puts("PASS generated engine create/scale/draw: pixel exact, fast path used, zero live images");
}
