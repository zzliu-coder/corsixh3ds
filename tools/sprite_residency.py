"""Bound actual SDL sprite textures; keep encoded sprite data as reload source."""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError

FAST_DRAW = '''
#ifdef CORSIXTH_3DS
  // CORSIXTH_3DS_FLIP_CACHE_R48: one decoded orientation, same global budget.
  // Alternate palettes and jelly strips retain the upstream general path.
  const unsigned flip = ((iFlags & thdf_flip_horizontal) ? 1U : 0U) |
                        ((iFlags & thdf_flip_vertical) ? 2U : 0U);
  if (cth3ds::render_work.fast_flip_enabled && flip &&
      !(iFlags & thdf_alt_palette) && effect == animation_effect::none && scale_factor == 1 &&
      sprite.data && sprite.width > 0 && sprite.height > 0) {
    SDL_Texture*& cached = sprite.flipped_texture[flip - 1U];
    if (!cached) {
      ++cth3ds::render_work.flip_misses;
      const size_t bytes = sprite_texture_prepare(sprite.width, sprite.height);
      const uint32_t flags = (sprite.sprite_flags & ~thdf_alt32_mask) |
          thdf_alt32_plain | (iFlags & (thdf_nearest | thdf_flip_horizontal | thdf_flip_vertical));
      cached = target->create_palettized_texture(sprite.width, sprite.height,
                                                sprite.data, palette, flags);
      sprite_texture_remember(&cached, bytes);
    } else ++cth3ds::render_work.flip_hits;
    cth3ds::render_work.flip_pixels_saved += static_cast<uint64_t>(sprite.width) * sprite.height;
    SDL_Rect rect{iX, iY, sprite.width, sprite.height};
    pCanvas->draw(cached, nullptr, &rect, iFlags & ~(thdf_flip_horizontal | thdf_flip_vertical));
    return;
  }
#endif
'''

# Fixed metadata, no per-draw allocations or lookup. FIFO is deliberate: misses
# evict the oldest generated texture; hits are the existing raw-pointer path.
CACHE = '''
#ifdef CORSIXTH_3DS
// CORSIXTH_3DS_SPRITE_RESIDENCY_V1
constexpr size_t sprite_texture_budget = 6U * 1024U * 1024U;
struct sprite_texture_slot { SDL_Texture** owner{}; size_t bytes{}; };
std::array<sprite_texture_slot, 4096> sprite_texture_slots{};
size_t sprite_texture_head = 0, sprite_texture_tail = 0;
size_t sprite_texture_count = 0, sprite_texture_bytes = 0;

void sprite_texture_evict_one() {
  auto& entry = sprite_texture_slots[sprite_texture_head];
  if (entry.owner) {
    // SDL_DestroyTexture flushes queued draws which reference this texture.
    SDL_DestroyTexture(*entry.owner);
    *entry.owner = nullptr;
    sprite_texture_bytes -= entry.bytes;
  }
  entry = {};
  sprite_texture_head = (sprite_texture_head + 1) % sprite_texture_slots.size();
  --sprite_texture_count;
}
size_t sprite_texture_prepare(int width, int height) {
  if (width <= 0 || height <= 0) throw std::runtime_error("invalid sprite dimensions");
  // Pixel payload plus per-texture bookkeeping allowance. Driver/allocator
  // overhead is still measured by the whole-heap telemetry, not declared exact.
  const uint64_t size = uint64_t(width) * uint64_t(height) * 4U + 512U;
  if (size > sprite_texture_budget) throw std::runtime_error("sprite exceeds texture budget");
  while (sprite_texture_count && (sprite_texture_bytes > sprite_texture_budget - size ||
         sprite_texture_count == sprite_texture_slots.size())) sprite_texture_evict_one();
  return static_cast<size_t>(size);
}
void sprite_texture_remember(SDL_Texture** owner, size_t bytes) {
  sprite_texture_slots[sprite_texture_tail] = {owner, bytes};
  sprite_texture_tail = (sprite_texture_tail + 1) % sprite_texture_slots.size();
  ++sprite_texture_count;
  sprite_texture_bytes += bytes;
}
void sprite_texture_forget(SDL_Texture** owner) {
  // Destruction/recolour only; drawing a cached sprite has no scan or allocation.
  for (auto& entry : sprite_texture_slots) {
    if (entry.owner == owner) {
      sprite_texture_bytes -= entry.bytes;
      entry = {};
      return;
    }
  }
}
#endif
'''

