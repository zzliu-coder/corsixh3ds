"""Ordered GPU backend at the real renderer, leaving the software reference intact."""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError

SITES=(
 ('  SDL_RendererInfo info;\n  SDL_GetRendererInfo(renderer, &info);',
  '#ifdef CORSIXTH_3DS_GPU\n  (void)cth3ds::gpu_initialize();\n#endif\n'
  '  SDL_RendererInfo info;\n  SDL_GetRendererInfo(renderer, &info);'),
 ('bool render_target::start_frame() {',
  'bool render_target::start_frame() {\n#ifdef CORSIXTH_3DS_GPU\n'
  '  if (cth3ds::gpu_active() && !cth3ds::gpu_begin()) return false;\n#endif'),
 ('const char* render_target::get_renderer_details() const {',
  'const char* render_target::get_renderer_details() const {\n#ifdef CORSIXTH_3DS_GPU\n'
  '  if (cth3ds::gpu_active()) return "citro2d-ordered-canvas";\n#endif'),
 ('  supports_target_textures = (info.flags & SDL_RENDERER_TARGETTEXTURE) != 0;',
  '  supports_target_textures = (info.flags & SDL_RENDERER_TARGETTEXTURE) != 0;\n'
  '#ifdef CORSIXTH_3DS_GPU\n'
  '  if (cth3ds::gpu_active()) supports_target_textures = false; // direct ordered canvas\n#endif'),
)

def patch_render_gpu(root: Path,dry_run=False):
    path=root/'CorsixTH/Src/th_gfx_sdl.cpp'
    old=text=path.read_text()
    for before,after in SITES:
        if after not in text:text=replace_exact(text,before,after,'GPU real renderer entry')
    if text==old:return []
    if not dry_run:path.write_text(text)
    return ['CorsixTH/Src/th_gfx_sdl.cpp']

def check_render_gpu(root):
    try:return ['GPU renderer site missing: '+p for p in patch_render_gpu(root,True)]
    except (OSError,SoundPatchError) as error:return [str(error)]
