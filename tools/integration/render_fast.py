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
