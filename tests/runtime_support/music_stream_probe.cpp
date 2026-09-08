#include <SDL.h>
#include <SDL_mixer.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstring>

// Virtual 30-minute PCM WAV: no huge fixture, disk write or network transfer.
// Count actual SDL decoder reads, not a guessed process-RSS difference.
struct Stream {
  std::array<Uint8,44> header{};
  Sint64 position{};
  std::atomic<Uint64> read_bytes{};
  unsigned closes{};
  static constexpr Uint32 payload=22050U*2U*1800U;
  Stream() {
    auto u16=[&](int p,Uint16 n){header[p]=n;header[p+1]=n>>8;};
    auto u32=[&](int p,Uint32 n){for(int i=0;i<4;++i)header[p+i]=n>>(8*i);};
    std::memcpy(header.data(),"RIFF",4);u32(4,payload+36);
    std::memcpy(header.data()+8,"WAVEfmt ",8);u32(16,16);u16(20,1);u16(22,1);
    u32(24,22050);u32(28,44100);u16(32,2);u16(34,16);
    std::memcpy(header.data()+36,"data",4);u32(40,payload);
  }
};
Stream& owner(SDL_RWops* rw){return *static_cast<Stream*>(rw->hidden.unknown.data1);}
Sint64 size(SDL_RWops*){return Stream::payload+44;}
Sint64 seek(SDL_RWops* rw,Sint64 offset,int mode){
  auto& s=owner(rw);const auto p=(mode==RW_SEEK_SET?0:mode==RW_SEEK_CUR?s.position:size(rw))+offset;
  if(p<0||p>size(rw))return -1;return s.position=p;
}
size_t read(SDL_RWops* rw,void* output,size_t element,size_t count){
  auto& s=owner(rw);if(!element)return 0;
  count=std::min(count,static_cast<size_t>(size(rw)-s.position)/element);
  auto* out=static_cast<Uint8*>(output);const auto n=count*element;
  for(size_t i=0;i<n;++i,++s.position)out[i]=s.position<44?s.header[s.position]:0x20;
  s.read_bytes+=n;return count;
}
int close(SDL_RWops* rw){++owner(rw).closes;SDL_FreeRW(rw);return 0;}
std::atomic<Uint64> mixed_bytes{};
void mixed(void*,Uint8* bytes,int n){for(int i=0;i<n;++i)if(bytes[i]){mixed_bytes+=n;break;}}
int main(){
  assert(SDL_setenv("SDL_AUDIODRIVER","dummy",1)==0);
  assert(SDL_Init(SDL_INIT_AUDIO)==0);
  assert(Mix_OpenAudio(22050,AUDIO_S16SYS,2,512)==0);
  Mix_SetPostMix(mixed,nullptr);
  for(int i=0;i<8;++i){
    Stream stream;
    auto* rw=SDL_AllocRW();assert(rw);
    rw->hidden.unknown.data1=&stream;rw->size=size;rw->seek=seek;rw->read=read;rw->write=nullptr;rw->close=close;
    auto* music=Mix_LoadMUSType_RW(rw,MUS_WAV,1);assert(music);
    assert(stream.read_bytes<65536 && stream.closes==0);
    assert(Mix_PlayMusic(music,0)==0);SDL_Delay(80);
    Mix_PauseMusic();assert(Mix_PausedMusic());
    SDL_Delay(30);const auto paused=stream.read_bytes.load();SDL_Delay(40);
    assert(stream.read_bytes==paused);
    Mix_ResumeMusic();assert(!Mix_PausedMusic());
    // Resume can drain already decoded frames before requesting another read.
    for(int wait=0;wait<150 && stream.read_bytes==paused;++wait)SDL_Delay(10);
    assert(stream.read_bytes>paused);
    Mix_HaltMusic();Mix_FreeMusic(music);assert(stream.closes==1);
    assert(stream.read_bytes<131072); // 79.4 MB file remains mostly unread.
  }
  assert(mixed_bytes>0);Mix_CloseAudio();SDL_Quit();
  std::puts("PASS real SDL_mixer WAV streams, bounded reads, pause resume, eight closes");
}
