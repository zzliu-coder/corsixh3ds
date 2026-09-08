#include <cassert>
#include <cstdio>
#include <vector>
extern "C" int voice_pcm(const unsigned char*,int,int,int,int,unsigned char*,int);
int main() {
  std::vector<unsigned char> source(22050,140);
  assert(voice_pcm(nullptr,100,8,1,11025,nullptr,0)<0);
  assert(voice_pcm(source.data(),1,16,1,22050,nullptr,0)<0);
  assert(voice_pcm(source.data(),100,24,1,22050,nullptr,0)<0);
  assert(voice_pcm(source.data(),100,8,3,22050,nullptr,0)<0);
  assert(voice_pcm(source.data(),100,8,1,0,nullptr,0)<0);
  for(int channels:{1,2})for(int bits:{8,16})for(int rate:{11025,22050}) {
    const int n=2204*channels*(bits/8);
    const int capacity=voice_pcm(source.data(),n,bits,channels,rate,nullptr,0);
    assert(capacity>=n);
    std::vector<unsigned char> output(capacity+16,0x5A);
    assert(voice_pcm(source.data(),n,bits,channels,rate,output.data(),capacity-1)<0);
    const int got=voice_pcm(source.data(),n,bits,channels,rate,output.data(),capacity);
    assert(got==(2204*22050/rate)*channels*2);
    for(int i=capacity;i<capacity+16;++i)assert(output[i]==0x5A);
  }
  std::puts("PASS voice PCM rates, channels, whole frames and capacity bounds");
}
