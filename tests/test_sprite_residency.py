"""The generated texture eviction code against real SDL software textures."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from sprite_residency import CACHE
from integrate_corsixth import main as integrate
from test_playable_path import original_sources

MAIN = r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"check %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main() {
  SDL_SetHint(SDL_HINT_VIDEODRIVER,"dummy");
  CHECK(SDL_Init(SDL_INIT_VIDEO)==0);
  auto* surface=SDL_CreateRGBSurfaceWithFormat(0,64,64,32,SDL_PIXELFORMAT_RGBA32);
  CHECK(surface);
  auto* renderer=SDL_CreateSoftwareRenderer(surface); CHECK(renderer);
  std::array<SDL_Texture*,512> owners{};
  std::array<Uint32,4096> pixels{};
  const auto colour=SDL_MapRGBA(surface->format,17,33,65,255); pixels.fill(colour);
  size_t peak=0;
  for(int turn=0;turn<5000;++turn) {
    auto& owner=owners[turn%owners.size()];
    if(owner) { sprite_texture_forget(&owner); SDL_DestroyTexture(owner); owner=nullptr; }
    auto bytes=sprite_texture_prepare(64,64);
    owner=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_RGBA32,SDL_TEXTUREACCESS_STATIC,64,64); CHECK(owner);
    CHECK(SDL_UpdateTexture(owner,nullptr,pixels.data(),64*4)==0);
    sprite_texture_remember(&owner,bytes);
    CHECK(sprite_texture_bytes<=sprite_texture_budget && sprite_texture_count<=4096);
    peak=std::max(peak,sprite_texture_bytes);
    if(turn==0) CHECK(SDL_RenderCopy(renderer,owner,nullptr,nullptr)==0);
    if(turn==400) CHECK(owners[0]==nullptr); // prior queued draw survived eviction
  }
  SDL_RenderPresent(renderer);
  CHECK(static_cast<Uint32*>(surface->pixels)[0]==colour);
  bool rejected=false;
  try { sprite_texture_prepare(0x7fffffff,0x7fffffff); } catch(const std::runtime_error&) { rejected=true; }
  CHECK(rejected);
  for(auto& owner:owners) if(owner) { sprite_texture_forget(&owner); SDL_DestroyTexture(owner); owner=nullptr; }
  CHECK(sprite_texture_bytes==0);
  while(sprite_texture_count) sprite_texture_evict_one();
  CHECK(sprite_texture_count==0);
  SDL_DestroyRenderer(renderer); SDL_FreeSurface(surface); SDL_Quit();
  printf("PASS 5000 textures; peak=%zu; budget=%zu; final=0; queued-pixels-exact\n",peak,sprite_texture_budget);
}
'''

class SpriteResidencyTests(unittest.TestCase):
    def test_actual_generated_cache_with_real_sdl_textures(self):
        with tempfile.TemporaryDirectory(prefix='cth3ds-sprite-residency-') as temp:
            temp=Path(temp)
            upstream=original_sources(temp/'upstream')
            self.assertEqual(integrate([str(upstream),'--overlay-root',str(ROOT)]),0)
            generated=(upstream/'CorsixTH/Src/th_gfx_sdl.cpp').read_text()
            self.assertIn(CACHE,generated)
            self.assertIn('sprite_texture_remember(&sprite.texture, texture_bytes)',generated)
            self.assertIn('sprite_texture_remember(&pSprite->alt_texture, texture_bytes)',generated)
            self.assertIn('sprite_texture_forget(&sprites[iNumber].texture)',generated)
            self.assertIn('std::unique_ptr<uint32_t[]> argb_owner(pARGBPixels)',generated)
            self.assertIn('return texture_owner.release()',generated)
            source=temp/'textures.cpp'
            source.write_text('#include <SDL.h>\n#include <array>\n#include <algorithm>\n#include <stdexcept>\n#include <cstdio>\n'+CACHE+MAIN)
            binary=temp/'textures'
            flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl2'],text=True))
            command=[os.environ.get('CXX','c++'),'-std=c++17','-DCORSIXTH_3DS',str(source),*flags,'-o',str(binary)]
            if os.environ.get('CTH3DS_SOUND_SANITIZERS'):
                command[1:1]=['-fsanitize='+os.environ['CTH3DS_SOUND_SANITIZERS'],'-fno-omit-frame-pointer','-g']
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('final=0; queued-pixels-exact',result.stdout)

