"""Extract real PCM preflight, evaluate with a 32-bit size_t host model.
No ARM CPU, ABI, decoder, or mixer behavior is claimed by this model.
"""
from pathlib import Path
def source(path: Path) -> str:
    text=path.read_text();begin=text.index('bool sound_archive::pcm_requirement(')
    end=text.index('\n}\n#endif',begin)+2;function=text[begin:end]
    return r'''
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#undef SIZE_MAX
#define SIZE_MAX UINT32_MAX
namespace target32 {
using size_t=uint32_t;using Uint16=uint16_t;
struct SDL_RWops {};
struct WaveInfo {uint32_t rate=22050,bytes=0;uint16_t channels=1,bits=8;};
struct SDL_AudioCVT {int len_mult=0;};
constexpr int AUDIO_U8=8,AUDIO_S16LSB=16;
#define SDL_AUDIO_BITSIZE(format) ((format)&255)
static uint32_t input=100;static int multiplier=2;
inline bool wave_info(SDL_RWops*,WaveInfo& w) {w.bytes=input;return true;}
inline int SDL_RWclose(SDL_RWops*) {return 0;}
inline int Mix_QuerySpec(int* rate,Uint16* format,int* channels) {*rate=22050;*format=16;*channels=2;return 1;}
inline int SDL_BuildAudioCVT(SDL_AudioCVT* cvt,int,int,int,int,int,int) {cvt->len_mult=multiplier;return 1;}
struct sound_archive {
  SDL_RWops rw;
  SDL_RWops* load_sound(size_t) {return &rw;}
  bool pcm_requirement(size_t,size_t&,size_t&);
};
''' + function + r'''
}
int main() {
 using namespace target32;
 sound_archive a;target32::size_t converted=0,scratch=0;
 if (!a.pcm_requirement(0,converted,scratch) || scratch!=65836) return 41;
 input=0x10000000;multiplier=15;
 bool accepted=a.pcm_requirement(0,converted,scratch);
 std::printf("model_size_t_bytes=%zu accepted_overflow=%d scratch=%u\n",sizeof(target32::size_t),accepted,scratch);
 if(accepted) return 41;
 std::puts("PASS 32-bit scratch overflow rejected; no ARM execution claimed");return 0;
}
'''
