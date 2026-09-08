"""Bound retained FreeType layouts across fonts while using the real renderer."""
from sound_lifetime import replace_exact

RELEASE = r'''
#ifdef CORSIXTH_3DS
void freetype_font::release_cached_text(cached_text* entry) const noexcept {
  cth3ds::text_cache.forget(entry->budget);
  free_texture(entry);
  delete[] entry->data;
  delete[] entry->message;
  *entry = {};
}
void freetype_font::evict_cached_text(void* context) noexcept {
  auto* entry = static_cast<cached_text*>(context);
  entry->owner->release_cached_text(entry);
}
#endif
'''

def transforms(root):
    path = 'CorsixTH/Src/th_gfx_font.h'
    text = (root/path).read_text()
    if '// CORSIXTH_3DS_TEXT_CACHE_R58' not in text:
        text = replace_exact(text, 'class freetype_font final : public font {',
            '''// CORSIXTH_3DS_TEXT_CACHE_R58
#ifdef CORSIXTH_3DS
#include "cth3ds/text_cache.hpp"
#endif
class freetype_font final : public font {''', 'font cache include')
        text = replace_exact(text, '  struct cached_text {', '''  struct cached_text {
#ifdef CORSIXTH_3DS
    cth3ds::TextCacheNode budget{};
    const freetype_font* owner{};
    int max_rows{}, skip_rows{};
#endif''', 'font cache ownership')
        text = replace_exact(text, '  static FT_Library freetype_library;', '''#ifdef CORSIXTH_3DS
  void release_cached_text(cached_text*) const noexcept;
  static void evict_cached_text(void*) noexcept;
#endif
  static FT_Library freetype_library;''', 'font cache release declaration')
    yield path, text

    path = 'CorsixTH/Src/th_gfx_font.cpp'
    text = (root/path).read_text()
    if RELEASE not in text:
        text = replace_exact(text, 'freetype_font::~freetype_font() {',
                             RELEASE + '\nfreetype_font::~freetype_font() {', 'font release')
        text = replace_exact(text, '''    delete[] pEntry->message;
    delete[] pEntry->data;
    free_texture(pEntry);''', '''#ifdef CORSIXTH_3DS
    release_cached_text(pEntry);
#else
    delete[] pEntry->message;
    delete[] pEntry->data;
    free_texture(pEntry);
#endif''', 'font destructor ownership')
        text = replace_exact(text, '''    pEntry->is_valid = false;
    free_texture(pEntry);''', '''#ifdef CORSIXTH_3DS
    release_cached_text(pEntry);
#else
    pEntry->is_valid = false;
    free_texture(pEntry);
#endif''', 'font invalidation frees layouts')
        text = replace_exact(text, '  if (freetype_library == nullptr) {',
            '''  // Every face owns one library reference, including later fonts.
  if (!is_done_freetype_init) {''', 'font library per-owner lifetime')
        text = replace_exact(text, '      pEntry->alignment != eAlign || !pEntry->is_valid ||',
            '''#ifdef CORSIXTH_3DS
      pEntry->max_rows != iMaxRows || pEntry->skip_rows != iSkipRows ||
#endif
      pEntry->alignment != eAlign || !pEntry->is_valid ||''', 'font hash collision parameters')
        text = replace_exact(text, '''    free_texture(pEntry);
    delete[] pEntry->data;
    pEntry->data = nullptr;
    pEntry->is_valid = false;''', '''#ifdef CORSIXTH_3DS
    release_cached_text(pEntry);
    pEntry->owner = this;
    pEntry->max_rows = iMaxRows;
    pEntry->skip_rows = iSkipRows;
#else
    free_texture(pEntry);
    delete[] pEntry->data;
    pEntry->data = nullptr;
    pEntry->is_valid = false;
#endif''', 'font miss release')
        text = replace_exact(text, '    // Prepare a canvas for rendering.', '''#ifdef CORSIXTH_3DS
    // Conservative retained charge: grayscale + ARGB staging + compact GPU
    // source including 8x8 padding + message and handle allowance. The staging
    // bytes are temporary; charging them leaves headroom without duplicating data.
    const auto w = static_cast<std::size_t>(pEntry->width);
    const auto h = static_cast<std::size_t>(pEntry->height);
    const auto charge = w * h * 5U + ((w + 7U) & ~7U) * ((h + 7U) & ~7U) * 4U
                        + pEntry->message_buffer_length + 1024U;
    cth3ds::text_cache.reserve(pEntry->budget, charge, pEntry, evict_cached_text);
#endif
    // Prepare a canvas for rendering.''', 'font byte budget at real allocation')
        text = replace_exact(text, '  if (pCanvas != nullptr) {', '''#ifdef CORSIXTH_3DS
  cth3ds::text_cache.touch(pEntry->budget);
#endif
  if (pCanvas != nullptr) {''', 'font real draw touch')
        text = replace_exact(text, '''  oDrawArea.row_count = pEntry->row_count;
  return oDrawArea;''', '''  oDrawArea.row_count = pEntry->row_count;
#ifdef CORSIXTH_3DS
  cth3ds::text_cache.finish(pEntry->budget);
#endif
  return oDrawArea;''', 'font oversized transient release')
    yield path, text
