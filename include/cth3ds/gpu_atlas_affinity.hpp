#pragma once
#include <array>
#include <cstdint>

#ifndef CTH3DS_GPU_ATLAS_AFFINITY
#define CTH3DS_GPU_ATLAS_AFFINITY 1
#endif
namespace cth3ds {
// A soft miss preference only: hits, capacity and eviction policy stay intact.
struct GpuAtlasAffinity {
  std::uint64_t generation{};
  int page{-1};
  bool floor{};
  template<class Pages> std::array<unsigned,3> order(const Pages& pages) noexcept {
    std::array<unsigned,3> result{0,1,2};
    if(page>=0 && (page>=3 || pages[page].generation!=generation))page=-1;
#if CTH3DS_GPU_ATLAS_AFFINITY
    int first=page;
    if(floor && first<0){
      // Reset pages have used==0. Recycled pages allocate before returning.
      for(unsigned i=0;i<3;++i)if(pages[i].used==0){first=int(i);break;}
    }
    if(first>=0){
      unsigned n=0;
      if(floor)result[n++]=unsigned(first);
      for(unsigned i=0;i<3;++i)if(int(i)!=first)result[n++]=i;
      if(!floor)result[n]=unsigned(first);
    }
#endif
    return result;
  }
  void placed(int selected,std::uint64_t current_generation) noexcept {
#if CTH3DS_GPU_ATLAS_AFFINITY
    if(floor && page<0){page=selected;generation=current_generation;}
#else
    (void)selected;(void)current_generation;
#endif
  }
};
static_assert(sizeof(GpuAtlasAffinity)<=24,"Atlas affinity must stay bounded");
}
