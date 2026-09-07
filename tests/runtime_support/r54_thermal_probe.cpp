// The oracle below is the original v0.70.1 method, copied without arithmetic
// changes from CorsixTH/Src/th_map.cpp (fixed upstream commit in sources.json).
#include <algorithm>
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <vector>
#include "cth3ds/thermal_grid.hpp"
enum class object_type { radiator, other };
struct map_tile {
  struct Flags { bool can_travel_n{},can_travel_s{},can_travel_e{},can_travel_w{},hospital{},room{}; } flags;
  std::uint16_t aiTemperature[2]{};
  std::vector<object_type> objects;
};
namespace original {
struct level_map {
  int width,height,current_temperature_index;map_tile* cells;
  uint32_t thermal_neighbour(uint32_t&,bool,std::ptrdiff_t,map_tile*,int) const;
  void update_temperatures(uint16_t,uint16_t);
};
uint32_t level_map::thermal_neighbour(uint32_t& iNeighbourSum, bool canTravel,
                                      std::ptrdiff_t relative_idx,
                                      map_tile* pNode, int prevTemp) const {
  int iNeighbourCount = 0;

  map_tile* pNeighbour = pNode + relative_idx;

  // Ensure the neighbour is within the map bounds
  map_tile* pLimitNode = cells + width * height;
  if (pNeighbour < cells || pNeighbour >= pLimitNode) {
    return 0;
  }

  if (canTravel) {
    iNeighbourCount += 4;
    iNeighbourSum += pNeighbour->aiTemperature[prevTemp] * 4;
  } else {
    bool bObjectPresent = false;
    int iHospital1 = pNeighbour->flags.hospital;
    int iHospital2 = pNode->flags.hospital;
    if (iHospital1 == iHospital2) {
      if (pNeighbour->flags.room == pNode->flags.room) {
        bObjectPresent = true;
      }
    }
    if (bObjectPresent) {
      iNeighbourCount += 4;
      iNeighbourSum += pNeighbour->aiTemperature[prevTemp] * 4;
    } else {
      iNeighbourCount += 1;
      iNeighbourSum += pNeighbour->aiTemperature[prevTemp];
    }
  }

  return iNeighbourCount;
}
namespace {
void merge_temperatures(map_tile& node, size_t temp_idx, uint32_t other_temp,
                        double ratio) {
  const uint32_t node_temp = node.aiTemperature[temp_idx];
  node.aiTemperature[temp_idx] =
      static_cast<uint16_t>(((node_temp * (ratio - 1)) + other_temp) / ratio);
}
}
void level_map::update_temperatures(uint16_t iAirTemperature,
                                    uint16_t iRadiatorTemperature) {
  if (iRadiatorTemperature < iAirTemperature) {
    iRadiatorTemperature = iAirTemperature;
  }
  const int iPrevTemp = current_temperature_index;
  current_temperature_index ^= 1;
  const int iNewTemp = current_temperature_index;

  map_tile* pLimitNode = cells + width * height;
  for (map_tile* pNode = cells; pNode != pLimitNode; ++pNode) {
    // Get average temperature of neighbour cells
    uint32_t iNeighbourSum = 0;
    uint32_t iNeighbourCount = 0;

    iNeighbourCount += thermal_neighbour(
        iNeighbourSum, pNode->flags.can_travel_n, -width, pNode, iPrevTemp);
    iNeighbourCount += thermal_neighbour(
        iNeighbourSum, pNode->flags.can_travel_s, width, pNode, iPrevTemp);
    iNeighbourCount += thermal_neighbour(
        iNeighbourSum, pNode->flags.can_travel_e, 1, pNode, iPrevTemp);
    iNeighbourCount += thermal_neighbour(
        iNeighbourSum, pNode->flags.can_travel_w, -1, pNode, iPrevTemp);

    uint32_t iMergeTemp = 0;
    double mergeRatio = 100;
    if (pNode->flags.hospital) {
      bool hasRadiator = false;
      for (auto thob : pNode->objects) {
        if (thob == object_type::radiator) {
          hasRadiator = true;
          break;
        }
      }
      if (hasRadiator) {
        iMergeTemp = iRadiatorTemperature;
        mergeRatio = 2;  // Merge 50% against radiator temperature.
      } else {
        iMergeTemp = 0;
        mergeRatio = 1000;  // Generally dissipate 0.1% of temperature.
      }
    } else {
      iMergeTemp = iAirTemperature;
      mergeRatio = 100;  // Merge 1% against air temperature.
    }

    // Diffuse 25% with neighbours
    pNode->aiTemperature[iNewTemp] = pNode->aiTemperature[iPrevTemp];
    if (iNeighbourCount != 0) {
      merge_temperatures(*pNode, iNewTemp, iNeighbourSum / iNeighbourCount, 4);
    }

    merge_temperatures(*pNode, iNewTemp, iMergeTemp, mergeRatio);
  }
}
} // namespace original
static std::uint64_t fake_now=0;
static std::uint64_t clock_now() noexcept {return ++fake_now;}
static std::uint32_t seed=271;
static std::uint32_t random_value(){return seed=seed*1664525U+1013904223U;}
static void populate(std::vector<map_tile>& v,bool uniform){
  for(auto& tile:v){auto n=random_value();tile.aiTemperature[0]=n;tile.aiTemperature[1]=n>>16;
    tile.flags=uniform?map_tile::Flags{true,true,true,true,true,false}:
       map_tile::Flags{bool(n&1),bool(n&2),bool(n&4),bool(n&8),bool(n&16),bool(n&32)};
    tile.objects.clear();if(n%7==0)tile.objects.push_back(object_type::radiator);
    if(n%11==0)tile.objects.push_back(object_type::other);
  }
}
int main(){
  using namespace cth3ds;
  cpu_work={};cpu_work.clock_us=clock_now;
  std::uint64_t updates=0,pixels=0,divisions=0;
  for(unsigned d=1;d<=16;++d)for(unsigned n=0;n<=16U*65535;++n){
    assert(thermal_average(n,d)==n/d);++divisions;
  }
  ThermalGrid cache;
  // Reuse the cache across same-size replacement, dimensions with equal area,
  // ordinary maps, single-row/column maps, undo, and radiator removal.
  for(const auto dims:std::array<std::array<int,2>,8>{{{128,128},{128,128},{64,256},{128,128},{1,1},{1,17},{17,1},{7,11}}}){
    const int width=dims[0],height=dims[1];
    std::vector<map_tile>a(width*height),b;
    populate(a,true);b=a;original::level_map ref{width,height,0,a.data()};int current=0;
    for(unsigned step=0;step<240;++step){
      if(step==70 || step==140){populate(a,step==70);b=a;}
      const auto i=(step*71U)%a.size();const auto saved=a[i];
      if(step%11==0){a[i].objects.clear();a[i].objects.push_back(object_type::radiator);}
      else if(step%7==0)a[i].objects.clear();
      a[i].flags.room=step%2==0;a[i].flags.hospital=step%5==0;
      a[i].flags.can_travel_e=step%4==0;a[i].flags.can_travel_w=step%3==0;
      b[i]=a[i];if(step%19==0){a[i]=saved;b[i]=saved;} // undo
      cpu_work.thermal_phase_profile=step%2!=0;
      cpu_work.thermal_uniform_fast=step%3!=0;
      const auto air=static_cast<std::uint16_t>(step*315U),heat=static_cast<std::uint16_t>(65535-step*200);
      ref.update_temperatures(air,heat);
      cache.update(b.data(),width,height,current,current^1,air,heat,object_type::radiator);current^=1;
      assert(current==ref.current_temperature_index);
      for(std::size_t j=0;j<a.size();++j)for(int k=0;k<2;++k){assert(a[j].aiTemperature[k]==b[j].aiTemperature[k]);++pixels;}
      ++updates;
    }
  }
  for(unsigned i=6;i<9;++i)assert(cpu_work.rows[i].calls==updates/2);
  // Disabled observation must leave all counters unchanged.
  const auto before=cpu_work.rows;cpu_work.enabled=false;
  {CpuWorkScope scope(CpuWork::ThermalSnapshot);}
  for(unsigned i=0;i<9;++i)assert(before[i].calls==cpu_work.rows[i].calls);
  std::printf("PASS thermal upstream-method comparison: updates=%llu buffer_values=%llu division_cases=%llu\n",
      (unsigned long long)updates,(unsigned long long)pixels,(unsigned long long)divisions);
}
