"""Real software-renderer fast path; keep the pinned engine API and fallback."""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError

INCLUDE = '''#ifdef CORSIXTH_3DS
// CORSIXTH_3DS_FAST_BLIT_R51: private handles never leave this translation unit.
#include "cth3ds/sdl_blitter.hpp"
#include "cth3ds/gpu_sdl_bridge.hpp"
#define SDL_DestroyTexture cth3ds::blit_destroy
#endif
'''
OWNER_INCLUDE = '''#ifdef CORSIXTH_3DS
#include "cth3ds/render_work.hpp"
#endif'''

RAW_LOAD = '''void raw_bitmap::load_from_th_file(const uint8_t* pPixelData,
                                   size_t iPixelDataLength, int iWidth,
                                   render_target* pEventualCanvas,
                                   uint32_t spriteFlags) {
  // CORSIXTH_3DS_RAW_OWNERSHIP_R62: prepare completely before replacing state.
  if (!pEventualCanvas || !pPixelData || !bitmap_palette || iWidth <= 0 ||
      iPixelDataLength == 0 || iPixelDataLength % static_cast<size_t>(iWidth) != 0 ||
      iPixelDataLength / static_cast<size_t>(iWidth) > 4096) {
    throw std::invalid_argument("Invalid raw bitmap dimensions or owner");
  }
  const int iHeight = static_cast<int>(iPixelDataLength / iWidth);
  using texture_owner = std::unique_ptr<SDL_Texture, decltype(&SDL_DestroyTexture)>;
  texture_owner next(nullptr, SDL_DestroyTexture);
#ifdef CORSIXTH_3DS_GPU
  if (cth3ds::gpu_active()) {
    // Legacy 0xFF palette blocks ignore opacity/alt32 recolouring; retain the
    // exact palette alpha and the existing load-time flips without RGBA copies.
    const auto& colours = bitmap_palette->get_argb_data();
    next.reset(cth3ds::gpu_image_create_indexed(pEventualCanvas->get_renderer(),
      iWidth, iHeight, pPixelData, colours.data(),
      (spriteFlags & thdf_flip_horizontal) != 0,
      (spriteFlags & thdf_flip_vertical) != 0));
    if (!next) {
      cth3ds::runtime_observe_memory("raw-image", "allocation-failed", "indexed-block",
        cth3ds::MemoryGate::Operation, 0, false, 0, false, true);
      throw std::runtime_error(SDL_GetError());
    }
    if (SDL_SetTextureBlendMode(next.get(), SDL_BLENDMODE_BLEND) != 0)
      throw std::runtime_error(SDL_GetError());
  } else
#endif
  {
    std::unique_ptr<uint8_t[]> converted_sprite(convertLegacySprite(pPixelData, iPixelDataLength));
    next.reset(pEventualCanvas->create_palettized_texture(iWidth, iHeight,
      converted_sprite.get(), bitmap_palette, thdf_alt32_plain | spriteFlags));
    if (!next) throw std::runtime_error("Raw bitmap texture creation failed");
  }
  if (texture) SDL_DestroyTexture(texture);
  texture = next.release();
  width = iWidth;
  height = iHeight;
  target = pEventualCanvas;
}'''

def transform(text):
    legacy_include=INCLUDE.replace('#include "cth3ds/gpu_sdl_bridge.hpp"\n','')
    if legacy_include in text:text=text.replace(legacy_include,INCLUDE,1)
    if INCLUDE not in text:
        text=replace_exact(text, OWNER_INCLUDE, OWNER_INCLUDE+'\n'+INCLUDE,'blitter owner include')
    old='''      SDL_CreateTexture(renderer, pixel_format->format,
                        SDL_TEXTUREACCESS_STATIC, iWidth, iHeight);'''
    new='''#ifdef CORSIXTH_3DS
      cth3ds::blit_create(renderer, iWidth, iHeight, pPixels);
#else
'''+old+'''
#endif'''
    if new not in text: text=replace_exact(text,old,new,'single image owner')
    old='''    SDL_DestroyRenderer(renderer);'''
    new='''#ifdef CORSIXTH_3DS
    cth3ds::blit_release_renderer(renderer);
#endif
'''+old
    if new not in text: text=replace_exact(text,old,new,'release renderer image metadata')
    old='''  if (current_target) current_target->offset(scaledDstRect);
  if (iSDLFlip != 0) {'''
    new='''  if (current_target) current_target->offset(scaledDstRect);
#ifdef CORSIXTH_3DS
  if (cth3ds::blit_draw(renderer, game_surface, pTexture, prcSrcRect, &scaledDstRect,
                        static_cast<SDL_RendererFlip>(iSDLFlip)) != 0)
    throw std::runtime_error(SDL_GetError());
  return;
#endif
  if (iSDLFlip != 0) {'''
    if new not in text: text=replace_exact(text,old,new,'actual blitter drawing')
    old='  cth3ds::runtime_set_game_canvas(game_surface);'
    new=old+'\n  cth3ds::blit_calibrate(renderer, game_surface); // R51 on-device path selection'
    if new not in text:text=replace_exact(text,old,new,'calibrate before game textures')
    old='''  err = SDL_UpdateTexture(pTexture, nullptr, pPixels,
                          static_cast<int>(sizeof(*pPixels) * iWidth));'''
    new='#ifndef CORSIXTH_3DS\n'+old+'\n#endif // blit_create has already populated the single owned payload'
    if new not in text:text=replace_exact(text,old,new,'avoid repeated initial texture upload')
    if RAW_LOAD not in text:
        begin=text.index('void raw_bitmap::load_from_th_file(')
        end=text.index('\n}',begin)+2
        text=text[:begin]+RAW_LOAD+text[end:]
    old='''  SDL_SetTextureAlphaMod(pTexture, 0xFF);
  if (iFlags & thdf_alpha_50) {
    SDL_SetTextureAlphaMod(pTexture, 0x80);
  } else if (iFlags & thdf_alpha_75) {
    SDL_SetTextureAlphaMod(pTexture, 0x40);
  }'''
    new='''#ifdef CORSIXTH_3DS
  SDL_SetTextureAlphaMod(pTexture, (iFlags & thdf_alpha_50) ? 0x80 :
      ((iFlags & thdf_alpha_75) ? 0x40 : 0xFF));
#else
  SDL_SetTextureAlphaMod(pTexture, 0xFF);
  if (iFlags & thdf_alpha_50) {
    SDL_SetTextureAlphaMod(pTexture, 0x80);
  } else if (iFlags & thdf_alpha_75) {
    SDL_SetTextureAlphaMod(pTexture, 0x40);
  }
#endif'''
    if new not in text:
        text=replace_exact(text,old,new,'one final 3DS texture alpha')
    return text

def patch_render_fast(root: Path, dry_run=False):
    path=root/'CorsixTH/Src/th_gfx_sdl.cpp'
    old=path.read_text(); new=transform(old)
    if old==new:return []
    if not dry_run:path.write_text(new)
    return ['CorsixTH/Src/th_gfx_sdl.cpp']

def check_render_fast(root):
    try:return ['fast blit patch missing: '+p for p in patch_render_fast(root,True)]
    except (OSError,SoundPatchError) as e:return [str(e)]
