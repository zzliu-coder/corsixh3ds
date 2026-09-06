"""Run the generated production renderer lifecycle using real SDL2 pixels.

HID, libctru scanout and visible readability are separate device gates.
Only runtime callbacks and unused cursor/temporary-texture types are harnessed.
"""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from integrate_corsixth import main as integrate
from test_playable_path import original_sources

HARNESS = r"""
#include <SDL.h>
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include "cth3ds/framebuffer_scaler.hpp"
#define FrameMark
static SDL_Surface* borrowed = nullptr;
static SDL_Window* registered_window = nullptr;
static bool callback_ok = true;
static bool allow_present = true;
static cth3ds::Vec2i pointer{};
namespace cth3ds {
void runtime_set_game_window(SDL_Window* w) { registered_window = w; }
void runtime_set_game_canvas(SDL_Surface* s) { borrowed = s; }
void runtime_top_present_complete(bool ok) { callback_ok = ok; }
bool runtime_present_game(int x, int y) {
  pointer = {x,y};
  return allow_present;
}
}
struct render_target_creation_params {
  int width=640,height=480,min_width=640,min_height=480;
  bool direct_zoom=true,present_immediate=true,fullscreen=true;
};
struct render_target {
  int width=0,height=0,cursor_x=320,cursor_y=240;
  bool direct_zoom=false,supports_target_textures=false,apply_opengl_clip_fix=false;
  bool blue_filter_active=false;
  SDL_PixelFormat* pixel_format=nullptr;
  SDL_Window* window=nullptr;
  SDL_Renderer* renderer=nullptr;
  SDL_Surface* game_surface=nullptr;
  struct unused_cursor { void draw(render_target*,int,int) {} };
  unused_cursor* game_cursor=nullptr;
  std::unique_ptr<int> zoom_buffer;
  void destroy_intermediate_textures() {}
  render_target(const render_target_creation_params&);
  ~render_target();
  bool update(const render_target_creation_params&);
  bool end_frame();
};
"""

MAIN = r"""
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s / %s\n",__LINE__,#x,SDL_GetError()); return 1; } } while(0)
int main() {
  SDL_setenv("SDL_VIDEODRIVER","dummy",1);
  CHECK(SDL_Init(SDL_INIT_VIDEO)==0);
  CHECK(std::strcmp(SDL_GetCurrentVideoDriver(),"dummy")==0);
  std::array<uint32_t,400*240> top{};
  std::array<uint32_t,320*240> bottom{};
  for (int lifetime=0;lifetime<20;++lifetime) {
    {
      render_target target{render_target_creation_params{}};
      CHECK(borrowed==target.game_surface && registered_window==target.window);
      CHECK(borrowed->w==640 && borrowed->h==480 && borrowed->pitch==640*4);
      int rw=0,rh=0; CHECK(SDL_GetRendererOutputSize(target.renderer,&rw,&rh)==0);
      CHECK(rw==640 && rh==480);
      CHECK(borrowed->format->format==SDL_PIXELFORMAT_ABGR8888);
      // Every single-pixel vertical stroke must survive real queued rendering.
      for(int x=0;x<640;++x) {
        CHECK(SDL_SetRenderDrawColor(target.renderer,Uint8(x%251),Uint8(x%127),73,255)==0);
        CHECK(SDL_RenderDrawLine(target.renderer,x,0,x,479)==0);
      }
      target.cursor_x=639; target.cursor_y=479;
      CHECK(target.end_frame()); CHECK(pointer.x==639 && pointer.y==479);
      const auto* pixels=static_cast<const uint32_t*>(borrowed->pixels);
      for(int x=0;x<640;++x)
        CHECK(pixels[239*640+x]==SDL_MapRGBA(borrowed->format,Uint8(x%251),Uint8(x%127),73,255));
      const auto view=cth3ds::follow_pointer_viewport({120,120},pointer,640,480,400,240);
      CHECK(view.x==240 && view.y==240);
      CHECK(cth3ds::copy_rgba_view(pixels,640,480,640,view,top.data(),400,240,400));
      CHECK(cth3ds::halve_rgba(pixels,640,480,640,bottom.data(),320));
      for(int y=0;y<240;++y) for(int x=0;x<400;++x)
        CHECK(top[y*400+x]==pixels[(y+240)*640+x+240]);
      for(int y=0;y<240;++y) for(int x=0;x<320;++x)
        CHECK(bottom[y*320+x]==pixels[(y*2)*640+x*2]);
      auto* original=borrowed;
      auto invalid=render_target_creation_params{}; invalid.width=800;
      CHECK(!target.update(invalid)); CHECK(borrowed==original && target.width==640);
      CHECK(target.update(render_target_creation_params{}));
      allow_present=false; CHECK(!target.end_frame()); allow_present=true;
    }
    CHECK(borrowed==nullptr && registered_window==nullptr);
  }
  SDL_Quit();
  printf("PASS real-SDL native-strokes crop overview pointer failure detach; lifetimes=20\n");
}
"""

class DualScreenCanvasTests(unittest.TestCase):
    def test_generated_renderer_real_sdl_pixels_and_lifetime(self):
        with tempfile.TemporaryDirectory(prefix='cth3ds-canvas-') as temp:
            temp=Path(temp)
            upstream=original_sources(temp/'upstream')
            self.assertEqual(integrate([str(upstream),'--overlay-root',str(ROOT)]),0)
            self.assertEqual(integrate([str(upstream),'--overlay-root',str(ROOT),'--check']),0)
            source=(upstream/'CorsixTH/Src/th_gfx_sdl.cpp').read_text()
            # These are the emitted production methods, not a replacement renderer.
            methods=source[source.index('render_target::render_target('):source.index('bool render_target::set_scale_factor(')]
            methods+=source[source.index('bool render_target::end_frame()'):source.index('bool render_target::fill_black()')]
            harness=temp/'canvas.cpp'
            harness.write_text(HARNESS+methods+MAIN)
            binary=temp/'canvas'
            flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl2'],text=True))
            command=[os.environ.get('CXX','c++'),'-std=c++17','-DCORSIXTH_3DS',
                     '-I'+str(ROOT/'include'),str(harness),str(ROOT/'src/common/framebuffer_scaler.cpp'),
                     *flags,'-o',str(binary)]
            if os.environ.get('CTH3DS_SOUND_SANITIZERS'):
                command[1:1]=['-fsanitize='+os.environ['CTH3DS_SOUND_SANITIZERS'],'-fno-omit-frame-pointer','-g']
            compiled=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('lifetimes=20',result.stdout)

    def test_real_level_identity_uses_map_and_header_is_required(self):
        with tempfile.TemporaryDirectory(prefix='cth3ds-canvas-contract-') as temp:
            upstream=original_sources(Path(temp)/'upstream')
            self.assertEqual(integrate([str(upstream),'--overlay-root',str(ROOT)]),0)
            app=(upstream/'CorsixTH/Lua/app.lua').read_text()
            self.assertEqual(app.count("'level:'..tostring((...).map and (...).map.level_number or 'loading')"),2)
            header=upstream/'CorsixTH/Src/th_gfx_sdl.h'
            header.write_text(header.read_text().replace('SDL_Surface* game_surface{nullptr};',''))
            self.assertNotEqual(integrate([str(upstream),'--overlay-root',str(ROOT),'--check']),0)
