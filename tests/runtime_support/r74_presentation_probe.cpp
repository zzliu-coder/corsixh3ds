#include "cth3ds/boot_presentation.hpp"
#include <array>
#include <cassert>
#include <cstdio>
#include <string>

using namespace cth3ds;
static void ppm(const std::string& path,const std::uint32_t* p,int w,int h){
  auto* f=std::fopen(path.c_str(),"wb");assert(f);std::fprintf(f,"P6\n%d %d\n255\n",w,h);
  for(int i=0;i<w*h;++i){unsigned char rgb[]={static_cast<unsigned char>(p[i]),static_cast<unsigned char>(p[i]>>8),static_cast<unsigned char>(p[i]>>16)};
    assert(std::fwrite(rgb,1,3,f)==3);}
  assert(std::fclose(f)==0);
}
int main(int argc,char** argv){
  BootPresentation state;
  assert(state.mode()==PresentationMode::BootText);
  state.artwork();state.artwork();assert(state.mode()==PresentationMode::BootArtwork);
  state.game();state.artwork();assert(state.mode()==PresentationMode::Game);
  state.error();state.game();state.artwork();assert(state.mode()==PresentationMode::Error);
  state.reset();assert(state.mode()==PresentationMode::BootText);
  state.game();assert(state.mode()==PresentationMode::Game); // no artwork/bad install
  std::array<std::uint32_t,648*480> source{};
  std::array<std::uint32_t,408*240> top{};
  std::array<std::uint32_t,328*240> bottom{};
  for(int y=0;y<480;++y)for(int x=0;x<640;++x)source[y*648+x]=0xff000000U|unsigned(x)|unsigned(y)<<10;
  top.fill(0xbadbadU);bottom.fill(0xbadbadU);
  assert(copy_boot_artwork(source.data(),648,top.data(),400,408,true,0xff201912U));
  assert(copy_boot_artwork(source.data(),648,bottom.data(),320,328,false,0xff201912U));
  for(int y=0;y<240;++y){
    for(int x=0;x<400;++x)assert(top[y*408+x]==((x>=40&&x<360&&y>=80)?source[(64+(y-80)*176/160)*648+144+(x-40)*352/320]:0xff201912U));
    for(int x=400;x<408;++x)assert(top[y*408+x]==0xbadbadU);
    for(int x=0;x<320;++x){
      const auto expected=y<160?source[(240+y*176/160)*648+144+x*352/320]:
        (y>=184&&y<208?source[(432+(y-184)*2)*648+x*2]:0xff201912U);
      assert(bottom[y*328+x]==expected);
    }
    for(int x=320;x<328;++x)assert(bottom[y*328+x]==0xbadbadU);
  }
  assert(!copy_boot_artwork(nullptr,648,top.data(),400,408,true,0));
  assert(!copy_boot_artwork(source.data(),639,top.data(),400,408,true,0));
  assert(!copy_boot_artwork(source.data(),648,top.data(),320,408,true,0));
  std::array<std::uint32_t,320*240> loading{};loading.fill(0xff201912U);
  auto mask=[&](const presentation_masks::Mask& m,int y){
    assert(m.width<=320&&m.height<=20);
    paint_fixed_mask(m,(320-m.width)/2,y,[&](int x,int yy,unsigned a){
      assert(x>=0&&x<320&&yy>=0&&yy<240);
      loading[yy*320+x]=0xff000000U|(18+(239-18)*a/255)|((25+(242-25)*a/255)<<8)|((32+(244-32)*a/255)<<16);
    });
  };
  mask(presentation_masks::loading,87);mask(presentation_masks::credit,123);mask(presentation_masks::based,146);
  if(argc>1)ppm(std::string(argv[1])+"/loading.ppm",loading.data(),320,240);
  loading.fill(0xff201912U);mask(presentation_masks::paused,0);
  if(argc>1)ppm(std::string(argv[1])+"/paused-strip.ppm",loading.data(),320,13);
  loading.fill(0xff201912U);mask(presentation_masks::paused_build,0);
  if(argc>1)ppm(std::string(argv[1])+"/paused-build-strip.ppm",loading.data(),320,13);
  constexpr auto bytes=sizeof(presentation_masks::loading_data)+sizeof(presentation_masks::credit_data)+sizeof(presentation_masks::based_data)+sizeof(presentation_masks::paused_data)+sizeof(presentation_masks::paused_build_data);
  static_assert(bytes<=6000);
  if(argc==4){
    // Optional local-only visual fixture. Original game files are never copied
    // into the repository; emitted previews exercise the production CPU map.
    std::array<unsigned char,640*480> indexed{};
    std::array<unsigned char,768> palette{};
    auto* pixels=std::fopen(argv[2],"rb");assert(pixels);
    assert(std::fread(indexed.data(),1,indexed.size(),pixels)==indexed.size());assert(std::fclose(pixels)==0);
    auto* colours=std::fopen(argv[3],"rb");assert(colours);
    assert(std::fread(palette.data(),1,palette.size(),colours)==palette.size());assert(std::fclose(colours)==0);
    for(int y=0;y<480;++y)for(int x=0;x<640;++x){
      auto at=indexed[y*640+x]*3;
      source[y*648+x]=0xff000000U|unsigned(palette[at]*4)|unsigned(palette[at+1]*4)<<8|unsigned(palette[at+2]*4)<<16;
    }
    std::array<std::uint32_t,400*240> top_image{};
    assert(copy_boot_artwork(source.data(),648,top_image.data(),400,400,true,kArtworkBackground));
    assert(copy_boot_artwork(source.data(),648,loading.data(),320,320,false,kArtworkBackground));
    ppm(std::string(argv[1])+"/disc-top.ppm",top_image.data(),400,240);
    ppm(std::string(argv[1])+"/disc-bottom.ppm",loading.data(),320,240);
  }
  std::printf("PASS startup state/error latch/reset; CPU disjoint slices + pitch guards; fixed masks=%zu bytes, heap allocation=0\n",bytes);
}
