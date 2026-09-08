#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>
#include "cth3ds/cpu_work.hpp"

namespace cth3ds {
// Exact division for the neighbour sum (<= 16*65535), no ARM software divide.
inline std::uint32_t thermal_average(std::uint32_t n,unsigned d) noexcept {
  constexpr std::array<std::uint32_t,17> reciprocal{{0,0,2147483648U,1431655766U,
    1073741824U,858993460U,715827883U,613566757U,536870912U,477218589U,
    429496730U,390451573U,357913942U,330382100U,306783379U,286331154U,268435456U}};
  if(d<=1)return n;
  auto q=static_cast<std::uint32_t>((static_cast<std::uint64_t>(n)*reciprocal[d])>>32U);
  return q-(q*d>n?1U:0U);
}
class ThermalGrid {
  struct Cell {std::uint8_t flags{},weight[4]{},sum{};bool dirty{true};};
  std::vector<Cell> stencil_;
  std::vector<std::uint16_t> old_;
  std::vector<std::uint16_t> next_;
  int width_{};
  int cached_index_{-1};
  bool structure_dirty_{true};
 public:
  // Called by the real map mutation owners, before changing tiles.
  void invalidate_structure() noexcept {structure_dirty_=true;cached_index_=-1;}
  template<class Tile,class Object>
  void update(Tile* tiles,int width,int height,int previous,int current,
              std::uint16_t air,std::uint16_t radiator,Object radiator_type,
              bool force_structure_scan=true) {
    const int count=width*height;
    if(count<=0)return;
    if(stencil_.size()!=static_cast<std::size_t>(count)||width_!=width){
      std::vector<Cell> fresh(static_cast<std::size_t>(count));
      std::vector<std::uint16_t> values(static_cast<std::size_t>(count));
      std::vector<std::uint16_t> next_values(static_cast<std::size_t>(count));
      stencil_.swap(fresh);old_.swap(values);next_.swap(next_values);
      width_=width;structure_dirty_=true;cached_index_=-1;
    }
    radiator=std::max(air,radiator);
    // The generic API scans authoritative fields on every update. The pinned
    // engine opts into reuse only with its audited mutation-owner notifications.
    const bool profile=cpu_work.thermal_phase_profile;
    const bool scan=force_structure_scan||structure_dirty_;
    // Only the audited engine opts into dense reuse. Its load/resize/mutation
    // owners invalidate us; all authoritative tile values are still published
    // on every update for saves, displays and ordinary game consumers.
    const bool snapshot=force_structure_scan || cached_index_!=previous;
    ++cpu_work.thermal_updates;
    if(scan)++cpu_work.thermal_scans;
    cpu_work.thermal_bytes=bytes();
    const auto observe=[&](int i) {
      const auto& f=tiles[i].flags;
      unsigned flags=(f.can_travel_n?1U:0U)|(f.can_travel_s?2U:0U)|
        (f.can_travel_e?4U:0U)|(f.can_travel_w?8U:0U)|(f.hospital?16U:0U)|(f.room?32U:0U);
      if(f.hospital)for(const auto object:tiles[i].objects)
        if(object==radiator_type){flags|=64U;break;}
      auto& cell=stencil_[i];
      if(cell.flags!=flags){
        cell.flags=static_cast<std::uint8_t>(flags);cell.dirty=true;
        for(const int neighbour:{i-width,i+width,i+1,i-1})
          if(neighbour>=0 && neighbour<count)stencil_[neighbour].dirty=true;
      }
    };
    if(profile) {
      // Profiling mode isolates the three costs, with no clock calls per tile.
      // It intentionally makes an extra map pass; compare normal/profile runs
      // separately and do not treat this diagnostic mode as the speed baseline.
      {
        CpuWorkScope scope(CpuWork::ThermalStructure,static_cast<std::uint64_t>(count));
        if(scan)for(int i=0;i<count;++i)observe(i);
      }
      {
        CpuWorkScope scope(CpuWork::ThermalSnapshot,static_cast<std::uint64_t>(count));
        if(snapshot)for(int i=0;i<count;++i)old_[i]=tiles[i].aiTemperature[previous];
      }
    } else {
      if(scan)for(int i=0;i<count;++i){observe(i);if(snapshot)old_[i]=tiles[i].aiTemperature[previous];}
      else if(snapshot)for(int i=0;i<count;++i)old_[i]=tiles[i].aiTemperature[previous];
    }
    // Preserve the pinned engine's linear-array neighbour bounds, including
    // east/west boundary behaviour. Changing that would change game rules.
    // R62: stencil dirtiness is produced only by the scan above. Ordinary
    // updates need no per-tile dirty branch or rebuild code in their hot loop.
    if(scan)for(int i=0;i<count;++i){
      auto& cell=stencil_[i];
      if(cell.dirty){
        ++cpu_work.thermal_rebuilds;
        const int neighbours[4]{i-width,i+width,i+1,i-1};cell.sum=0;
        for(unsigned side=0;side<4;++side){
          const int n=neighbours[side];unsigned weight=0;
          if(n>=0&&n<count)
            weight=(cell.flags&(1U<<side)) || ((cell.flags^stencil_[n].flags)&48U)==0 ?4U:1U;
          cell.weight[side]=static_cast<std::uint8_t>(weight);cell.sum+=weight;
        }cell.dirty=false;
      }
    }
    CpuWorkScope arithmetic(CpuWork::ThermalArithmetic,static_cast<std::uint64_t>(count),profile);
    const bool uniform_fast=cpu_work.thermal_uniform_fast;
    for(int i=0;i<count;++i){
      const auto& cell=stencil_[i];
      std::uint32_t value=old_[i];
      if(uniform_fast && cell.sum==16) {
        // Four weights of four imply four valid neighbours. Cancelling the
        // common factor is exact, including both original integer truncations.
        // No approximate reciprocal, changed edge rule, or delayed publication.
        const std::uint32_t neighbours=static_cast<std::uint32_t>(old_[i-width])+
          old_[i+width]+old_[i+1]+old_[i-1];
        value=(value*3U+(neighbours>>2U))>>2U;
      } else {
        std::uint32_t sum=0;
        if(cell.weight[0])sum+=old_[i-width]*cell.weight[0];
        if(cell.weight[1])sum+=old_[i+width]*cell.weight[1];
        if(cell.weight[2])sum+=old_[i+1]*cell.weight[2];
        if(cell.weight[3])sum+=old_[i-1]*cell.weight[3];
        if(cell.sum)value=(value*3U+thermal_average(sum,cell.sum))/4U;
      }
      if(!(cell.flags&16U))value=(value*99U+air)/100U;
      else if(cell.flags&64U)value=(value+radiator)/2U;
      else value=value*999U/1000U;
      tiles[i].aiTemperature[current]=static_cast<std::uint16_t>(value);
      next_[i]=static_cast<std::uint16_t>(value);
    }
    old_.swap(next_);cached_index_=current;
    structure_dirty_=false;
  }
  std::size_t bytes() const noexcept {return stencil_.capacity()*sizeof(Cell)+(old_.capacity()+next_.capacity())*sizeof(std::uint16_t);}
};
} // namespace cth3ds
