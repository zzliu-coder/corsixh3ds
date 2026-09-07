"""Own real logical pixels; physical windows are presentation-only surfaces."""
from pathlib import Path
from sound_lifetime import SoundPatchError, replace_exact

OLD_PRESENT = '''#ifdef CORSIXTH_3DS
  cth3ds::RuntimeTimingScope u3_top(cth3ds::TimingStage::Top);
  SDL_ClearError();
#endif
  SDL_RenderPresent(renderer);
#ifdef CORSIXTH_3DS
  // SDL2 present returns void. This proves completion without reported error;
  // actual scanout/frame visibility is a separate device observation.
  const bool u3_ok = *SDL_GetError() == '\\0';
  u3_top.finish(u3_ok);
  cth3ds::runtime_top_present_complete(u3_ok);
  if (!u3_ok) return false;
#endif'''
NEW_PRESENT = '''#ifdef CORSIXTH_3DS
  // R46: complete software drawing before the presentation timer starts.
  // This renderer owns a surface, not a window; SDL_RenderPresent is not the
  // surface-to-LCD operation. Flush before accessing these pixels directly.
  if (SDL_RenderFlush(renderer) != 0) {
    cth3ds::runtime_top_present_complete(false);
    return false;
  }
  if (!cth3ds::runtime_present_game(cursor_x, cursor_y)) return false;
#else
  SDL_RenderPresent(renderer);
#endif'''


def transform_cpp(text):
    text = replace_exact(text, '  renderer = SDL_CreateRenderer(window, -1, iRendererFlags);', '''#ifdef CORSIXTH_3DS
  // CORSIXTH_3DS_OWNED_CANVAS_R46: textures and drawing use native ABGR pixels.
  // Each LCD receives a crop/reduction after drawing, never a per-sprite shrink.
  (void)iRendererFlags;
  game_surface = SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, SDL_PIXELFORMAT_ABGR8888);
  renderer = game_surface ? SDL_CreateSoftwareRenderer(game_surface) : nullptr;
  if (!renderer) {
    const std::string error = SDL_GetError();
    SDL_FreeSurface(game_surface); game_surface = nullptr;
    SDL_DestroyWindow(window); window = nullptr;
    SDL_FreeFormat(pixel_format); pixel_format = nullptr;
    throw std::runtime_error(error);
  }
#else
  renderer = SDL_CreateRenderer(window, -1, iRendererFlags);
#endif''', 'owned game canvas')
    text = replace_exact(text, '                            SDL_WINDOWPOS_UNDEFINED, width, height,\n                            window_flags);', '''                            SDL_WINDOWPOS_UNDEFINED,
#ifdef CORSIXTH_3DS
                            400, 240,
#else
                            width, height,
#endif
                            window_flags);''', 'physical upper window size')
    text = replace_exact(text, '  cth3ds::runtime_set_game_window(window);',
                         '  cth3ds::runtime_set_game_window(window);\n  cth3ds::runtime_set_game_canvas(game_surface);', 'borrow canvas')
    text = replace_exact(text, '  SDL_SetWindowMinimumSize(window, params.min_width, params.min_height);\n  SDL_RenderSetLogicalSize(renderer, width, height);', '''#ifndef CORSIXTH_3DS
  SDL_SetWindowMinimumSize(window, params.min_width, params.min_height);
#endif
  SDL_RenderSetLogicalSize(renderer, width, height);''', 'physical window minimum')
    text = replace_exact(text, 'render_target::~render_target() {\n  zoom_buffer.reset();', '''render_target::~render_target() {
#ifdef CORSIXTH_3DS
  cth3ds::runtime_set_game_canvas(nullptr);
  cth3ds::runtime_set_game_window(nullptr);
#endif
  zoom_buffer.reset();''', 'detach borrowed pixels before destruction')
    text = replace_exact(text, '  if (window) {\n    SDL_DestroyWindow(window);', '''#ifdef CORSIXTH_3DS
  SDL_FreeSurface(game_surface);
  game_surface = nullptr;
#endif
  if (window) {
    SDL_DestroyWindow(window);''', 'destroy canvas after renderer')
    text = replace_exact(text, 'bool render_target::update(const render_target_creation_params& params) {', '''bool render_target::update(const render_target_creation_params& params) {
#ifdef CORSIXTH_3DS
  // A physical LCD cannot be resized to the desktop logical canvas. Keep the
  // renderer and its textures attached to the one fixed-size logical surface.
  if (params.width != 640 || params.height != 480) return false;
  width = params.width; height = params.height;
  return SDL_RenderSetLogicalSize(renderer, width, height) == 0;
#endif''', 'fixed logical dimensions')
    return replace_exact(text, OLD_PRESENT, NEW_PRESENT, 'flush then present owned pixels')


def transform_app(text):
    old = "'level:'..tostring((...).world and (...).world.level_number or 'loading')"
    new = "'level:'..tostring((...).map and (...).map.level_number or 'loading')"
    if text.count(old) == 2 and new not in text:
        return text.replace(old, new)
    if old not in text and text.count(new) == 2:
        return text
    raise SoundPatchError('expected exactly two complete level identity observations')


def patch_dual_screen(root: Path, dry_run=False):
    transforms = {
        'CorsixTH/Src/th_gfx_sdl.cpp': transform_cpp,
        'CorsixTH/Src/th_gfx_sdl.h': lambda text: replace_exact(text,
            '  SDL_Renderer* renderer{nullptr};',
            '  SDL_Renderer* renderer{nullptr};\n#ifdef CORSIXTH_3DS\n  SDL_Surface* game_surface{nullptr}; // owned; destroyed after renderer\n#endif',
            'owned surface member'),
        'CorsixTH/Lua/app.lua': transform_app,
    }
    changed = []
    for relative, transform in transforms.items():
        path = root / relative
        old = path.read_text(encoding='utf-8')
        new = transform(old)
        if old != new:
            changed.append(relative)
            if not dry_run: path.write_text(new, encoding='utf-8')
    return changed


def check_dual_screen(root):
    try:
        return ['owned canvas patch missing: '+name for name in patch_dual_screen(root, True)]
    except (OSError, SoundPatchError) as exc:
        return [str(exc)]
