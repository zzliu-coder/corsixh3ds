// Compiled against original and assembled production methods, not a second
// temperature implementation. Minimal tile containers isolate the arithmetic.
#include "cth3ds/cpu_work.hpp"
#include "cth3ds/thermal_grid.hpp"
#include <algorithm>
#include <cassert>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <vector>
enum class object_type { radiator, other };
struct map_tile {
  struct Flags {bool can_travel_n{},can_travel_s{},can_travel_e{},can_travel_w{},hospital{},room{};} flags;
  std::uint16_t aiTemperature[2]{};
  std::vector<object_type> objects;
};
// INSERT_METHODS
static std::uint64_t fake_now;
static std::uint64_t clock_now() noexcept {return fake_now;}
int main() {
  for(std::uint32_t value=0;value<65536;++value)for(unsigned ratio:{2,4,100,1000})
    for(unsigned other:{0U,65535U,(value*347U)%65536U}) {
      map_tile a,b;a.aiTemperature[0]=b.aiTemperature[0]=static_cast<std::uint16_t>(value);
      original::merge_temperatures(a,0,other,ratio);
      improved::merge_temperatures(b,0,other,ratio);
      assert(a.aiTemperature[0]==b.aiTemperature[0]);
    }
  std::vector<map_tile> a(128*128),b;
  std::uint32_t seed=271;
  for(auto& tile:a) {
    seed=seed*1664525U+1013904223U;
    tile.aiTemperature[0]=static_cast<std::uint16_t>(seed);
    tile.aiTemperature[1]=static_cast<std::uint16_t>(seed>>16U);
    tile.flags={bool(seed&1),bool(seed&2),bool(seed&4),bool(seed&8),bool(seed&16),bool(seed&32)};
    if(seed%7==0)tile.objects.push_back(object_type::radiator);
    if(seed%11==0)tile.objects.push_back(object_type::other);
  }
  b=a;original::level_map ref{128,128,0,a.data(),{}};improved::level_map fast{128,128,0,b.data(),{}};
  cth3ds::cpu_work.clock_us=clock_now;
  for(unsigned step=0;step<200;++step) {
    // Same boundary/ownership/radiator mutations before each real update.
    const auto index=step*71;
    a[index].flags.room=b[index].flags.room=step%2==0;
    a[index].objects.clear();b[index].objects.clear();
    if(step%3==0){a[index].objects.push_back(object_type::radiator);b[index].objects=a[index].objects;}
    a[index].flags.hospital=b[index].flags.hospital=step%5==0;
    a[index].flags.can_travel_e=b[index].flags.can_travel_e=step%4==0;
    const auto air=static_cast<std::uint16_t>(step*315U),heat=static_cast<std::uint16_t>(65535-step*200);
    // This standalone fixture writes tile fields directly. Production writes
    // go through the ten separately verified mutation owners.
    fast.thermal_cache.invalidate_structure();
    ref.update_temperatures(air,heat);fast.update_temperatures(air,heat);
    assert(ref.current_temperature_index==fast.current_temperature_index);
    for(std::size_t i=0;i<a.size();++i)for(int slot=0;slot<2;++slot)
      assert(a[i].aiTemperature[slot]==b[i].aiTemperature[slot]);
  }
  const auto temp=cth3ds::cpu_work.rows[0];
  assert(temp.calls==200 && temp.units==200*128*128);
  cth3ds::cpu_work.rows={};fake_now=10;
  {cth3ds::CpuWorkScope scope(cth3ds::CpuWork::InputState);fake_now=27;}
  assert(cth3ds::cpu_work.rows[2].total_us==17 && cth3ds::cpu_work.rows[2].max_us==17);
  cth3ds::cpu_work.enabled=false;
  {cth3ds::CpuWorkScope scope(cth3ds::CpuWork::InputState);fake_now=999;}
  assert(cth3ds::cpu_work.rows[2].calls==1);
  cth3ds::InputRefreshGate gate;
  unsigned queries=0,ui_epoch=1,observed=0;
  auto query=[&]{++queries;observed=ui_epoch;};
  for(int sample=0;sample<64;++sample) {
    gate.refresh(query);gate.refresh(query);gate.refresh(query);
  }
  assert(queries==1 && observed==1);
  ++ui_epoch;gate.invalidate();gate.refresh(query);gate.refresh(query);
  assert(queries==2 && observed==2);
  gate.invalidate();try {gate.refresh([]{throw std::runtime_error("test");});}catch(const std::runtime_error&){}
  gate.refresh(query);assert(queries==3);
  std::puts("PASS 786432 temperature merges, 200 complete mutated-map updates, bounded CPU counters, input invalidation");
}
