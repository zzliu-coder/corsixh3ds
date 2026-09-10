"""Real generated music entry points compiled against the host SDL mixer."""
import os
from pathlib import Path
import shlex
import subprocess
import sys

from test_playable_path import function_body

ROOT = Path(__file__).resolve().parents[2]


def run_probe(directory, audio, core):
    source = (ROOT / 'tests/runtime_support/music_event_sdl_probe.cpp').read_text()
    music_class = audio[audio.index('class music {'):audio.index('\nnamespace {')]
    bodies = '\n'.join(function_body(audio, signature) for signature in (
        'void audio_music_over_callback()', 'int l_play_music(',
        'int l_stop_music(', 'int l_free_music(', 'int l_destroy('))
    begin = core.index('        case SDL_USEREVENT_MUSIC_OVER:')
    end = core.index('        case SDL_USEREVENT_MUSIC_LOADED:', begin)
    source = source.replace('// INSERT_MUSIC_CLASS', music_class)
    source = source.replace('// INSERT_NATIVE_FUNCTIONS', bodies)
    source = source.replace('// INSERT_NATIVE_DISPATCH', core[begin:end])
    target = directory / 'music-event-actual.cpp'
    target.write_text(source)
    flags = shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'sdl2', 'SDL2_mixer'], text=True))
    binary = directory / 'music-event-actual'
    compiler = shlex.split(os.environ.get('CXX', 'c++'))
    build = subprocess.run([*compiler, '-std=c++17', '-O2', '-g',
        '-Wall', '-Wextra', '-Wconversion', '-Wsign-conversion', '-Werror',
        '-Wno-unused-parameter', '-DCORSIXTH_3DS=1',
        '-fsanitize=address,undefined', '-I' + str(ROOT / 'include'),
        str(target), *flags, '-o', str(binary)], capture_output=True, text=True)
    if build.returncode:
        raise RuntimeError(build.stdout + build.stderr)
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    if sys.platform == 'darwin':
        # Local sdl2-compat may retain its app-bundle install_name. Resolve the
        # declared pkg-config library only in this probe process, not globally.
        libdir = subprocess.check_output(
            ['pkg-config', '--variable=libdir', 'sdl2'], text=True).strip()
        environment['DYLD_LIBRARY_PATH'] = libdir + (
            ':' + environment['DYLD_LIBRARY_PATH']
            if environment.get('DYLD_LIBRARY_PATH') else '')
    return subprocess.run([str(binary)], capture_output=True, text=True,
                          timeout=30, env=environment)
