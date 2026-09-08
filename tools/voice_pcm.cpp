// Offline only. SDL's established converter; preserve mono/stereo, normalize
// PCM to S16LE/22050 before the SD read. Never linked into the 3DS application.
#include <SDL.h>
#include <climits>
#include <cstring>
extern "C" int voice_pcm(const unsigned char* source,int bytes,int bits,
                        int channels,int rate,unsigned char* output,int capacity) {
  if(!source || bytes<=0 || (bits!=8 && bits!=16) ||
     (channels!=1 && channels!=2) || rate<4000 || rate>192000 ||
     bytes%(channels*(bits/8))!=0)return -1;
  SDL_AudioCVT cvt{};
  if(SDL_BuildAudioCVT(&cvt,bits==8?AUDIO_U8:AUDIO_S16LSB,channels,rate,
                      AUDIO_S16LSB,channels,22050)<0 || cvt.len_mult<1)return -2;
  if(bytes>INT_MAX/cvt.len_mult || bytes*cvt.len_mult>12*1024*1024)return -3;
  const int reserve=bytes*cvt.len_mult;
  if(!output)return reserve;
  if(capacity<reserve)return -4;
  std::memcpy(output,source,bytes);
  if(!cvt.needed)return bytes;
  cvt.buf=output;cvt.len=bytes;
  if(SDL_ConvertAudio(&cvt)<0 || cvt.len_cvt<=0 || cvt.len_cvt>capacity)return -5;
  return cvt.len_cvt;
}
