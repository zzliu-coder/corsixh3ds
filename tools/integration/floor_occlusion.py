"""R73 bounded fullscreen floor omission. No whole-map or Window draw skip."""
from pathlib import Path
from sound_lifetime import replace_exact


def replace(text, old, new, label):
    return text if new in text else replace_exact(text, old, new, 'R73 ' + label)


def transform(name, text):
    if name == 'Src/th_gfx_sdl.h':
        text = replace(text, '  //! Should bitmaps be scaled?', '''#ifdef CORSIXTH_3DS
  bool opaque_canvas_geometry() const noexcept {
    return renderer && game_surface && width == 640 && height == 480 &&
      !current_target && !zoom_buffer && clip_rects.empty() &&
      global_scale_factor == 1.0 && (!scale_bitmaps || bitmap_scale_factor == 1.0);
  }
#endif

  //! Should bitmaps be scaled?''', 'canvas proof')
        text = replace(text, '  raw_bitmap() = default;', '''  raw_bitmap() = default;
#ifdef CORSIXTH_3DS
  bool opaque_canvas_for(render_target* canvas) const noexcept;
#endif''', 'loaded bitmap proof')
        text = replace(text, '  //! Image stored in SDL format for quick rendering.', '''#ifdef CORSIXTH_3DS
  bool opaque_canvas{false};
#endif
  //! Image stored in SDL format for quick rendering.''', 'bitmap proof storage')
    elif name == 'Src/th_gfx_sdl.cpp':
        text = replace(text, 'raw_bitmap::~raw_bitmap() {', '''#ifdef CORSIXTH_3DS
bool raw_bitmap::opaque_canvas_for(render_target* canvas) const noexcept {
#ifdef CORSIXTH_3DS_GPU
  return cth3ds::gpu_active() && opaque_canvas && texture && SDL_GetTextureUserData(texture) && target == canvas && canvas &&
    width == 640 && height == 480 && canvas->opaque_canvas_geometry();
#else
  (void)canvas;
  return false; // Software fallback retains the complete original map draw.
#endif
}
#endif

raw_bitmap::~raw_bitmap() {''', 'active GPU proof')
        text = replace(text, '''void raw_bitmap::set_palette(const palette* pPalette) {
  bitmap_palette = pPalette;''', '''void raw_bitmap::set_palette(const palette* pPalette) {
#ifdef CORSIXTH_3DS
  opaque_canvas = false;
#endif
  bitmap_palette = pPalette;''', 'palette proof invalidation')
    elif name == 'Src/th_lua_gfx.cpp':
        text = replace(text, 'int l_rawbitmap_draw(lua_State* L) {', '''#ifdef CORSIXTH_3DS
int l_rawbitmap_opaque_canvas(lua_State* L) {
  auto* bitmap = luaT_testuserdata<raw_bitmap>(L);
  auto* canvas = luaT_testuserdata<render_target>(L, 2);
  lua_pushboolean(L, bitmap->opaque_canvas_for(canvas));
  return 1;
}
#endif

int l_rawbitmap_draw(lua_State* L) {''', 'bitmap proof bridge')
        text = replace(text, '    lcb.add_function(l_rawbitmap_draw, "draw", lua_metatable::surface);', '''    lcb.add_function(l_rawbitmap_draw, "draw", lua_metatable::surface);
#ifdef CORSIXTH_3DS
    lcb.add_function(l_rawbitmap_opaque_canvas, "opaqueCanvas", lua_metatable::surface);
#endif''', 'bitmap proof registration')
    elif name == 'Src/th_map.h':
        text = replace(text, '            int iHeight, int iCanvasX, int iCanvasY) const;',
            '            int iHeight, int iCanvasX, int iCanvasY, bool skip_opaque_floor = false) const;', 'map declaration')
    elif name == 'Src/th_map.cpp':
        text = replace(text, '''void level_map::draw(render_target* pCanvas, int iScreenX, int iScreenY,
                     int iWidth, int iHeight, int iCanvasX,
                     int iCanvasY) const {''', '''void level_map::draw(render_target* pCanvas, int iScreenX, int iScreenY,
                     int iWidth, int iHeight, int iCanvasX,
                     int iCanvasY, bool skip_opaque_floor) const {''', 'map definition')
        text = replace(text, '  draw_floor(pCanvas, iScreenX, iScreenY, iWidth, iHeight, iCanvasX, iCanvasY);', '''#ifdef CORSIXTH_3DS
  if (!skip_opaque_floor)
#else
  (void)skip_opaque_floor;
#endif
  draw_floor(pCanvas, iScreenX, iScreenY, iWidth, iHeight, iCanvasX, iCanvasY);''', 'only floor pass')
    elif name == 'Src/th_lua_map.cpp':
        text = replace(text, '''             static_cast<int>(luaL_optinteger(L, 8, 0)));''', '''             static_cast<int>(luaL_optinteger(L, 8, 0)),
#ifdef CORSIXTH_3DS
             lua_type(L, 9) == LUA_TBOOLEAN && lua_toboolean(L, 9)
#else
             false
#endif
             );''', 'map explicit default')
    elif name == 'Lua/map.lua':
        text = replace(text, '''function Map:draw(canvas, sx, sy, sw, sh, dx, dy)
  -- All the heavy work is done by C code:
  self.th:draw(canvas, sx, sy, sw, sh, dx, dy)''', '''function Map:draw(canvas, sx, sy, sw, sh, dx, dy, skip_opaque_floor)
  -- All the heavy work is done by C code:
  self.th:draw(canvas, sx, sy, sw, sh, dx, dy, skip_opaque_floor == true)''', 'Lua map per call')
    elif name == 'Lua/game_ui.lua':
        text = replace(text, 'function GameUI:draw(canvas)', '''-- Optional optimization; a missing platform module preserves the full draw.
local r73_floor_ok, r73_floor = pcall(require, "3ds.floor_occlusion")
if not r73_floor_ok then r73_floor = nil end

function GameUI:draw(canvas)''', 'GameUI local gate')
        text = replace(text, '''    app.map:draw(canvas, dx, dy, math.ceil(config.width / zoom), math.ceil(config.height / zoom), 0, 0)''', '''    local skip_floor = r73_floor and r73_floor.covered(self, canvas) or false
    app.map:draw(canvas, dx, dy, math.ceil(config.width / zoom), math.ceil(config.height / zoom), 0, 0, skip_floor)''', 'top map only')
    registration = {
        'Lua/window.lua': 'Window', 'Lua/map.lua': 'Map',
        'Lua/dialogs/bottom_panel.lua': 'UIBottomPanel',
        'Lua/dialogs/adviser.lua': 'UIAdviser', 'Lua/dialogs/menu.lua': 'UIMenuBar',
        'Lua/dialogs/subtitles.lua': 'Subtitles',
        'Lua/dialogs/fullscreen/hospital_policy.lua': 'UIPolicy',
        'Lua/dialogs/fullscreen/progress_report.lua': 'UIProgressReport',
        'Lua/dialogs/fullscreen/research_policy.lua': 'UIResearch',
        'Lua/dialogs/fullscreen/staff_management.lua': 'UIStaffManagement',
    }.get(name)
    if registration:
        block = f'''\n-- R73 fixed draw identity; module absence leaves normal drawing enabled.
do
  local ok, gate = pcall(require, "3ds.floor_occlusion")
  if ok then gate.remember("{registration}", {registration}) end
end
'''
        if block not in text: text += block
    return text


