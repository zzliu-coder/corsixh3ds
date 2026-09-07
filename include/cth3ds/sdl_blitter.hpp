#pragma once

// SDL2-only backend seam. All owned handles are confined to th_gfx_sdl.cpp.
// A 1x1 SDL texture carries modulation state; exactly one full-size payload is
// owned by either an accelerated surface OR a promoted renderer texture.
// No private SDL structs, renderer-driver patches or second persistent copy.
#include <SDL.h>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <new>
#include "cth3ds/render_work.hpp"

namespace cth3ds {
namespace blit_detail {
struct Image {
  SDL_Texture* handle{};
  SDL_Texture* promoted{};
  SDL_Renderer* renderer{};
  SDL_Surface* surface{};
  Image* next{};
  Image* previous{};
  std::uint64_t bytes{};
  std::uint64_t span_bytes{};
  std::unique_ptr<std::uint32_t[]> rows;
  std::unique_ptr<std::uint16_t[]> spans;
  bool opaque{}, binary_alpha{}, software{};
  ~Image() { SDL_FreeSurface(surface); SDL_DestroyTexture(promoted); }
};
inline Image* images{};
inline Image* get(SDL_Texture* texture) noexcept {
  return texture ? static_cast<Image*>(SDL_GetTextureUserData(texture)) : nullptr;
}
inline void forget(Image* image) noexcept {
  if (image->previous) image->previous->next=image->next;
  else images=image->next;
  if (image->next) image->next->previous=image->previous;
  blit_counters.live_bytes-=image->bytes; --blit_counters.live_images;
  blit_counters.span_bytes-=image->span_bytes;
  SDL_SetTextureUserData(image->handle,nullptr);
  delete image;
}
inline SDL_Texture* promote(Image* image) {
  if (!image->promoted) {
    image->promoted=SDL_CreateTextureFromSurface(image->renderer,image->surface);
    if (!image->promoted) return nullptr;
    SDL_FreeSurface(image->surface); image->surface=nullptr;
    ++blit_counters.promoted;
  }
  Uint8 r=255,g=255,b=255,a=255;
  SDL_BlendMode blend=SDL_BLENDMODE_BLEND;
  SDL_GetTextureColorMod(image->handle,&r,&g,&b);
  SDL_GetTextureAlphaMod(image->handle,&a);
  SDL_GetTextureBlendMode(image->handle,&blend);
  SDL_SetTextureColorMod(image->promoted,r,g,b);
  SDL_SetTextureAlphaMod(image->promoted,a);
  SDL_SetTextureBlendMode(image->promoted,blend);
  return image->promoted;
}
} // namespace blit_detail

inline SDL_Texture* blit_create(SDL_Renderer* renderer, int width, int height,
                                const std::uint32_t* pixels) {
  if (!pixels || width<=0 || height<=0 || width>4096 || height>4096) {
    SDL_SetError("Invalid CorsixTH blit image"); return nullptr;
  }
  if(!blit_counters.enabled) {
    auto* texture=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ABGR8888,SDL_TEXTUREACCESS_STATIC,width,height);
    if(texture && (SDL_UpdateTexture(texture,nullptr,pixels,width*4)!=0 ||
                   SDL_SetTextureBlendMode(texture,SDL_BLENDMODE_BLEND)!=0)) {
      SDL_DestroyTexture(texture);return nullptr;
    }
    return texture;
  }
  std::unique_ptr<blit_detail::Image> image(new(std::nothrow) blit_detail::Image);
  if (!image) { SDL_OutOfMemory(); return nullptr; }
  image->renderer=renderer;
  SDL_RendererInfo info{};
  if(SDL_GetRendererInfo(renderer,&info)!=0)return nullptr;
  image->software=(info.flags&SDL_RENDERER_SOFTWARE)!=0;
  image->surface=SDL_CreateRGBSurfaceWithFormat(0,width,height,32,SDL_PIXELFORMAT_ABGR8888);
  if (!image->surface) return nullptr;
  image->opaque=true; image->binary_alpha=true;
  std::uint32_t runs=0;
  for (int y=0;y<height;++y) {
    const auto* row=pixels+static_cast<std::size_t>(y)*static_cast<std::size_t>(width);
    std::memcpy(static_cast<Uint8*>(image->surface->pixels)+y*image->surface->pitch,
                row,static_cast<std::size_t>(width)*4U);
    bool last_opaque=false;
    for (int x=0;x<width;++x) {
      const auto a=row[x]>>24U;
      const bool present=a!=0;
      runs+=present && !last_opaque; last_opaque=present;
      image->opaque=image->opaque && a==255;
      image->binary_alpha=image->binary_alpha && (a==0 || a==255);
    }
  }
  // Preserve raw pixels for modulation/fallback; bounded metadata skips binary
  // transparent spans without SDL RLE's lazy encoding/remapping work.
  SDL_SetSurfaceBlendMode(image->surface,SDL_BLENDMODE_BLEND);
  const auto raw_bytes=static_cast<std::uint64_t>(width)*static_cast<std::uint64_t>(height)*4U;
  const auto span_bytes=(static_cast<std::uint64_t>(height)+1U+static_cast<std::uint64_t>(runs))*4U;
  if (image->binary_alpha && !image->opaque && span_bytes<=raw_bytes/4U &&
      span_bytes+2U<=262144U-blit_counters.span_bytes) {
    image->rows.reset(new(std::nothrow) std::uint32_t[height+1]);
    image->spans.reset(new(std::nothrow) std::uint16_t[static_cast<std::size_t>(runs)*2U+1U]);
    if (image->rows && image->spans) {
      std::uint32_t offset=0;
      for(int y=0;y<height;++y) {
        image->rows[y]=offset;
        for(int x=0;x<width;) {
          while(x<width && (pixels[y*width+x]>>24U)==0)++x;
          const int begin=x;
          while(x<width && (pixels[y*width+x]>>24U)!=0)++x;
          if(x>begin) {image->spans[offset++]=static_cast<std::uint16_t>(begin);
            image->spans[offset++]=static_cast<std::uint16_t>(x);}
        }
      }
      image->rows[height]=offset;
      image->bytes=span_bytes+2U;
      image->span_bytes=span_bytes+2U;
    } else {image->rows.reset();image->spans.reset();}
  }
  image->handle=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ABGR8888,SDL_TEXTUREACCESS_STATIC,1,1);
  if (!image->handle) return nullptr;
  SDL_SetTextureBlendMode(image->handle,SDL_BLENDMODE_BLEND);
  if (SDL_SetTextureUserData(image->handle,image.get())!=0) {
    SDL_DestroyTexture(image->handle); return nullptr;
  }
  image->bytes+=raw_bytes;
  blit_counters.live_bytes+=image->bytes; ++blit_counters.live_images;
  blit_counters.span_bytes+=image->span_bytes;
  if(blit_counters.live_bytes>blit_counters.peak_bytes)blit_counters.peak_bytes=blit_counters.live_bytes;
  image->next=blit_detail::images;
  if(image->next)image->next->previous=image.get();
  blit_detail::images=image.get();
  return image.release()->handle;
}