LEGACY_CACHE = CACHE
CACHE = CACHE.replace('    *entry.owner = nullptr;\n    sprite_texture_bytes -= entry.bytes;',
    '    *entry.owner = nullptr;\n    sprite_texture_bytes -= entry.bytes;\n    ++cth3ds::render_work.cache_evictions;\n    cth3ds::render_work.cache_bytes = sprite_texture_bytes;')
CACHE = CACHE.replace('  sprite_texture_bytes += bytes;',
    '  sprite_texture_bytes += bytes;\n  ++cth3ds::render_work.texture_creates;\n  cth3ds::render_work.cache_bytes = sprite_texture_bytes;\n  cth3ds::render_work.cache_peak_bytes = std::max(cth3ds::render_work.cache_peak_bytes, static_cast<uint64_t>(sprite_texture_bytes));')
CACHE = CACHE.replace('      sprite_texture_bytes -= entry.bytes;',
    '      sprite_texture_bytes -= entry.bytes;\n      cth3ds::render_work.cache_bytes = sprite_texture_bytes;')

def transform(text):
    text = text.replace('  for (auto& texture : sprites[iNumber].flipped_texture) {\n    if (!texture) continue;',
                        '  for (auto& texture : sprites[iNumber].flipped_texture) {')
    text = text.replace(LEGACY_CACHE, CACHE)
    marker = 'constexpr double pi = 3.14159265358979323846;'
    text = replace_exact(text, marker, marker + '\n' + CACHE, 'sprite FIFO implementation')
    for target in ('sprites[iNumber].texture', 'sprites[iNumber].alt_texture', 'pSprite->alt_texture'):
        old = '    SDL_DestroyTexture('+target+');' if not target.startswith('pSprite') else '      SDL_DestroyTexture('+target+');'
        new = '#ifdef CORSIXTH_3DS\n  sprite_texture_forget(&'+target+');\n#endif\n'+old
        text = replace_exact(text, old, new, 'forget sprite texture '+target)
    old = '''    pTexture = target->create_palettized_texture(
        sprite.width, sprite.height, sprite.data, palette, iSprFlags);
    sprite.texture = pTexture;'''
    new = '''#ifdef CORSIXTH_3DS
    const size_t texture_bytes = sprite_texture_prepare(sprite.width, sprite.height);
#endif
''' + old + '''
#ifdef CORSIXTH_3DS
    sprite_texture_remember(&sprite.texture, texture_bytes);
    cth3ds::runtime_observe_memory("textures", "sprite-cache", "pixels-plus-allowance", cth3ds::MemoryGate::Operation, texture_bytes, true, sprite_texture_bytes, true, false);
#endif'''
    text = replace_exact(text, old, new, 'normal texture residency')
    old = '''SDL_Texture* sprite_sheet::_makeAltBitmap(sprite* pSprite) {
  const auto& argb_data = palette->get_argb_data();'''
    new = '''SDL_Texture* sprite_sheet::_makeAltBitmap(sprite* pSprite) {
#ifdef CORSIXTH_3DS
  const size_t texture_bytes = sprite_texture_prepare(pSprite->width, pSprite->height);
#endif
  const auto& argb_data = palette->get_argb_data();'''
    text = replace_exact(text, old, new, 'alternate preflight')
    old = '  return pSprite->alt_texture;\n}'
    new = '''#ifdef CORSIXTH_3DS
  sprite_texture_remember(&pSprite->alt_texture, texture_bytes);
  cth3ds::runtime_observe_memory("textures", "sprite-cache", "pixels-plus-allowance", cth3ds::MemoryGate::Operation, texture_bytes, true, sprite_texture_bytes, true, false);
#endif
''' + old
    text = replace_exact(text, old, new, 'alternate residency')
    # Keep transient decoded pixels and a partially configured SDL texture owned
    # while any decoder/SDL call may throw. The successful pointer API is unchanged.
    text = replace_exact(text, '  full_colour_storing oRenderer(pARGBPixels, iWidth, iHeight);',
                         '  std::unique_ptr<uint32_t[]> argb_owner(pARGBPixels);\n  full_colour_storing oRenderer(pARGBPixels, iWidth, iHeight);', 'temporary pixel ownership')
    text = replace_exact(text, '  delete[] pARGBPixels;', '  argb_owner.reset(); // release before the after-observation', 'pixel cleanup')
    old = '''  if (pTexture == nullptr) {
    throw std::runtime_error(SDL_GetError());
  }

  int err = 0;'''
    new = '''  if (pTexture == nullptr) {
    throw std::runtime_error(SDL_GetError());
  }
  std::unique_ptr<SDL_Texture, decltype(&SDL_DestroyTexture)> texture_owner(pTexture, SDL_DestroyTexture);

  int err = 0;'''
    text = replace_exact(text, old, new, 'texture preparation ownership')
    old = '''  return pTexture;
}

void render_target::draw'''
    new = '''  return texture_owner.release();
}

void render_target::draw'''
    text = replace_exact(text, old, new, 'texture ownership publication')
    text = replace_exact(text, '#include "th_gfx_sdl.h"',
        '#include "th_gfx_sdl.h"\n#ifdef CORSIXTH_3DS\n#include "cth3ds/render_work.hpp"\n#endif', 'render counters include')
    text = replace_exact(text, '  // Find or create the texture\n', FAST_DRAW + '\n  // Find or create the texture\n', 'bounded flipped sprite path')
    text = replace_exact(text, '  oRenderer.decode_image(pPixels, pPalette, iSpriteFlags);',
        '''  oRenderer.decode_image(pPixels, pPalette, iSpriteFlags);
#ifdef CORSIXTH_3DS
  cth3ds::render_work.decoded_pixels += static_cast<uint64_t>(iWidth) * iHeight;
  cth3ds::flip_rgba_in_place(pARGBPixels, iWidth, iHeight,
      (iSpriteFlags & thdf_flip_horizontal) != 0, (iSpriteFlags & thdf_flip_vertical) != 0);
#endif''', 'decode flip once')
    text = replace_exact(text, '  if (sprites[iNumber].data != nullptr) {',
        '''#ifdef CORSIXTH_3DS
  for (auto& texture : sprites[iNumber].flipped_texture) {
    sprite_texture_forget(&texture);
    SDL_DestroyTexture(texture);
    texture = nullptr;
  }
#endif
  if (sprites[iNumber].data != nullptr) {''', 'flipped texture destruction')
    draw_head = '                         const SDL_Rect* prcDstRect, int iFlags) {\n'
    bridge = '#ifdef CORSIXTH_3DS_GPU\n  cth3ds::GpuSubmitBridgeScope submit_bridge;\n#endif\n'
    # R66 adds a scope immediately after the signature. Retain it when checking
    # an already assembled tree; counter order and meaning stay unchanged.
    if draw_head + bridge in text:
        draw_head += bridge
    text = replace_exact(text, draw_head + '  SDL_SetTextureAlphaMod', draw_head + '''
#ifdef CORSIXTH_3DS
  ++cth3ds::render_work.draws;
  if (iFlags & (thdf_flip_horizontal | thdf_flip_vertical)) ++cth3ds::render_work.flipped_fallback;
#endif
  SDL_SetTextureAlphaMod'''.lstrip('\n'), 'actual draw counters')
    text = text.replace('  for (auto& texture : sprites[iNumber].flipped_texture) {\n    sprite_texture_forget',
                        '  for (auto& texture : sprites[iNumber].flipped_texture) {\n    if (!texture) continue;\n    sprite_texture_forget')
    return text


def patch_sprite_residency(root: Path, dry_run=False):
    path = root/'CorsixTH/Src/th_gfx_sdl.cpp'
    old = path.read_text(encoding='utf-8')
    new = transform(old)
    changed = []
    if old != new:
        if not dry_run: path.write_text(new, encoding='utf-8')
        changed.append(path.relative_to(root).as_posix())
    header = root/'CorsixTH/Src/th_gfx_sdl.h'
    old = header.read_text(encoding='utf-8')
    new = replace_exact(old, '    SDL_Texture* alt_texture;',
        '    SDL_Texture* alt_texture;\n#ifdef CORSIXTH_3DS\n    SDL_Texture* flipped_texture[3]{};\n#endif', 'flipped cache owner slots')
    if old != new:
        if not dry_run: header.write_text(new, encoding='utf-8')
        changed.append(header.relative_to(root).as_posix())
    return changed


def check_sprite_residency(root):
    try:
        return ['sprite residency patch missing: '+name for name in patch_sprite_residency(root,True)]
    except (OSError, SoundPatchError) as exc:
        return [str(exc)]
