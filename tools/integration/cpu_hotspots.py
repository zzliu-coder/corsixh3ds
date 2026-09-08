"""Small, pinned real-call-site CPU changes; desktop equations unchanged."""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError
from .thermal_cache import transforms as thermal_transforms
from .world_profile import transforms as world_transforms
from .latency import transforms as latency_transforms
from .spatial_queries import transforms as spatial_transforms
from .save_memory import transforms as save_transforms

def transforms(root):
    path='CorsixTH/Src/th_map.cpp'
    text=(root/path).read_text()
    sites=[
      ('#include "th_map.h"\n', '#include "th_map.h"\n#ifdef CORSIXTH_3DS\n#include "cth3ds/cpu_work.hpp"\n#endif\n'),
      ('                        double ratio) {\n',
       '                        double ratio) {\n#ifdef CORSIXTH_3DS\n'
       '  // R51: all four pinned weights are positive integers; 16-bit inputs\n'
       '  // keep the numerator below 2^26. Preserve both truncation steps.\n'
       '  const auto weight = static_cast<uint32_t>(ratio);\n'
       '  const uint32_t previous = node.aiTemperature[temp_idx];\n'
       '  node.aiTemperature[temp_idx] = static_cast<uint16_t>(\n'
       '      (previous * (weight - 1U) + other_temp) / weight);\n'
       '  return;\n#endif\n'),
      ('                                    uint16_t iRadiatorTemperature) {\n',
       '                                    uint16_t iRadiatorTemperature) {\n#ifdef CORSIXTH_3DS\n'
       '  cth3ds::CpuWorkScope cpu_scope(cth3ds::CpuWork::Temperature,\n'
       '      static_cast<uint64_t>(width) * height);\n#endif\n')]
    for old,new in sites:
        if 'CpuWorkScope cpu_scope' in new and 'R52: one authoritative snapshot' in text:continue
        if new not in text:text=replace_exact(text,old,new,'CPU temperature site')
    old='''      static_cast<uint64_t>(width) * height);
#endif'''
    new='''      static_cast<uint64_t>(width) * height);
  // R52: one authoritative snapshot, cached stencil, exact bounded arithmetic.
  // Toggle only after all scratch allocations succeed.
  thermal_cache.update(cells,width,height,current_temperature_index,
    current_temperature_index ^ 1,iAirTemperature,iRadiatorTemperature,object_type::radiator,
    !cth3ds::cpu_work.thermal_structure_fast);
  current_temperature_index ^= 1;
  return;
#endif'''
    if new not in text:text=replace_exact(text,old,new,'CPU real thermal stencil')
    yield path,text

    path='CorsixTH/Lua/app.lua'
    text=(root/path).read_text()
    old='''function App:onTick(...)
  if (not self.moviePlayer.playing) then
    if self.world then
      self.world:onTick(...)
    end
    self.ui:onTick(...)
  end
  return true -- tick events always result in a repaint
end'''
    new='''function App:onTick(...)
  -- R52: preserve World/UI tick rules; observe each real call exactly once.
  local native = self._3ds and self._3ds.native
  local repaint = self.moviePlayer.playing
  if (not self.moviePlayer.playing) then
    if self.world then
      if native and native.cpu_profile then
        native.cpu_profile("world", self.world.onTick, self.world, ...)
      else self.world:onTick(...) end
      repaint = true
    end
    local ui_repaint
    if native and native.cpu_profile then
      ui_repaint = native.cpu_profile("ui", self.ui.onTick, self.ui, ...)
    else ui_repaint = self.ui:onTick(...) end
    repaint = repaint or ui_repaint
  end
  if not native then return true end
  return repaint -- static menus retain a paced compatibility refresh
end'''
    if new not in text:text=replace_exact(text,old,new,'real World/UI profile and menu repaint')
    yield path,text
    path='CorsixTH/Src/th_map.h'
    text=(root/path).read_text()
    old='class level_map {'
    new='''#ifdef CORSIXTH_3DS
#include "cth3ds/thermal_grid.hpp"
#endif
class level_map {
#ifdef CORSIXTH_3DS
  cth3ds::ThermalGrid thermal_cache;
#endif'''
    if new not in text:text=replace_exact(text,old,new,'map-owned thermal stencil lifetime')
    yield path,text
    path='CorsixTH/Src/th_pathfind.cpp'
    text=(root/path).read_text()
    old='#include "th_pathfind.h"\n'
    new=old+'#ifdef CORSIXTH_3DS\n#include "cth3ds/cpu_work.hpp"\n#endif\n'
    if new not in text:text=replace_exact(text,old,new,'CPU path header')
    old='                                 int iStartY, int iEndX, int iEndY) {\n'
    new=old+'#ifdef CORSIXTH_3DS\n  cth3ds::CpuWorkScope cpu_scope(cth3ds::CpuWork::Pathfind);\n#endif\n'
    if new not in text:text=replace_exact(text,old,new,'CPU basic path timing')
    yield path,text

    yield from thermal_transforms(root)
    yield from world_transforms(root)
    yield from latency_transforms(root)
    yield from spatial_transforms(root)
    yield from save_transforms(root)

def patch_cpu_hotspots(root: Path, dry_run=False):
    changes=[]
    for name,text in transforms(root):
        path=root/name
        if path.read_text()!=text:
            changes.append(name)
            if not dry_run:path.write_text(text)
    return changes

def check_cpu_hotspots(root):
    try:return ['CPU hotspot site missing: '+p for p in patch_cpu_hotspots(root,True)]
    except (OSError,SoundPatchError) as e:return [str(e)]