inline void blit_destroy(SDL_Texture* texture) noexcept {
  if(auto* image=blit_detail::get(texture))blit_detail::forget(image);
  SDL_DestroyTexture(texture);
}
inline void blit_release_renderer(SDL_Renderer* renderer) noexcept {
  // Renderer destruction also destroys SDL handles, but not user data.
  auto* image=blit_detail::images;
  while(image) { auto* next=image->next;
    if(image->renderer==renderer)blit_detail::forget(image);
    image=next;
  }
}

inline int blit_draw(SDL_Renderer* renderer, SDL_Surface* canvas, SDL_Texture* texture,
    const SDL_Rect* source, const SDL_FRect* destination, SDL_RendererFlip flip) {
  auto* image=blit_detail::get(texture);
  if(!image) {
    ++blit_counters.fallback;
    return flip==SDL_FLIP_NONE ? SDL_RenderCopyF(renderer,texture,source,destination) :
      SDL_RenderCopyExF(renderer,texture,source,destination,0,nullptr,flip);
  }
  if(image && image->renderer!=renderer) return SDL_SetError("Blit renderer owner mismatch");
  float sx=1,sy=1; SDL_RenderGetScale(renderer,&sx,&sy);
  SDL_Rect viewport; SDL_RenderGetViewport(renderer,&viewport);
  // Match SDL2 SW_QueueCopy's truncation, including CorsixTH's +/-0.01
  // overdraw coordinates. Fractional scaling still uses the reference path.
  const bool bounded=destination && std::isfinite(destination->x) && std::isfinite(destination->y) &&
    std::isfinite(destination->w) && std::isfinite(destination->h) &&
    destination->x>=-32768 && destination->x<=32768 && destination->y>=-32768 && destination->y<=32768 &&
    destination->w>0 && destination->w<4097 && destination->h>0 && destination->h<4097;
  if(blit_counters.enabled && image && image->software && image->surface && canvas && bounded &&
     flip==SDL_FLIP_NONE && !SDL_GetRenderTarget(renderer) && sx==1 && sy==1 &&
     viewport.x==0 && viewport.y==0 && viewport.w==canvas->w && viewport.h==canvas->h) {
    SDL_Rect src=source?*source:SDL_Rect{0,0,image->surface->w,image->surface->h};
    if(static_cast<int>(destination->w)==src.w && static_cast<int>(destination->h)==src.h &&
       src.x>=0 && src.y>=0 && src.w>=0 && src.h>=0 &&
       src.x<=image->surface->w-src.w && src.y<=image->surface->h-src.h) {
      // Mixing queued renderer operations with direct blits requires a flush
      // before each crossing, preserving lines/fills/complex effects ordering.
      if(SDL_RenderFlush(renderer)!=0)return -1;
      SDL_Rect old_clip,clip; SDL_GetClipRect(canvas,&old_clip);
      if(SDL_RenderIsClipEnabled(renderer))SDL_RenderGetClipRect(renderer,&clip);
      else clip={0,0,canvas->w,canvas->h};
      SDL_SetClipRect(canvas,&clip);
      SDL_GetClipRect(canvas,&clip); // intersect the renderer clip with surface bounds
      Uint8 r=255,g=255,b=255,a=255; SDL_BlendMode blend=SDL_BLENDMODE_BLEND;
      SDL_GetTextureColorMod(texture,&r,&g,&b); SDL_GetTextureAlphaMod(texture,&a);
      SDL_GetTextureBlendMode(texture,&blend);
      if(!(image->opaque || image->rows) || r!=255 || g!=255 || b!=255 || a!=255 ||
         blend!=SDL_BLENDMODE_BLEND || canvas->format->format!=SDL_PIXELFORMAT_ABGR8888 || SDL_MUSTLOCK(canvas)) {
        SDL_SetClipRect(canvas,&old_clip);
        ++blit_counters.fallback;
        auto* actual=blit_detail::promote(image);
        return actual?SDL_RenderCopyF(renderer,actual,source,destination):-1;
      }
      const bool opaque=image->opaque && a==255 && blend==SDL_BLENDMODE_BLEND;
      SDL_SetSurfaceColorMod(image->surface,r,g,b);
      SDL_SetSurfaceAlphaMod(image->surface,a);
      SDL_SetSurfaceBlendMode(image->surface,opaque?SDL_BLENDMODE_NONE:blend);
      SDL_Rect dst{static_cast<int>(destination->x),static_cast<int>(destination->y),src.w,src.h};
      int result=0;
      const bool copy_spans=(image->opaque || image->rows) && r==255 && g==255 && b==255 && a==255 &&
        blend==SDL_BLENDMODE_BLEND && canvas->format->format==SDL_PIXELFORMAT_ABGR8888 && !SDL_MUSTLOCK(canvas);
      if(copy_spans) {
        // Bounds use the real clipped destination; source subrects and negative
        // offsets use the same translation. Preserve painter order and alpha.
        SDL_Rect clipped;
        if(SDL_IntersectRect(&dst,&clip,&clipped)==SDL_TRUE) {
          for(int y=clipped.y;y<clipped.y+clipped.h;++y) {
            const int source_y=src.y+y-dst.y;
            const int left=src.x+clipped.x-dst.x, right=left+clipped.w;
            auto copy=[&](int start,int end) {
              if(end<=start)return;
              const auto* from=static_cast<const Uint8*>(image->surface->pixels)+source_y*image->surface->pitch+start*4;
              auto* to=static_cast<Uint8*>(canvas->pixels)+y*canvas->pitch+(dst.x+start-src.x)*4;
              std::memcpy(to,from,static_cast<std::size_t>(end-start)*4U);
            };
            if(image->opaque)copy(left,right);
            else for(auto i=image->rows[source_y];i<image->rows[source_y+1];i+=2U)
              copy(std::max(left,static_cast<int>(image->spans[i])),std::min(right,static_cast<int>(image->spans[i+1])));
          }
          dst=clipped;
        } else {dst.w=0;dst.h=0;}
      } else result=SDL_BlitSurface(image->surface,&src,canvas,&dst);
      SDL_SetClipRect(canvas,&old_clip);
      if(result==0) {
        ++blit_counters.direct; if(opaque)++blit_counters.opaque;
        if(dst.w>0 && dst.h>0)blit_counters.pixels+=static_cast<std::uint64_t>(dst.w)*static_cast<std::uint64_t>(dst.h);
        else ++blit_counters.clipped;
      }
      return result;
    }
  }
  ++blit_counters.fallback;
  auto* actual=image?blit_detail::promote(image):texture;
  if(!actual)return -1;
  return flip==SDL_FLIP_NONE ? SDL_RenderCopyF(renderer,actual,source,destination) :
    SDL_RenderCopyExF(renderer,actual,source,destination,0,nullptr,flip);
}
} // namespace cth3ds