FILES = ('Src/th_gfx_sdl.h', 'Src/th_gfx_sdl.cpp', 'Src/th_lua_gfx.cpp',
         'Src/th_map.h', 'Src/th_map.cpp', 'Src/th_lua_map.cpp',
         'Lua/game_ui.lua', 'Lua/map.lua', 'Lua/window.lua',
         'Lua/dialogs/bottom_panel.lua', 'Lua/dialogs/adviser.lua',
         'Lua/dialogs/menu.lua', 'Lua/dialogs/subtitles.lua',
         'Lua/dialogs/fullscreen/hospital_policy.lua',
         'Lua/dialogs/fullscreen/progress_report.lua',
         'Lua/dialogs/fullscreen/research_policy.lua',
         'Lua/dialogs/fullscreen/staff_management.lua')


def patch_floor_occlusion(root: Path, dry_run=False):
    changed = []
    for name in FILES:
        path = root / 'CorsixTH' / name
        # The historical 44-file syntax fixture intentionally has no complete
        # UI. Missing registrations cannot enable the gate. Full A2 tests use
        # the fixed complete originals for every FILES entry.
        if not path.exists(): continue
        original = path.read_text()
        updated = transform(name, original)
        if original != updated:
            changed.append(path.relative_to(root).as_posix())
            if not dry_run: path.write_text(updated)
    return changed


def check_floor_occlusion(root):
    return ['R73 floor contract missing: ' + name for name in patch_floor_occlusion(root, True)]
