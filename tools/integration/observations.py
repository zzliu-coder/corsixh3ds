"""Insert observations into the actual upstream resource and frame paths."""

from __future__ import annotations

from dual_screen_canvas import patch_dual_screen, check_dual_screen
from pathlib import Path
import shutil
import tempfile
from .common import (
    Change,
    IntegrationError,
    read_text,
    write_text,
)
from .source_patches import (
    patch_sources,
)
from .product_patches import (
    patch_product_sources,
)
from .clock import (
    patch_simulation_clock,
)


def patch_u3_observations(root: Path, dry_run: bool = False) -> list[Change]:
    """U3 generated sites, pinned-source anchors; applied after U1/U2 semantics."""
    if dry_run:
        with tempfile.TemporaryDirectory(prefix="cth3ds-u3-preview-") as temp:
            preview=Path(temp)/"upstream"
            shutil.copytree(root,preview,ignore=shutil.ignore_patterns(".git"))
            patch_sources(preview,False);patch_product_sources(preview,False)
            changes = patch_u3_observations(preview,False)
            changes.extend(patch_simulation_clock(preview))
            changes.extend(Change(path, "dual-screen-canvas") for path in patch_dual_screen(preview))
            return changes
    changes = []
    operations = [('CorsixTH/Src/sdl_core.cpp',
  '    do {\n      // CORSIXTH_3DS_BEGIN: bottom-event-filter',
  '    do {\n'
  '#ifdef CORSIXTH_3DS\n'
  '      cth3ds::RuntimeTimingScope u3_event(cth3ds::TimingStage::Event);\n'
  '#endif\n'
  '      // CORSIXTH_3DS_BEGIN: bottom-event-filter'),
 ('CorsixTH/Src/sdl_core.cpp',
  '    if (do_timer) {\n',
  '    if (do_timer) {\n'
  '#ifdef CORSIXTH_3DS\n'
  '      cth3ds::RuntimeTimingScope u3_logic(cth3ds::TimingStage::Logic);\n'
  '#endif\n'),
 ('CorsixTH/Src/sdl_core.cpp',
  '      do {\n        if (fps.track_fps) {',
  '      do {\n'
  '#ifdef CORSIXTH_3DS\n'
  '        cth3ds::runtime_begin_frame();\n'
  '        cth3ds::RuntimeTimingScope u3_render(cth3ds::TimingStage::Render);\n'
  '#endif\n'
  '        if (fps.track_fps) {'),
 ('CorsixTH/Src/sdl_core.cpp',
  '        cth3ds::runtime_after_frame();',
  '        u3_render.finish(res == LUA_OK);\n        cth3ds::runtime_after_frame(res == LUA_OK);'),
 ('CorsixTH/Src/sdl_core.cpp',
  '    // No events pending - a good time to do a bit of garbage collection\n    lua_gc(L, LUA_GCSTEP, 2);',
  '#ifdef CORSIXTH_3DS\n'
  '    if (!do_frame && fps.limit_fps) cth3ds::runtime_frame_skipped();\n'
  '    {\n'
  '      cth3ds::RuntimeTimingScope u3_gc(cth3ds::TimingStage::GC);\n'
  '      cth3ds::runtime_observe_memory("gc", "before", "incremental", cth3ds::MemoryGate::Operation);\n'
  '#endif\n'
  '    // No events pending - a good time to do a bit of garbage collection\n'
  '    lua_gc(L, LUA_GCSTEP, 2);\n'
  '#ifdef CORSIXTH_3DS\n'
  '      cth3ds::runtime_observe_memory("gc", "after", "incremental", cth3ds::MemoryGate::Operation);\n'
  '    }\n'
  '    cth3ds::runtime_flush_observations();\n'
  '#endif'),
 ('CorsixTH/Src/sdl_core.cpp',
  'leave_loop:\n',
  'leave_loop:\n#ifdef CORSIXTH_3DS\n  cth3ds::runtime_flush_observations(true);\n#endif\n'),
 ('CorsixTH/Src/th_map.cpp',
  '#include "th_map.h"\n',
  '#include "th_map.h"\n#ifdef CORSIXTH_3DS\n#include "3ds/runtime_3ds.hpp"\n#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '  SDL_RenderPresent(renderer);\n  FrameMark;',
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::RuntimeTimingScope u3_top(cth3ds::TimingStage::Top);\n'
  '  SDL_ClearError();\n'
  '#endif\n'
  '  SDL_RenderPresent(renderer);\n'
  '#ifdef CORSIXTH_3DS\n'
  '  // SDL2 present returns void. This proves completion without reported error;\n'
  '  // actual scanout/frame visibility is a separate device observation.\n'
  "  const bool u3_ok = *SDL_GetError() == '\\0';\n"
  '  u3_top.finish(u3_ok);\n'
  '  cth3ds::runtime_top_present_complete(u3_ok);\n'
  '  if (!u3_ok) return false;\n'
  '#endif\n'
  '  FrameMark;'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '  sprites = new (std::nothrow) sprite[sprite_count];\n',
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("vspr_decode", "descriptors-before", "sprite-sheet", '
  'cth3ds::MemoryGate::Operation, sprite_count * sizeof(sprite), true, 0, false, false);\n'
  '#endif\n'
  '  sprites = new (std::nothrow) sprite[sprite_count];\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("vspr_decode", "descriptors-after", "sprite-sheet", '
  'cth3ds::MemoryGate::Operation, sprite_count * sizeof(sprite), true, sprites ? sprite_count * sizeof(sprite) : '
  '0, true, sprites == nullptr);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '      std::vector<uint8_t> pData(pSprite->width * pSprite->height);',
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("vspr_decode", "pixels-before", "sprite-pixels", '
  'cth3ds::MemoryGate::Operation, pSprite->width * pSprite->height, true, 0, false, false);\n'
  '#endif\n'
  '      std::vector<uint8_t> pData(pSprite->width * pSprite->height);\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("vspr_decode", "pixels-after", "sprite-pixels", '
  'cth3ds::MemoryGate::Operation, pSprite->width * pSprite->height, true, pData.size(), true, false);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '          convertLegacySprite(pData.data(), pSprite->width * pSprite->height);',
  '          convertLegacySprite(pData.data(), pSprite->width * pSprite->height);\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("vspr_decode", "converted-after", "sprite-converted", '
  'cth3ds::MemoryGate::Operation, 0, false, 0, false, false);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '  delete[] sprites;\n  sprites = nullptr;',
  '  delete[] sprites;\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("release", "descriptors-after", "sprite-sheet", '
  'cth3ds::MemoryGate::Operation, 0, false, 0, true, false);\n'
  '#endif\n'
  '  sprites = nullptr;'),
 ('CorsixTH/Src/th_map.cpp',
  '  cells = new (std::nothrow) map_tile[iWidth * iHeight];\n',
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("map", "before", "cells", cth3ds::MemoryGate::Operation, '
  'static_cast<std::uint64_t>(iWidth) * iHeight * sizeof(map_tile), true, 0, false, false);\n'
  '#endif\n'
  '  cells = new (std::nothrow) map_tile[iWidth * iHeight];\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("map", "after", "cells", cth3ds::MemoryGate::Operation, '
  'static_cast<std::uint64_t>(iWidth) * iHeight * sizeof(map_tile), true, cells ? '
  'static_cast<std::uint64_t>(iWidth) * iHeight * sizeof(map_tile) : 0, true, cells == nullptr);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_map.cpp',
  '  original_cells = new (std::nothrow) map_tile[iWidth * iHeight];\n',
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("map", "before", "original_cells", cth3ds::MemoryGate::Operation, '
  'static_cast<std::uint64_t>(iWidth) * iHeight * sizeof(map_tile), true, 0, false, false);\n'
  '#endif\n'
  '  original_cells = new (std::nothrow) map_tile[iWidth * iHeight];\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("map", "after", "original_cells", cth3ds::MemoryGate::Operation, '
  'static_cast<std::uint64_t>(iWidth) * iHeight * sizeof(map_tile), true, original_cells ? '
  'static_cast<std::uint64_t>(iWidth) * iHeight * sizeof(map_tile) : 0, true, original_cells == nullptr);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '  uint32_t* pARGBPixels = new uint32_t[iWidth * iHeight];',
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("textures", "pixels-before", "ARGB", cth3ds::MemoryGate::Operation, '
  'static_cast<std::uint64_t>(iWidth) * iHeight * sizeof(uint32_t), true, 0, false, false);\n'
  '#endif\n'
  '  uint32_t* pARGBPixels = new uint32_t[iWidth * iHeight];\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("textures", "pixels-after", "ARGB", cth3ds::MemoryGate::Operation, '
  'static_cast<std::uint64_t>(iWidth) * iHeight * sizeof(uint32_t), true, static_cast<std::uint64_t>(iWidth) * '
  'iHeight * sizeof(uint32_t), true, false);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '  texture = SDL_CreateTexture(target->renderer, SDL_PIXELFORMAT_ABGR8888,\n'
  '                              SDL_TEXTUREACCESS_TARGET, iWidth, iHeight);',
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("textures", "create-before", "SDL-texture", cth3ds::MemoryGate::Operation, 0, '
  'false, 0, false, false);\n'
  '#endif\n'
  '  texture = SDL_CreateTexture(target->renderer, SDL_PIXELFORMAT_ABGR8888,\n'
  '                              SDL_TEXTUREACCESS_TARGET, iWidth, iHeight);\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("textures", "create-after", "SDL-texture", cth3ds::MemoryGate::Operation, 0, '
  'false, 0, false, false);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '  SDL_Texture* pTexture =\n'
  '      SDL_CreateTexture(renderer, pixel_format->format,\n'
  '                        SDL_TEXTUREACCESS_STATIC, iWidth, iHeight);',
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("textures", "create-before", "SDL-texture", cth3ds::MemoryGate::Operation, 0, '
  'false, 0, false, false);\n'
  '#endif\n'
  '  SDL_Texture* pTexture =\n'
  '      SDL_CreateTexture(renderer, pixel_format->format,\n'
  '                        SDL_TEXTUREACCESS_STATIC, iWidth, iHeight);\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("textures", "create-after", "SDL-texture", cth3ds::MemoryGate::Operation, 0, '
  'false, 0, false, false);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '    SDL_DestroyTexture(sprites[iNumber].texture);',
  '    SDL_DestroyTexture(sprites[iNumber].texture);\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("release", "texture-after", "SDL-texture", cth3ds::MemoryGate::Operation, 0, '
  'false, 0, false, false);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '    SDL_DestroyTexture(sprites[iNumber].alt_texture);',
  '    SDL_DestroyTexture(sprites[iNumber].alt_texture);\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("release", "texture-after", "SDL-texture", cth3ds::MemoryGate::Operation, 0, '
  'false, 0, false, false);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '      SDL_DestroyTexture(pSprite->alt_texture);',
  '      SDL_DestroyTexture(pSprite->alt_texture);\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("release", "texture-after", "SDL-texture", cth3ds::MemoryGate::Operation, 0, '
  'false, 0, false, false);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '    SDL_DestroyTexture(pCacheEntry->texture);',
  '    SDL_DestroyTexture(pCacheEntry->texture);\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("release", "texture-after", "SDL-texture", cth3ds::MemoryGate::Operation, 0, '
  'false, 0, false, false);\n'
  '#endif\n'),
 ('CorsixTH/Lua/persistance.lua',
  '  local dumped, result, err, obj = pcall(function()\n'
  '    return persist.dump(state, MakePermanentObjectsTable(false))\n'
  '  end)',
  '  if TH3DS then TH3DS.observe_memory("save","dump-before","persist","Operation") end\n'
  '  local dumped, result, err, obj = pcall(function()\n'
  '    return persist.dump(state, MakePermanentObjectsTable(false))\n'
  '  end)\n'
  '  if TH3DS then TH3DS.observe_memory("save","dump-after","persist","Operation") end'),
 ('CorsixTH/Lua/persistance.lua',
  '  local state = assert(persist.load(data, objtable))',
  '  if TH3DS then TH3DS.observe_memory("reload", "parse-before", "persist", "Operation") end\n'
  '  local state = assert(persist.load(data, objtable))\n'
  '  if TH3DS then TH3DS.observe_memory("reload", "parse-after", "persist", "Operation") end'),
 ('CorsixTH/Lua/persistance.lua',
  '  TheApp:afterLoad()',
  '  if TH3DS then TH3DS.observe_memory("reload", "afterLoad-before", "persist", "Operation") end\n'
  '  TheApp:afterLoad()\n'
  '  if TH3DS then TH3DS.observe_memory("reload", "afterLoad-after", "persist", "Operation") end'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '  uint8_t* pData = new uint8_t[iNewSize];',
  '#ifdef CORSIXTH_3DS\n'
  '  uint8_t* pData = nullptr;\n'
  '  try { pData = new uint8_t[iNewSize]; } catch (const std::bad_alloc&) {\n'
  '    cth3ds::runtime_observe_memory("vspr_decode", "allocation-failed", "pData", cth3ds::MemoryGate::Operation, '
  'iNewSize, true, 0, false, true);\n'
  '    throw;\n'
  '  }\n'
  '#else\n'
  '  uint8_t* pData = new uint8_t[iNewSize];\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '  uint32_t* pARGBPixels = new uint32_t[iWidth * iHeight];',
  '#ifdef CORSIXTH_3DS\n'
  '  uint32_t* pARGBPixels = nullptr;\n'
  '  try { pARGBPixels = new uint32_t[iWidth * iHeight]; } catch (const std::bad_alloc&) {\n'
  '    cth3ds::runtime_observe_memory("textures", "allocation-failed", "pARGBPixels", '
  'cth3ds::MemoryGate::Operation, static_cast<std::uint64_t>(iWidth) * iHeight * sizeof(uint32_t), true, 0, '
  'false, true);\n'
  '    throw;\n'
  '  }\n'
  '#else\n'
  '  uint32_t* pARGBPixels = new uint32_t[iWidth * iHeight];\n'
  '#endif\n'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '      std::vector<uint8_t> pData(pSprite->width * pSprite->height);',
  '#ifdef CORSIXTH_3DS\n'
  '      std::vector<uint8_t> pData;\n'
  '      try { pData.resize(pSprite->width * pSprite->height); } catch (const std::bad_alloc&) {\n'
  '        cth3ds::runtime_observe_memory("vspr_decode", "allocation-failed", "sprite-pixels", '
  'cth3ds::MemoryGate::Operation, pSprite->width * pSprite->height, true, 0, false, true);\n'
  '        throw;\n'
  '      }\n'
  '#else\n'
  '      std::vector<uint8_t> pData(pSprite->width * pSprite->height);\n'
  '#endif'),
 ('CorsixTH/Src/th_gfx_sdl.cpp',
  '  delete[] pARGBPixels;',
  '  delete[] pARGBPixels;\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("release", "pixels-after", "ARGB", cth3ds::MemoryGate::Operation, 0, false, '
  '0, true, false);\n'
  '#endif\n'),
 ('CorsixTH/Src/th_map.cpp',
  '  delete[] parcel_tile_counts;\n  delete[] parcel_adjacency_matrix;\n  delete[] purchasable_matrix;\n}',
  '  delete[] parcel_tile_counts;\n'
  '  delete[] parcel_adjacency_matrix;\n'
  '  delete[] purchasable_matrix;\n'
  '#ifdef CORSIXTH_3DS\n'
  '  cth3ds::runtime_observe_memory("release", "map-after", "level-map", cth3ds::MemoryGate::Operation, 0, false, '
  '0, true, false);\n'
  '#endif\n'
  '}'),
 ('CorsixTH/Lua/app.lua',
  '  local new_map = Map(self)',
  '  if TH3DS then TH3DS.observe_memory("map", "before", "new-map", "Operation") end\n'
  '  local new_map = Map(self)\n'
  '  if TH3DS then TH3DS.observe_memory("map", "after", "new-map", "Operation") end'),
 ('CorsixTH/Lua/app.lua',
  '  self.world = World(self, determineFreeBuildMode())',
  '  if TH3DS then TH3DS.operation_boundary(); TH3DS.observe_memory("world", "before", "world", "Operation") end\n'
  '  self.world = World(self, determineFreeBuildMode())\n'
  '  if TH3DS then TH3DS.operation_boundary(); TH3DS.observe_memory("world", "after", "world", "Operation") end'),
 ('CorsixTH/Lua/app.lua',
  '  self.world:createMapObjects(map_objects)',
  '  if TH3DS then TH3DS.operation_boundary(); TH3DS.observe_memory("world", "before", "map-objects", "Operation") end\n'
  '  self.world:createMapObjects(map_objects)\n'
  '  if TH3DS then TH3DS.operation_boundary(); TH3DS.observe_memory("world", "after", "map-objects", "Operation") end'),
 ('CorsixTH/Lua/persistance.lua',
  '  state.map:prepareForSave()',
  '  if TH3DS then TH3DS.observe_memory("save", "prepare-before", "map", "Operation") end\n'
  '  state.map:prepareForSave()\n'
  '  if TH3DS then TH3DS.observe_memory("save", "prepare-after", "map", "Operation") end'),
 ('CorsixTH/Lua/persistance.lua',
  '  local cleaned, cleanup_error = pcall(state.map.afterSave,state.map)',
  '  if TH3DS then TH3DS.observe_memory("save","afterSave-before","map","Operation") end\n'
  '  local cleaned, cleanup_error = pcall(state.map.afterSave,state.map)\n'
  '  if TH3DS then TH3DS.observe_memory("save","afterSave-after","map","Operation") end'),
 ('CorsixTH/Lua/persistance.lua',
  '  local data = SaveGame()',
  '  local data = SaveGame()\n'
  '  if TH3DS then TH3DS.observe_memory("save", "serialized", "state-string", "Operation", nil, #data) end'),
 ('CorsixTH/Lua/strings.lua',
  '82, 0x90) -- e-acute\n'
  'case(0x84, 0x8E) -- a-umlaut\n'
  'case(0x86, 0x8F) -- a-ring\n'
  'case(0x94, 0x99) -- o-umlaut\n'
  'case(0xA4, 0xA5) -- n-tilde\n'
  'local case_pattern = "\\195[\\128-\\191]" -- Unicode range [0xC0, 0xFF] as UTF-8\n'
  '\n'
  'local orig_upper = string.upper\n'
  'function string.upper(s) -- luacheck: ignore 122\n'
  '  return orig_upper(s:gsub(case_pattern, lower_to_upper))\n'
  'end\n'
  '\n'
  'local orig_lower = string.lower\n'
  'function string.lower(s) -- luacheck: ignore 122\n'
  '  return orig_lower(s:gsub(case_pattern, upper_to_lower))\n'
  'end\n',
  '82, 0x90) -- e-acute\n'
  'case(0x84, 0x8E) -- a-umlaut\n'
  'case(0x86, 0x8F) -- a-ring\n'
  'case(0x94, 0x99) -- o-umlaut\n'
  'case(0xA4, 0xA5) -- n-tilde\n'
  'local case_pattern = "\\195[\\128-\\191]" -- Unicode range [0xC0, 0xFF] as UTF-8\n'
  '\n'
  'local orig_upper = string.upper\n'
  'function string.upper(s) -- luacheck: ignore 122\n'
  '  return orig_upper(s:gsub(case_pattern, lower_to_upper))\n'
  'end\n'
  '\n'
  'local orig_lower = string.lower\n'
  'function string.lower(s) -- luacheck: ignore 122\n'
  '  return orig_lower(s:gsub(case_pattern, upper_to_lower))\n'
  'end\n'
  '\n'
  '-- CORSIXTH_3DS_BEGIN: U3-actual-loader-spans\n'
  'do\n'
  '  do\n'
  '    local original = assert(Strings.init)\n'
  '    Strings.init = function(...)\n'
  '      if not TH3DS then return original(...) end\n'
  '      local token = TH3DS.span_begin("load")\n'
  '      TH3DS.observe_memory("language_discovery", "before", "Strings:init", "Operation")\n'
  '      local result = table.pack(pcall(original, ...))\n'
  '      local success = result[1] and result[2] ~= false\n'
  '      TH3DS.observe_memory("language_discovery", success and "after" or "failed", "Strings:init", '
  '"Operation")\n'
  '      TH3DS.span_end(token, success)\n'
  '      \n'
  '      if not result[1] then error(result[2], 0) end\n'
  '      return table.unpack(result, 2, result.n)\n'
  '    end\n'
  '  end\n'
  '  do\n'
  '    local original = assert(Strings.load)\n'
  '    Strings.load = function(...)\n'
  '      if not TH3DS then return original(...) end\n'
  '      local token = TH3DS.span_begin("load")\n'
  '      TH3DS.observe_memory("language_selected", "before", "Strings:load", "Operation")\n'
  '      local result = table.pack(pcall(original, ...))\n'
  '      local success = result[1] and result[2] ~= false\n'
  '      TH3DS.observe_memory("language_selected", success and "after" or "failed", "Strings:load", "Operation")\n'
  '      TH3DS.span_end(token, success)\n'
  '      \n'
  '      if not result[1] then error(result[2], 0) end\n'
  '      return table.unpack(result, 2, result.n)\n'
  '    end\n'
  '  end\n'
  'end\n'
  '-- CORSIXTH_3DS_END: U3-actual-loader-spans\n'),
 ('CorsixTH/Lua/audio.lua',
  ')\n'
  '  if jukebox then\n'
  '    jukebox:updatePlayButton()\n'
  '  end\n'
  'end\n'
  '\n'
  'function Audio:reserveChannel()\n'
  '  if self.sound_fx then\n'
  '    return self.sound_fx:reserveChannel()\n'
  '  else\n'
  '    return -1\n'
  '  end\n'
  'end\n'
  '\n'
  'function Audio:releaseChannel(channel)\n'
  '  if self.sound_fx and channel > -1 then\n'
  '    self.sound_fx:releaseChannel(channel)\n'
  '  end\n'
  'end\n'
  '\n'
  'function Audio:destroy()\n'
  '  self.has_bg_music = false\n'
  '  self.not_loaded = not TheApp.config.audio\n'
  '  self.speech_file_name = nil\n'
  '  self.sound_fx = nil\n'
  '  SDL.audio.destroy()\n'
  'end\n',
  ')\n'
  '  if jukebox then\n'
  '    jukebox:updatePlayButton()\n'
  '  end\n'
  'end\n'
  '\n'
  'function Audio:reserveChannel()\n'
  '  if self.sound_fx then\n'
  '    return self.sound_fx:reserveChannel()\n'
  '  else\n'
  '    return -1\n'
  '  end\n'
  'end\n'
  '\n'
  'function Audio:releaseChannel(channel)\n'
  '  if self.sound_fx and channel > -1 then\n'
  '    self.sound_fx:releaseChannel(channel)\n'
  '  end\n'
  'end\n'
  '\n'
  'function Audio:destroy()\n'
  '  self.has_bg_music = false\n'
  '  self.not_loaded = not TheApp.config.audio\n'
  '  self.speech_file_name = nil\n'
  '  self.sound_fx = nil\n'
  '  SDL.audio.destroy()\n'
  'end\n'
  '\n'
  '-- CORSIXTH_3DS_BEGIN: U3-actual-loader-spans\n'
  'do\n'
  '  do\n'
  '    local original = assert(Audio.initSpeech)\n'
  '    Audio.initSpeech = function(...)\n'
  '      if not TH3DS then return original(...) end\n'
  '      local token = TH3DS.span_begin("load")\n'
  '      TH3DS.observe_memory("sound_index", "before", "Audio:initSpeech", "Operation")\n'
  '      local result = table.pack(pcall(original, ...))\n'
  '      local success = result[1] and result[2] ~= false\n'
  '      TH3DS.observe_memory("sound_index", success and "after" or "failed", "Audio:initSpeech", "Operation")\n'
  '      TH3DS.span_end(token, success)\n'
  '      \n'
  '      if not result[1] then error(result[2], 0) end\n'
  '      return table.unpack(result, 2, result.n)\n'
  '    end\n'
  '  end\n'
  'end\n'
  '-- CORSIXTH_3DS_END: U3-actual-loader-spans\n'),
 ('CorsixTH/Lua/graphics.lua',
  '     local n = (f - f1) / (f2 - f1)\n'
  '        setMarkerFramePosition(false, x1, y1, x2, y2, n)\n'
  '      else\n'
  '        setMarkerFramePosition(true, x1, y1)\n'
  '      end\n'
  '      frame = self.anims:getNextFrame(frame)\n'
  '    end\n'
  '  else\n'
  '    error("Invalid arguments to setMarker", 2)\n'
  '  end\n'
  'end\n'
  '\n'
  '-- Kept for load compatibility\n'
  'function Graphics:loadPalette(_, name)\n'
  '  -- Was named PREF01V.PAL in ui.lua until version 240\n'
  '  if name == "PREF01V.PAL" then\n'
  '    name = "Pref01V.pal"\n'
  '  end\n'
  '  return self:getPalette(name)\n'
  'end\n',
  '     local n = (f - f1) / (f2 - f1)\n'
  '        setMarkerFramePosition(false, x1, y1, x2, y2, n)\n'
  '      else\n'
  '        setMarkerFramePosition(true, x1, y1)\n'
  '      end\n'
  '      frame = self.anims:getNextFrame(frame)\n'
  '    end\n'
  '  else\n'
  '    error("Invalid arguments to setMarker", 2)\n'
  '  end\n'
  'end\n'
  '\n'
  '-- Kept for load compatibility\n'
  'function Graphics:loadPalette(_, name)\n'
  '  -- Was named PREF01V.PAL in ui.lua until version 240\n'
  '  if name == "PREF01V.PAL" then\n'
  '    name = "Pref01V.pal"\n'
  '  end\n'
  '  return self:getPalette(name)\n'
  'end\n'
  '\n'
  '-- CORSIXTH_3DS_BEGIN: U3-actual-loader-spans\n'
  'do\n'
  '  do\n'
  '    local original = assert(Graphics.loadAnimations)\n'
  '    Graphics.loadAnimations = function(...)\n'
  '      if not TH3DS then return original(...) end\n'
  '      local token = TH3DS.span_begin("load")\n'
  '      TH3DS.observe_memory("vspr_decode", "before", "Graphics:loadAnimations", "Operation")\n'
  '      local result = table.pack(pcall(original, ...))\n'
  '      local success = result[1] and result[2] ~= false\n'
  '      TH3DS.observe_memory("vspr_decode", success and "after" or "failed", "Graphics:loadAnimations", '
  '"Operation")\n'
  '      TH3DS.span_end(token, success)\n'
  '      \n'
  '      if not result[1] then error(result[2], 0) end\n'
  '      return table.unpack(result, 2, result.n)\n'
  '    end\n'
  '  end\n'
  '  do\n'
  '    local original = assert(Graphics.loadSpriteTable)\n'
  '    Graphics.loadSpriteTable = function(...)\n'
  '      if not TH3DS then return original(...) end\n'
  '      local token = TH3DS.span_begin("load")\n'
  '      TH3DS.observe_memory("vspr_table", "before", "Graphics:loadSpriteTable", "Operation")\n'
  '      local result = table.pack(pcall(original, ...))\n'
  '      local success = result[1] and result[2] ~= false\n'
  '      TH3DS.observe_memory("vspr_table", success and "after" or "failed", "Graphics:loadSpriteTable", '
  '"Operation")\n'
  '      TH3DS.span_end(token, success)\n'
  '      \n'
  '      if not result[1] then error(result[2], 0) end\n'
  '      return table.unpack(result, 2, result.n)\n'
  '    end\n'
  '  end\n'
  'end\n'
  '-- CORSIXTH_3DS_END: U3-actual-loader-spans\n'),
 ('CorsixTH/Lua/app.lua',
  'nderer: %s\\n",\n'
  '      table.concat(comp_details, ", "), self.video:getRendererDetails())\n'
  '  local running = string.format("%s run with api version: %s, game version: %s, savegame version: %s\\n",\n'
  '      compile_opts.jit or _VERSION, tostring(corsixth.require("api_version")),\n'
  '      self:getReleaseString(), tostring(SAVEGAME_VERSION))\n'
  '  return (compiled .. running)\n'
  'end\n'
  '\n'
  '-- Do not remove, for savegame compatibility < r1891\n'
  'local app_confirm_quit_stub = --[[persistable:app_confirm_quit]] function()\n'
  'end\n',
  'nderer: %s\\n",\n'
  '      table.concat(comp_details, ", "), self.video:getRendererDetails())\n'
  '  local running = string.format("%s run with api version: %s, game version: %s, savegame version: %s\\n",\n'
  '      compile_opts.jit or _VERSION, tostring(corsixth.require("api_version")),\n'
  '      self:getReleaseString(), tostring(SAVEGAME_VERSION))\n'
  '  return (compiled .. running)\n'
  'end\n'
  '\n'
  '-- Do not remove, for savegame compatibility < r1891\n'
  'local app_confirm_quit_stub = --[[persistable:app_confirm_quit]] function()\n'
  'end\n'
  '\n'
  '-- CORSIXTH_3DS_BEGIN: U3-actual-loader-spans\n'
  'do\n'
  '  do\n'
  '    local original = assert(App._loadLevel)\n'
  '    App._loadLevel = function(...)\n'
  '      if not TH3DS then return original(...) end\n'
  '      local token = TH3DS.span_begin("load")\n'
  '      TH3DS.operation_boundary(); TH3DS.observe_memory("world", "before", "App:_loadLevel", "Operation")\n'
  '      local result = table.pack(pcall(original, ...))\n'
  '      local success = result[1] and result[2] ~= false\n'
  '      TH3DS.operation_boundary(); TH3DS.observe_memory("world", success and "after" or "failed", "App:_loadLevel", "Operation")\n'
  '      TH3DS.span_end(token, success)\n'
  '      TH3DS.flush_observations()\n'
  '      if not result[1] then error(result[2], 0) end\n'
  '      return table.unpack(result, 2, result.n)\n'
  '    end\n'
  '  end\n'
  '  do\n'
  '    local original = assert(App.loadMainMenu)\n'
  '    App.loadMainMenu = function(...)\n'
  '      if not TH3DS then return original(...) end\n'
  '      local token = TH3DS.span_begin("load")\n'
  '      TH3DS.operation_boundary(); TH3DS.observe_memory("release", "before", "App:loadMainMenu", "Operation")\n'
  '      local result = table.pack(pcall(original, ...))\n'
  '      local success = result[1] and result[2] ~= false\n'
  '      TH3DS.operation_boundary(); TH3DS.observe_memory("release", success and "after" or "failed", "App:loadMainMenu", "Operation")\n'
  '      TH3DS.span_end(token, success)\n'
  '      TH3DS.flush_observations()\n'
  '      if not result[1] then error(result[2], 0) end\n'
  '      return table.unpack(result, 2, result.n)\n'
  '    end\n'
  '  end\n'
  'end\n'
  '-- CORSIXTH_3DS_END: U3-actual-loader-spans\n'),
 ('CorsixTH/Lua/strings.lua',
  '      local result, err = loadfile_envcall(path .. file)',
  '      if TH3DS then TH3DS.observe_memory("language_discovery", "compile-before", file, "Operation") end\n'
  '      local result, err = loadfile_envcall(path .. file)\n'
  '      if TH3DS then TH3DS.observe_memory("language_discovery", "compile-after", file, "Operation") end'),
 ('CorsixTH/Lua/graphics.lua',
  '    data_tab = self.app:readDataFile(dir, name .. ".tab")',
  '    if TH3DS then TH3DS.observe_memory("vspr_table", "read-before", name, "Operation") end\n'
  '    data_tab = self.app:readDataFile(dir, name .. ".tab")\n'
  '    if TH3DS then TH3DS.observe_memory("vspr_table", "read-after", name, "Operation", nil, #data_tab) end'),
 ('CorsixTH/Lua/graphics.lua',
  '    data_dat = self.app:readDataFile(dir, name .. ".dat")',
  '    if TH3DS then TH3DS.observe_memory("vspr_data", "read-before", name, "Operation") end\n'
  '    data_dat = self.app:readDataFile(dir, name .. ".dat")\n'
  '    if TH3DS then TH3DS.observe_memory("vspr_data", "read-after", name, "Operation", nil, #data_dat) end')]
    operations.extend([
        ('CorsixTH/Src/sdl_core.cpp', '        int res = lua_pcall(L, nargs + 1, 1, -3 - nargs);', '        int res = lua_pcall(L, nargs + 1, 1, -3 - nargs);\n#ifdef CORSIXTH_3DS\n        u3_event.finish(res == LUA_OK);\n#endif'),
        ('CorsixTH/Src/sdl_core.cpp', '\n      int res = lua_pcall(L, 2, 1, -4);', '\n      int res = lua_pcall(L, 2, 1, -4);\n#ifdef CORSIXTH_3DS\n      u3_logic.finish(res == LUA_OK);\n#endif'),
    ])
    pending = {}
    already_done = {relative for relative, _, _ in operations if "CORSIXTH_3DS_U3_OBSERVATIONS_V1" in read_text(root / relative)}
    for relative, before, after in operations:
        if relative in already_done: continue
        path = root / relative
        content = pending.get(relative, read_text(path))
        if after in content:
            continue
        if "-- CORSIXTH_3DS_BEGIN: U3-actual-loader-spans" in after and "-- CORSIXTH_3DS_BEGIN: U3-actual-loader-spans" not in before and "-- CORSIXTH_3DS_BEGIN: U3-actual-loader-spans" in content:
            continue
        if content.count(before) != 1:
            raise IntegrationError("U3 observation anchor mismatch: " + relative)
        if relative=='CorsixTH/Lua/app.lua' and 'U3-actual-loader-spans' in after:
            after=after.replace('"App:_loadLevel"', '\'level:\'..tostring((...).world and (...).world.level_number or \'loading\')').replace('"App:loadMainMenu"','"menu"')
        pending[relative] = content.replace(before, after, 1)
    for relative, content in pending.items():
        prefix = "--" if relative.endswith(".lua") else "//"
        if relative in ('CorsixTH/Lua/strings.lua','CorsixTH/Lua/graphics.lua'):
            content = 'local ok, TH3DS = pcall(require,"th3ds")\nif not ok or not TH3DS.is_platform() then TH3DS=nil end\n' + content
        elif relative.endswith('.lua'):
            content = content.replace('local IS_3DS = th3ds_ok and TH3DS.is_platform()', 'local IS_3DS = th3ds_ok and TH3DS.is_platform()\nif not IS_3DS then TH3DS=nil end').replace('local IS_3DS = native_ok and TH3DS.is_platform()', 'local IS_3DS = native_ok and TH3DS.is_platform()\nif not IS_3DS then TH3DS=nil end')
        content += "\n" + prefix + " CORSIXTH_3DS_U3_OBSERVATIONS_V1\n"
        write_text(root / relative, content, dry_run)
        changes.append(Change(relative, "patch"))
    return changes
