"""Small, pinned real-call-site CPU changes; desktop equations unchanged."""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError

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
        if new not in text:text=replace_exact(text,old,new,'CPU temperature site')
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