namespace cth3ds {
// Once per fresh canvas, before any game texture exists. The target device
// selects a path only when both same-workload samples improve. This is a small
// software microbenchmark, not proof of game FPS or complete pixel correctness.
inline void blit_calibrate(SDL_Renderer* renderer, SDL_Surface* canvas) noexcept {
  if(blit_counters.reference_forced || !canvas || canvas->w<160 || canvas->h<100 ||
     canvas->format->format!=SDL_PIXELFORMAT_ABGR8888 || SDL_MUSTLOCK(canvas) ||
     blit_counters.live_images || SDL_GetRenderTarget(renderer)) {
    blit_counters.enabled=false;return;
  }
  blit_counters.probe_ran=true;
  const auto frequency=SDL_GetPerformanceFrequency();
  std::unique_ptr<std::uint32_t[]> pixels(new(std::nothrow) std::uint32_t[64*64]);
  if(!frequency || !pixels) {blit_counters.enabled=false;return;}
  Uint8 old_r,old_g,old_b,old_a;SDL_GetRenderDrawColor(renderer,&old_r,&old_g,&old_b,&old_a);
  bool matched=true,valid=true;
  for(int pattern=0;pattern<2 && valid;++pattern) {
    for(int y=0;y<64;++y)for(int x=0;x<64;++x)
      pixels[y*64+x]=(pattern==0 || (x>25 && x<39 && y>5 && y<60))?0xff4271a3U:0U;
    blit_counters.enabled=true;
    std::unique_ptr<SDL_Texture,decltype(&blit_destroy)> fast(blit_create(renderer,64,64,pixels.get()),blit_destroy);
    std::unique_ptr<SDL_Texture,decltype(&SDL_DestroyTexture)> ref(
      SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ABGR8888,SDL_TEXTUREACCESS_STATIC,64,64),SDL_DestroyTexture);
    if(!fast || !ref || SDL_UpdateTexture(ref.get(),nullptr,pixels.get(),64*4)!=0 ||
       SDL_SetTextureBlendMode(ref.get(),SDL_BLENDMODE_BLEND)!=0) {valid=false;break;}
    auto draw=[&](bool accelerated,int n) {
      const SDL_FRect dst{static_cast<float>(n*29%(canvas->w-64)),static_cast<float>(n*23%(canvas->h-64)),64,64};
      return accelerated?blit_draw(renderer,canvas,fast.get(),nullptr,&dst,SDL_FLIP_NONE):
        SDL_RenderCopyF(renderer,ref.get(),nullptr,&dst);
    };
    // Full-canvas checksum is additional on-target screening; exact image
    // equivalence remains covered by the independent host pixel suite.
    std::uint32_t checksums[2]{};
    for(int mode=0;mode<2;++mode) {
      SDL_SetRenderDrawColor(renderer,21,41,61,255);
      valid=valid && SDL_RenderClear(renderer)==0;
      for(int n=0;n<16;++n)valid=valid && draw(mode!=0,n)==0;
      valid=valid && SDL_RenderFlush(renderer)==0;
      std::uint32_t hash=2166136261U;
      for(int y=0;y<canvas->h;++y) {
        const auto* row=reinterpret_cast<const std::uint32_t*>(static_cast<const Uint8*>(canvas->pixels)+y*canvas->pitch);
        for(int x=0;x<canvas->w;++x)hash=((hash<<5U)|(hash>>27U))^row[x];
      }
      checksums[mode]=hash;
    }
    matched=matched && checksums[0]==checksums[1];
    std::uint64_t samples[2][3]{};
    for(int trial=0;trial<3 && valid;++trial)for(int order=0;order<2;++order) {
      const int mode=(order+trial)%2;
      const auto start=SDL_GetPerformanceCounter();
      for(int n=0;n<128;++n)valid=valid && draw(mode!=0,n)==0;
      valid=valid && SDL_RenderFlush(renderer)==0;
      const auto elapsed=(SDL_GetPerformanceCounter()-start)*1000000U/frequency;
      samples[mode][trial]=elapsed;
      if(elapsed>1000000U)valid=false; // bounded startup work, reject slow probe
    }
    for(auto& sample:samples)std::sort(sample,sample+3);
    blit_counters.probe_reference_us[pattern]=samples[0][1];
    blit_counters.probe_fast_us[pattern]=samples[1][1];
  }
  blit_counters.probe_pixels=valid && matched;
  bool faster=valid && matched;
  for(int i=0;i<2;++i)faster=faster && blit_counters.probe_reference_us[i]>0 &&
    blit_counters.probe_fast_us[i]*100U<=blit_counters.probe_reference_us[i]*90U;
  blit_counters.enabled=faster;
  blit_counters.direct=blit_counters.opaque=blit_counters.fallback=blit_counters.promoted=0;
  blit_counters.clipped=blit_counters.pixels=blit_counters.peak_bytes=0;
  SDL_SetRenderDrawColor(renderer,old_r,old_g,old_b,old_a);
  SDL_ClearError();
}
} // namespace cth3ds
