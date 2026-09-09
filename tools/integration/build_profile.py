"""Two explicit build identities; one checked common-source classification."""
from pathlib import Path
import re

from .common import IntegrationError

PROFILES = ('loose', 'resource-experiment')

def validate_profile(profile: str) -> str:
    if profile not in PROFILES:
        raise IntegrationError('invalid build profile: ' + str(profile))
    return profile

def common_groups(root: Path) -> dict[str, list[str]]:
    text = '\n'.join(line.split('#', 1)[0] for line in
                     (root/'src/common/sources.cmake').read_text().splitlines())
    pattern = r'set\(CTH3DS_(PLAYER|RESOURCE_EXPERIMENT|RESOURCE_TOOL)_SOURCES\s+([^)]*)\)'
    blocks = re.findall(pattern, text)
    if re.sub(pattern, '', text).strip() or [key for key, _ in blocks] != [
            'PLAYER', 'RESOURCE_EXPERIMENT', 'RESOURCE_TOOL']:
        raise IntegrationError('invalid common-source classification')
    groups = {key: body.split() for key, body in blocks}
    names = [name for entries in groups.values() for name in entries]
    if len(names) != len(set(names)) or any(not entries for entries in groups.values()):
        raise IntegrationError('empty or duplicate common-source classification')
    for name in names:
        path = root/'src/common'/name
        if not re.fullmatch(r'[a-z0-9_]+\.cpp', name) or path.is_symlink() or not path.is_file():
            raise IntegrationError('invalid or missing common source: ' + name)
    actual = {p.name for p in (root/'src/common').glob('*.cpp')}
    if actual != set(names):
        raise IntegrationError('unclassified common source: ' + repr(sorted(actual ^ set(names))))
    return groups

def common_sources(root: Path, profile: str = 'loose', *, all_sources=False) -> list[str]:
    validate_profile(profile)
    groups = common_groups(root)
    if all_sources:
        return [name for entries in groups.values() for name in entries]
    return groups['PLAYER'] + (groups['RESOURCE_EXPERIMENT'] if profile == 'resource-experiment' else [])

def cmake_contract(profile: str, names: list[str]) -> str:
    validate_profile(profile)
    sources = '\n'.join('  "${CTH3DS_PLATFORM_ROOT}/common/' + name + '"' for name in names)
    enabled = '1' if profile == 'resource-experiment' else '0'
    return ('set(CTH3DS_GENERATED_BUILD_PROFILE "' + profile + '")\n'
            'if(DEFINED CTH3DS_BUILD_PROFILE AND NOT CTH3DS_BUILD_PROFILE STREQUAL CTH3DS_GENERATED_BUILD_PROFILE)\n'
            '  message(FATAL_ERROR "build profile differs from complete generated view")\n'
            'endif()\n'
            'set(CTH3DS_BUILD_PROFILE "${CTH3DS_GENERATED_BUILD_PROFILE}" CACHE STRING "3DS build identity")\n'
            'set(CTH3DS_COMMON_SOURCES\n' + sources + ')\n'
            'target_compile_definitions(CorsixTH_lib PUBLIC CTH3DS_RESOURCE_EXPERIMENT=' + enabled + ')\n')
