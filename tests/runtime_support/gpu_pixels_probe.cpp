#include "cth3ds/gpu_pixels.hpp"
#include <cassert>
#include <chrono>
#include <cstdio>
#include <vector>
int main(){
  using namespace cth3ds;
  std::uint64_t compared=0;
  for(int w:{1,7,8,17,127,128})for(int h:{1,8,23,128})for(int flip=0;flip<4;++flip){
    const int iw=w+23,ih=h+19,sx=11,sy=9;
    std::vector<std::uint8_t> indices(iw*ih),packed(w*h+2,0xad);
    std::uint32_t colours[256],pica[256];
    for(unsigned i=0;i<256;++i)pica[i]=gpu_pixel(colours[i]=0x80204600U+i*7919U);
    for(int i=0;i<iw*ih;++i)indices[i]=static_cast<std::uint8_t>(i*79U);
    std::vector<std::uint32_t> reference(w*h),actual(512*512,0xfeedabcd),expected=actual;
    for(int y=0;y<h;++y)for(int x=0;x<w;++x)
      reference[y*w+x]=colours[indices[(flip&2?ih-1-sy-y:sy+y)*iw+(flip&1?iw-1-sx-x:sx+x)]];
    gpu_prepare_indices(packed.data()+1,indices.data(),iw,ih,sx,sy,w,h,flip&1,flip&2);
    assert(packed.front()==0xad&&packed.back()==0xad);
    gpu_upload_indices(actual.data(),512,24,16,packed.data()+1,w,h,pica);
    gpu_upload_rgba(expected.data(),512,24,16,reference.data(),w,w,h);
    assert(actual==expected);compared+=w*h;
  }
  // The skyline owns tile-aligned, non-overlapping regions. Rejected requests
  // leave it unchanged; mixed heights reuse space left by the old shelf.
  GpuSkyline skyline;GpuShelf shelf;std::vector<bool> used(64*64);
  unsigned skyline_count=0,shelf_count=0;
  for(int n=0;n<300;++n){
    const int w=n%3==0?128:32,h=n%3==0?128:8;int x{},y{},a{},b{};
    if(shelf.allocate(w,h,a,b))++shelf_count;
    const auto before=skyline;
    if(skyline.allocate(w,h,x,y)){
      ++skyline_count;assert(x%8==0&&y%8==0&&x+w<=512&&y+h<=512);
      for(int yy=y/8;yy<(y+h+7)/8;++yy)for(int xx=x/8;xx<(x+w+7)/8;++xx){
        assert(!used[yy*64+xx]);used[yy*64+xx]=true;
      }
    }else for(int i=0;i<64;++i)assert(skyline.heights[i]==before.heights[i]);
  }
  assert(skyline_count>shelf_count);
  std::printf("PASS indexed pixels and skyline mixed_fixture=%u shelf=%u hardware=NOT_PROVEN\n",skyline_count,shelf_count);
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
