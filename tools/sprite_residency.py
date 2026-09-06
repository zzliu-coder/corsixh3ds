"""Bound actual SDL sprite textures; keep encoded sprite data as reload source."""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError

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


def transform(text):
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
    return replace_exact(text, old, new, 'texture ownership publication')


def patch_sprite_residency(root: Path, dry_run=False):
    path = root/'CorsixTH/Src/th_gfx_sdl.cpp'
    old = path.read_text(encoding='utf-8')
    new = transform(old)
    if old == new: return []
    if not dry_run: path.write_text(new, encoding='utf-8')
    return [path.relative_to(root).as_posix()]


def check_sprite_residency(root):
    try:
        return ['sprite residency patch missing: '+name for name in patch_sprite_residency(root,True)]
    except (OSError, SoundPatchError) as exc:
        return [str(exc)]
