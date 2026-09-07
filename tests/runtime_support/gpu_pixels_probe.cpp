#include "cth3ds/gpu_pixels.hpp"
#include <cassert>
#include <chrono>
#include <cstdio>
#include <vector>
int main(){
  using namespace cth3ds;
  std::uint64_t compared=0;
  for(unsigned w:{1U,3U,7U,8U,9U,31U,64U,127U,255U,511U,512U})
    for(unsigned h:{1U,7U,8U,9U,23U,64U,129U,512U}) {
      const auto stride=w+13;
      std::vector<std::uint32_t> src(stride*(h+1)),packed(w*h+2,0xdeadbeef);
      for(std::size_t i=0;i<src.size();++i)src[i]=std::uint32_t(i*17377U)^0x1307abcdU;
      gpu_prepare_pixels(packed.data()+1,src.data()+3,stride,w,h);
      assert(packed.front()==0xdeadbeef && packed.back()==0xdeadbeef);
      std::vector<std::uint32_t> a(1024*1024,0xbeadbeef),b=a;
      // Partial tiles and nonzero aligned origins must leave neighbours intact.
      gpu_upload_rgba(a.data(),1024,24,16,src.data()+3,stride,w,h);
      gpu_upload_prepared(b.data(),1024,24,16,packed.data()+1,w,h);
      assert(a==b);compared+=w*h;
    }
  // CPU-only cost comparison; never presented as a hardware speedup.
  const unsigned w=256,h=256;std::vector<std::uint32_t> src(w*h,0x7fabde23),packed(w*h),out(512*512);
  gpu_prepare_pixels(packed.data(),src.data(),w,w,h);
  auto measure=[&](auto upload){
    const auto start=std::chrono::steady_clock::now();
    for(int n=0;n<300;++n){upload();out[n]=static_cast<std::uint32_t>(n);}
    return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-start).count();
  };
  const auto reference=measure([&]{gpu_upload_rgba(out.data(),512,0,0,src.data(),w,w,h);});
  const auto prepared=measure([&]{gpu_upload_prepared(out.data(),512,0,0,packed.data(),w,h);});
  std::printf("PASS prepared GPU pixels compared=%llu exact_bytes_no_padding=1 host_reference_us=%lld host_prepared_us=%lld hardware=NOT_PROVEN\n",
    static_cast<unsigned long long>(compared),static_cast<long long>(reference),static_cast<long long>(prepared));
}
