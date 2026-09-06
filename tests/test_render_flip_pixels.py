"""Real SDL software render comparison. Host timing never becomes device FPS."""
import os, shlex, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CPP=r'''
#include <SDL.h>
#include "cth3ds/render_work.hpp"
#include <vector>
#include <cstdio>
#include <cstring>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"check %d: %s %s\n",__LINE__,#x,SDL_GetError());return 1;}}while(0)
int main(){
 SDL_SetHint(SDL_HINT_VIDEODRIVER,"dummy"); CHECK(SDL_Init(SDL_INIT_VIDEO)==0);
 auto* canvas=SDL_CreateRGBSurfaceWithFormat(0,64,64,32,SDL_PIXELFORMAT_ARGB8888);CHECK(canvas);
 auto* r=SDL_CreateSoftwareRenderer(canvas);CHECK(r);unsigned cases=0;
 for(int w:{1,2,3,16,17,32})for(int h:{1,2,3,16,17,32})for(int flip=1;flip<4;++flip)
 for(int pos:{-3,0,7,57})for(int alpha:{255,128,64}){
   std::vector<Uint32> p(static_cast<size_t>(w*h));
   for(size_t i=0;i<p.size();++i) p[i]=SDL_MapRGBA(canvas->format,static_cast<Uint8>(i*17),static_cast<Uint8>(i*31),static_cast<Uint8>(i*47),i%3?255:0);
   auto* original=SDL_CreateTexture(r,SDL_PIXELFORMAT_ARGB8888,SDL_TEXTUREACCESS_STATIC,w,h);CHECK(original);
   CHECK(SDL_UpdateTexture(original,nullptr,p.data(),w*4)==0);
   cth3ds::flip_rgba_in_place(p.data(),w,h,(flip&1)!=0,(flip&2)!=0);
   auto* cached=SDL_CreateTexture(r,SDL_PIXELFORMAT_ARGB8888,SDL_TEXTUREACCESS_STATIC,w,h);CHECK(cached);
   CHECK(SDL_UpdateTexture(cached,nullptr,p.data(),w*4)==0);
   for(auto* t:{original,cached}){CHECK(SDL_SetTextureBlendMode(t,SDL_BLENDMODE_BLEND)==0);CHECK(SDL_SetTextureAlphaMod(t,static_cast<Uint8>(alpha))==0);}
   SDL_Rect clip{2,3,57,55};CHECK(SDL_RenderSetClipRect(r,&clip)==0);
   // Exact FRect overdraw used by the pinned render_target::draw at scale 1.
   SDL_FRect dst{static_cast<float>(pos)-.01F,6.99F,static_cast<float>(w)+.02F,static_cast<float>(h)+.02F};
   auto clear=[&]{SDL_SetRenderDrawColor(r,19,31,41,255);SDL_RenderClear(r);};
   clear();CHECK(SDL_RenderCopyExF(r,original,nullptr,&dst,0,nullptr,static_cast<SDL_RendererFlip>(flip))==0);CHECK(SDL_RenderFlush(r)==0);
   std::vector<Uint8> ref(static_cast<size_t>(canvas->pitch*canvas->h));memcpy(ref.data(),canvas->pixels,ref.size());
   clear();CHECK(SDL_RenderCopyF(r,cached,nullptr,&dst)==0);CHECK(SDL_RenderFlush(r)==0);
   if(memcmp(ref.data(),canvas->pixels,ref.size())){fprintf(stderr,"pixels differ w=%d h=%d flip=%d x=%d alpha=%d\n",w,h,flip,pos,alpha);return 2;}
   SDL_DestroyTexture(original);SDL_DestroyTexture(cached);++cases;
 }
 printf("PASS %u clipped alpha odd/even flip pixel comparisons\n",cases);
 SDL_DestroyRenderer(r);SDL_FreeSurface(canvas);SDL_Quit();
}
'''
class RenderFlipPixelsTests(unittest.TestCase):
    def test_real_sdl_preflipped_pixels_match_general_flip(self):
        with tempfile.TemporaryDirectory(prefix='cth3ds-flip-pixels-') as temp:
            temp=Path(temp); source=temp/'pixels.cpp';binary=temp/'pixels';source.write_text(CPP)
            flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl2'],text=True))
            cmd=[os.environ.get('CXX','c++'),'-std=c++17','-O2','-I'+str(ROOT/'include'),str(source),*flags,'-o',str(binary)]
            if os.environ.get('CTH3DS_SOUND_SANITIZERS'):cmd[1:1]=['-fsanitize='+os.environ['CTH3DS_SOUND_SANITIZERS'],'-fno-omit-frame-pointer']
            result=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS 1296',result.stdout)
