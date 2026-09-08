"""Verified original upstream fixtures and disposable assembly for product tests.

All source hashes and repeated-generation checks are preserved. No game data.
The integrator may write only the disposable overlay, never the checkout under test.
"""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/pinned_upstream'
SOURCE_HASHES = json.loads((FIXTURE / 'sha256.json').read_text())

def original_sources(root):
    files=json.loads(zlib.decompress(base64.b64decode((FIXTURE / 'sources.zlib.b64').read_bytes())))
    files['CorsixTH/Src/th_gfx_sdl.h'] = (ROOT/'tests/fixtures/th_gfx_sdl.h.pinned').read_text(encoding='utf-8')
    files['CorsixTH/Src/th_map.h'] = (ROOT/'tests/fixtures/th_map.h.pinned').read_text(encoding='utf-8')
    files['CorsixTH/Src/th_pathfind.cpp'] = (ROOT/'tests/fixtures/th_pathfind.cpp.pinned').read_text(encoding='utf-8')
    files['CorsixTH/Src/th_lua_map.cpp'] = (ROOT/'tests/fixtures/th_lua_map.cpp.pinned').read_text(encoding='utf-8')
    files['CorsixTH/Lua/world.lua'] = (ROOT/'tests/fixtures/world.lua.pinned').read_text(encoding='utf-8')
    files['CorsixTH/Lua/dialogs/resizables/file_browsers/save_game.lua'] = (ROOT/'tests/fixtures/save_game.lua.pinned').read_text(encoding='utf-8')
    for name in ('sdl_audio.cpp', 'th_gfx_font.h', 'th_gfx_font.cpp', 'th_strings.h', 'th_strings.cpp', 'persist_lua.cpp', 'persist_lua.h', 'th_lua.h', 'th_lua.cpp', 'lua.hpp'):
        files['CorsixTH/Src/' + name] = (ROOT/'tests/fixtures'/ (name + '.pinned')).read_text(encoding='utf-8')
    files['CorsixTH/Lua/entities/humanoid.lua'] = (ROOT/'tests/fixtures/humanoid.lua.pinned').read_text(encoding='utf-8')
    files['CorsixTH/Lua/entity_map.lua'] = (ROOT/'tests/fixtures/entity_map.lua.pinned').read_text(encoding='utf-8')
    files['CorsixTH/Lua/entities/humanoids/staff.lua'] = (ROOT/'tests/fixtures/staff.lua.pinned').read_text(encoding='utf-8')
    files['CorsixTH/Lua/dialogs/resizables/sound_setting.lua'] = (ROOT/'tests/fixtures/sound_setting.lua.pinned').read_text(encoding='utf-8')
    for name,text in files.items():
        assert hashlib.sha256(text.encode()).hexdigest()==SOURCE_HASHES[name]
        path=root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(text,encoding='utf-8')
    return root

def generated_sources(directory):
    """Generate from the pinned sources and a private copy of this checkout."""
    generated = original_sources(directory / 'upstream')
    originals = {str(path.relative_to(generated)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in generated.rglob('*') if path.is_file()}
    if originals != SOURCE_HASHES or len(originals) != 40:
        raise RuntimeError('pinned upstream source inventory/hash mismatch')
    overlay = directory / 'overlay'
    tracked = subprocess.check_output(
        ['git', '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')
    before = {}
    for name in filter(None, tracked):
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError('overlay requires regular tracked file: ' + name)
        target = overlay / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        # The integrator owns only this disposable export, even for read-only checkouts.
        target.chmod(target.stat().st_mode | 0o200)
        before[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    def hashes(root):
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob('*') if path.is_file()}
    first = None
    for attempt in (1, 2):
        result = subprocess.run([
            sys.executable, '-B', str(overlay / 'tools/integrate_corsixth.py'),
            str(generated), '--overlay-root', str(overlay)],
            capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('integration %d failed: %s\n%s' %
                               (attempt, result.stdout, result.stderr))
        current = hashes(generated)
        if first is not None and current != first:
            raise RuntimeError('repeat generation changed file inventory or bytes')
        first = current
    if hashes(overlay) != before:
        after = hashes(overlay)
        changed = sorted(name for name in before.keys() | after.keys()
                         if before.get(name) != after.get(name))
        raise RuntimeError('integration changed exported overlay bytes: ' + ', '.join(changed))
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest
           for name, digest in before.items()):
        raise RuntimeError('integration changed the tested checkout')
    return generated
