"""Generated slice bytes/cursors and actual runtime fresh audio admission."""
import os
from pathlib import Path
import shlex
import struct
import subprocess
import tempfile
import unittest

from support.pinned_upstream import generated_sources
from test_save_memory import native_inputs
from test_sound_lifetime import helper

ROOT = Path(__file__).resolve().parents[1]


class R67SoundObservationTests(unittest.TestCase):
    def test_generated_slice_and_fresh_runtime_admission(self):
        runtime = (ROOT / 'src/3ds/runtime_3ds.cpp').read_text()
        observe = runtime[runtime.index('void runtime_observe_memory(const char* checkpoint,'):
                          runtime.index('void runtime_note_timer_event()')]
        reserve = runtime[runtime.index('bool runtime_audio_reserve('):
                          runtime.index('void runtime_tick(lua_State*')]
        compiler, _, _ = native_inputs()
        with tempfile.TemporaryDirectory(prefix='cth-r67-sound-') as name:
            directory = Path(name)
            generated = generated_sources(directory)
            sound = (generated / 'CorsixTH/Src/th_sound.cpp').read_text()
            # Compile the complete generated anonymous slice/WAV helper block.
            # No reimplementation of read, seek, close, or WAV parsing.
            slice_methods = sound[sound.index('void sound_observe('):
                                  sound.index('\n}\n\nbool sound_archive::load_from_file')]
            wave = helper('make_audio_fixtures').wave(400, 0x85)
            body = wave[8:12] + b'JUNK' + struct.pack('<I', 3) + b'abc\0' + wave[12:]
            extra_wave = b'RIFF' + struct.pack('<I', len(body)) + body
            (directory / 'extra.wav').write_bytes(extra_wave)
            (directory / 'truncated.wav').write_bytes(extra_wave[:-7])
            (directory / 'shrinking.wav').write_bytes(extra_wave)
            code = r'''
#include <algorithm>
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <new>
#include <string>
#include <unistd.h>
#include <SDL.h>
#include "cth3ds/allocation_watch.hpp"
#include "cth3ds/memory_telemetry.hpp"
namespace cth3ds {
std::uint64_t time_us{},snapshots{},lua_queries{},recorded{},fail_logs{};
std::uint64_t available=16*kMiB;
std::uint64_t now_us() noexcept {return time_us;}
enum class CpuWork {MemoryObserve};
struct CpuWorkScope {explicit CpuWorkScope(CpuWork) {}};
struct Heap {
 std::uint64_t heap_total=52*kMiB,arena{},uordblks{},fordblks{},linear_total=8*kMiB,
 linear_free{},lua_bytes{},heap_available_estimate=available;
};
Heap heap_snapshot() {++snapshots;return {};}
void* g_observation_state=reinterpret_cast<void*>(1);
void update_lua_memory(void*) {++lua_queries;}
struct Observations {void observe(const char*,const MemoryObservation&) {++recorded;}} g_observations;
const char* g_current_stage="test";
MemoryObservationGate g_memory_sampling;
AllocationWatch g_lua_allocations;
struct Pressure {size_t count{},bytes{};void request(size_t n){++count;bytes=n;}} g_memory_pressure;
void boot_log(const char*,...) {}
void boot_log_memory(const char*) {++fail_logs;}
// ACTUAL_OBSERVE
// ACTUAL_RESERVE
}
uint32_t bytes_to_uint32_le(const uint8_t* p) {
 return uint32_t(p[0]) | uint32_t(p[1])<<8 | uint32_t(p[2])<<16 | uint32_t(p[3])<<24;
}
// GENERATED_SLICE
void close_checked(SDL_RWops* rw) {
 const int fd=fileno(static_cast<SoundSlice*>(rw->hidden.unknown.data1)->file);
 assert(SDL_RWclose(rw)==0);errno=0;
 assert(fcntl(fd,F_GETFD)==-1 && errno==EBADF);
}
int main(int argc,char** argv) {
 using namespace cth3ds;
 assert(argc==2);const std::string root=argv[1];
 // An ordinary observation sees ample memory. At the same timestamp the
 // actual reserve method must see a sudden drop and reject immediately.
 sound_observe("sound_read","before","fresh",4,0);
 assert(snapshots==1 && recorded==1);
 available=3*kMiB;
 assert(!runtime_audio_reserve(kMiB,"drop"));
 assert(snapshots==2 && recorded==1 && g_memory_pressure.count==1);
 assert(g_memory_pressure.bytes==kMiB);
 // Simulated owner eviction restores headroom. Retry must read it afresh.
 available=8*kMiB;
 assert(runtime_audio_reserve(kMiB,"after-eviction"));
 assert(snapshots==3 && recorded==1 && g_memory_pressure.count==1);
 available=4*kMiB;
 assert(!runtime_audio_reserve(1,"post-reserve-headroom"));
 assert(snapshots==4 && g_memory_pressure.count==2);
 available=8*kMiB;
 assert(!runtime_audio_reserve(9*kMiB,"larger-than-available"));
 assert(snapshots==5 && g_memory_pressure.count==3);
 assert(runtime_audio_reserve(kMiB,"fresh-retry"));assert(snapshots==6);

 const auto path=root+"/extra.wav";
 FILE* file=std::fopen(path.c_str(),"rb");assert(file);
 assert(!std::fseek(file,0,SEEK_END));const auto length=std::ftell(file);std::fclose(file);
 SDL_RWops* rw=open_slice(path,0,length);assert(rw);
 WaveInfo info;assert(wave_info(rw,info));
 assert(info.rate==22050 && info.channels==1 && info.bits==8 && info.bytes==400);
 assert(SDL_RWtell(rw)==length);
 unsigned char bytes[512]{};
 const auto before_eof=recorded;
 assert(SDL_RWread(rw,bytes,1,4)==0 && SDL_RWtell(rw)==length);
 assert(recorded==before_eof); // Known zero-byte EOF observations share the gate.
 assert(SDL_RWseek(rw,0,RW_SEEK_SET)==0);
 assert(SDL_RWread(rw,bytes,2,2)==2 && !std::memcmp(bytes,"RIFF",4));
 assert(SDL_RWtell(rw)==4);
 assert(SDL_RWread(rw,bytes,0,4)==0 && SDL_RWtell(rw)==4);
 assert(SDL_RWseek(rw,-1,RW_SEEK_SET)==-1 && SDL_RWtell(rw)==4);
 assert(SDL_RWseek(rw,length+1,RW_SEEK_SET)==-1 && SDL_RWtell(rw)==4);
 assert(SDL_RWseek(rw,56,RW_SEEK_SET)==56);
 assert(SDL_RWread(rw,bytes,4,100)==100 && SDL_RWtell(rw)==length);
 for(size_t i=0;i<400;++i)assert(bytes[i]==0x85);
 assert(SDL_RWread(rw,bytes,4,1)==0 && SDL_RWtell(rw)==length);
 close_checked(rw);

 // The real SDL WAV reader takes its own header reads through the same slice.
 rw=open_slice(path,0,length);assert(rw);
 SDL_AudioSpec spec{};Uint8* pcm=nullptr;Uint32 pcm_length=0;
 assert(SDL_LoadWAV_RW(rw,0,&spec,&pcm,&pcm_length));
 assert(spec.freq==22050 && spec.channels==1 && spec.format==AUDIO_U8 && pcm_length==400);
 for(size_t i=0;i<pcm_length;++i)assert(pcm[i]==0x85);
 SDL_FreeWAV(pcm);close_checked(rw);

 assert(!open_slice(root+"/truncated.wav",0,length));
 rw=open_slice(root+"/truncated.wav",0,length-7);assert(rw);
 WaveInfo truncated;assert(!wave_info(rw,truncated));close_checked(rw);
 // Open-valid, then physical short read: both partial and zero reads must log
 // immediately even after a normal sample at this exact microsecond.
 const auto shrinking=root+"/shrinking.wav";
 rw=open_slice(shrinking,0,length);assert(rw);
 auto* slice=static_cast<SoundSlice*>(rw->hidden.unknown.data1);
 assert(!std::setvbuf(slice->file,nullptr,_IONBF,0));
 assert(!truncate(shrinking.c_str(),2));
 g_memory_sampling={};sound_observe("sound_read","before","short",4,0);
 const auto sampled=snapshots,logged=fail_logs;
 assert(SDL_RWread(rw,bytes,1,4)==2 && SDL_RWtell(rw)==2);
 assert(snapshots==sampled+1 && fail_logs==logged+1);
 assert(SDL_RWread(rw,bytes,1,4)==0 && SDL_RWtell(rw)==2);
 assert(snapshots==sampled+2 && fail_logs==logged+2);
 close_checked(rw);
 std::puts("PASS generated slice extra RIFF chunk/PCM/EOF/truncation/cursors/close; actual reserve fresh reject and eviction retry");
}
'''.replace('// ACTUAL_OBSERVE', observe).replace('// ACTUAL_RESERVE', reserve).replace(
                '// GENERATED_SLICE', slice_methods)
            source = directory / 'probe.cpp'
            source.write_text(code)
            binary = directory / 'probe'
            command = [*compiler, '-std=c++17', '-O1', '-g',
                       '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                       '-I' + str(ROOT / 'include'),
                       *shlex.split(subprocess.check_output(['pkg-config', '--cflags', 'sdl2'], text=True)),
                       str(source),
                       *shlex.split(subprocess.check_output(['pkg-config', '--libs', 'sdl2'], text=True)),
                       '-o', str(binary)]
            built = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(binary), str(directory)], capture_output=True,
                                    text=True, timeout=30,
                                    env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                                             UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS generated slice', result.stdout)
            print(result.stdout, end='')


if __name__ == '__main__':
    unittest.main()
