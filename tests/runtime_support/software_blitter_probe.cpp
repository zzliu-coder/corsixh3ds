#include "cth3ds/sdl_blitter.hpp"
#include <cassert>
#include <cstdio>
#include <vector>
#include <chrono>

int main() {
  SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY,"nearest");
  auto* a=SDL_CreateRGBSurfaceWithFormat(0,128,96,32,SDL_PIXELFORMAT_ABGR8888);
  auto* b=SDL_CreateRGBSurfaceWithFormat(0,128,96,32,SDL_PIXELFORMAT_ABGR8888);
  assert(a && b);
  auto* ra=SDL_CreateSoftwareRenderer(a);auto* rb=SDL_CreateSoftwareRenderer(b);
  assert(ra && rb);
  std::vector<Uint32> source(64*64);
  unsigned cases=0;
  for(int pattern=0;pattern<3;++pattern) {
    for(int y=0;y<64;++y)for(int x=0;x<64;++x) {
      const auto alpha=pattern==0?255U:pattern==1?(x>25 && x<39 && y>5 && y<60?255U:0U):static_cast<Uint32>((x*3+y*2)%256);
      source[static_cast<std::size_t>(y*64+x)]=(alpha<<24U)|0x004271a3U;
    }
    for(unsigned flip=0;flip<4;++flip)for(int mod:{255,128,64})for(int clipping=0;clipping<3;++clipping)
    for(int scaled=0;scaled<2;++scaled)for(int colored=0;colored<2;++colored)
    for(int geometry=0;geometry<3;++geometry) {
      auto* fast=cth3ds::blit_create(ra,64,64,source.data());assert(fast);
      auto* ref=SDL_CreateTexture(rb,SDL_PIXELFORMAT_ABGR8888,SDL_TEXTUREACCESS_STATIC,64,64);assert(ref);
      assert(SDL_UpdateTexture(ref,nullptr,source.data(),64*4)==0);
      for(auto* t:{fast,ref}) {
        assert(SDL_SetTextureBlendMode(t,SDL_BLENDMODE_BLEND)==0);
        assert(SDL_SetTextureAlphaMod(t,static_cast<Uint8>(mod))==0);
        assert(SDL_SetTextureColorMod(t,static_cast<Uint8>(colored?0:255),static_cast<Uint8>(colored?200:255),255)==0);
      }
      const SDL_Rect clip=clipping==2?SDL_Rect{-20,-30,190,160}:SDL_Rect{13,12,90,60};
      const SDL_Rect src{2,3,60,57};
      SDL_FRect dst{8,4,static_cast<float>(scaled?48:60),static_cast<float>(scaled?40:57)};
      if(geometry) {dst.x=geometry==1?7.99F:-10.01F;dst.y-=.01F;dst.w+=.02F;dst.h+=.02F;}
      for(auto* r:{ra,rb}) {
        SDL_RenderSetClipRect(r,clipping?&clip:nullptr);
        SDL_SetRenderDrawColor(r,30,60,90,177);SDL_RenderClear(r);
        // Pending fill then direct drawing, followed by pending line: ordering.
        SDL_SetRenderDrawColor(r,60,10,20,255);SDL_Rect fill{0,0,60,50};SDL_RenderFillRect(r,&fill);
      }
      for(int repeat=0;repeat<3;++repeat) {
        assert(cth3ds::blit_draw(ra,a,fast,&src,&dst,static_cast<SDL_RendererFlip>(flip))==0);
        assert((flip?SDL_RenderCopyExF(rb,ref,&src,&dst,0,nullptr,static_cast<SDL_RendererFlip>(flip)):
                     SDL_RenderCopyF(rb,ref,&src,&dst))==0);
      }
      for(auto* r:{ra,rb}){SDL_SetRenderDrawColor(r,255,255,0,255);SDL_RenderDrawLine(r,0,40,120,40);assert(SDL_RenderFlush(r)==0);}
      auto* pa=static_cast<Uint32*>(a->pixels);auto* pb=static_cast<Uint32*>(b->pixels);
      for(int i=0;i<128*96;++i)if(pa[i]!=pb[i]) {
        std::printf("FAIL pattern=%d flip=%u mod=%d clip=%d scale=%d color=%d pixel=%d actual=%08x expected=%08x\n",pattern,flip,mod,clipping,scaled,colored,i,pa[i],pb[i]);return 1;
      }
      cth3ds::blit_destroy(fast);SDL_DestroyTexture(ref);++cases;
      assert(cth3ds::blit_counters.live_images==0 && cth3ds::blit_counters.live_bytes==0);
    }
  }
  // Automatic renderer teardown frees remaining metadata and payloads.
  auto* leaked_handle=cth3ds::blit_create(ra,64,64,source.data());assert(leaked_handle);
  cth3ds::blit_release_renderer(ra);
  assert(cth3ds::blit_counters.live_images==0 && cth3ds::blit_detail::images==nullptr);
  SDL_DestroyRenderer(ra);SDL_DestroyRenderer(rb);SDL_FreeSurface(a);SDL_FreeSurface(b);
  std::printf("PASS blitter %u pixel cases; direct=%llu opaque=%llu fallback=%llu promoted=%llu; zero live images\n",cases,
      (unsigned long long)cth3ds::blit_counters.direct,(unsigned long long)cth3ds::blit_counters.opaque,
      (unsigned long long)cth3ds::blit_counters.fallback,(unsigned long long)cth3ds::blit_counters.promoted);
}
