"""Language closure and original DAT metadata validation, including aliases."""
import hashlib
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from prepare_loose_assets import prepare, parse_original_sound
from th3ds_resource import ResourceError
from test_th3ds_resource_packer import make_fixture, sound_archive, pcm_wave


def add_loose_fixture(package, root):
    from test_playable_path import original_sources
    source,_,_=make_fixture(root/'asset-input')
    runtime=original_sources(root/'runtime-input')/'CorsixTH'
    if (package/'game').exists(): shutil.rmtree(package/'game')
    shutil.copytree(source,package/'game')
    prepare(runtime,source,package)


class PlayableAssetsTests(unittest.TestCase):
    def test_real_upstream_english_closure_is_staged_without_mutating_source(self):
        from test_playable_path import original_sources
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,_,_=make_fixture(root/'input')
            runtime=original_sources(root/'runtime')/'CorsixTH'
            (runtime/'Lua/languages/unused.lua').write_text('Language("Unused")\n')
            before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
            stage=root/'stage';shutil.copytree(source,stage/'game')
            shutil.copytree(runtime/'Lua/languages',stage/'Lua/languages')
            result=prepare(runtime,source,stage)
            self.assertEqual(set(result['language_files']),{'english.lua','original_strings.lua'})
            self.assertEqual(result['original_string_ids'],[0])
            self.assertEqual(result['sound_source_sha256'],result['sound_staged_sha256'])
            self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
            self.assertEqual({p.name for p in (stage/'Lua/languages').glob('*.lua')},{'english.lua','original_strings.lua'})

    def test_conflicting_alias_partial_overlap_and_truncation_fail(self):
        raw=sound_archive([('A.WAV',pcm_wave(bytes(100))),('B.WAV',pcm_wave(bytes(100)))])
        h=struct.unpack_from('<I',raw,len(raw)-4)[0];t=struct.unpack_from('<I',raw,h+50)[0]
        bad=bytearray(raw);bad[t+32:t+50]=bad[t:t+18]
        with self.assertRaises(ResourceError):parse_original_sound(bytes(bad))
        bad=bytearray(raw);struct.pack_into('<I',bad,t+32+18,4)
        with self.assertRaises(ResourceError):parse_original_sound(bytes(bad))
        with self.assertRaises(ResourceError):parse_original_sound(raw[:-10])

    def test_exact_original_alias_retains_numeric_index(self):
        raw=bytearray(sound_archive([('A.WAV',pcm_wave(bytes(100))),('B.WAV',pcm_wave(bytes(100)))]))
        h=struct.unpack_from('<I',raw,len(raw)-4)[0];t=struct.unpack_from('<I',raw,h+50)[0]
        raw[t+32:t+64]=raw[t:t+32]
        sounds,indices,reserved=parse_original_sound(bytes(raw))
        self.assertEqual(indices,[0,1]);self.assertEqual(sounds[0],sounds[1]);self.assertEqual(reserved,0)

    def test_language_missing_original_and_oversized_required_sound_fail(self):
        from test_playable_path import original_sources
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,_,_=make_fixture(root/'input');runtime=original_sources(root/'runtime')/'CorsixTH'
            stage=root/'stage';shutil.copytree(source,stage/'game')
            data=source/'DATA/LANG-0.DAT';saved=data.read_bytes();data.unlink()
            with self.assertRaises(ResourceError):prepare(runtime,source,stage)
            data.write_bytes(saved)
            (source/'SOUND/DATA/SOUND-0.DAT').write_bytes(sound_archive([('BIG.WAV',pcm_wave(bytes(2*1024*1024)))]))
            with self.assertRaises(ResourceError):prepare(runtime,source,stage)


class SoundInitializationTests(unittest.TestCase):
    def test_generated_consumer_preserves_state_on_each_preparation_failure(self):
        """Execute the actual generated method; the mixer seam records ownership."""
        import os
        import subprocess
        from test_playable_path import original_sources
        from integrate_corsixth import main as integrate
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            upstream = original_sources(root / 'upstream')
            self.assertEqual(integrate([str(upstream), '--overlay-root', str(ROOT)]), 0)
            source = (upstream / 'CorsixTH/Src/th_sound.cpp').read_text()
            begin = source.index('void sound_player::populate_from(')
            end = source.index('\nuint32_t sound_player::play(', begin)
            consumer = source[begin:end]
            harness = root / 'sound-init.cpp'
            harness.write_text(SOUND_INIT_SEAM + '\n' + consumer + '\n' + SOUND_INIT_CASES)
            binary = root / 'sound-init'
            built = subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17',
                                    '-DCORSIXTH_3DS', str(harness), '-o', str(binary)],
                                   capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn('PASS initial=4 replacement=4 retry=8 release=100', ran.stdout)


SOUND_INIT_SEAM = r'''
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <new>
#include <vector>
static int fail_at = -1, attempted = 0, staged_live = 0;
static void* staged[32]{};
void* operator new(std::size_t n) {
  const bool track = fail_at >= 0;
  if (track && attempted++ == fail_at) throw std::bad_alloc();
  void* p = std::malloc(n ? n : 1);
  if (!p) throw std::bad_alloc();
  if (track) { bool stored=false; for (auto& slot : staged) if (!slot) {
    slot=p; ++staged_live; stored=true; break;
  } assert(stored); }
  return p;
}
void operator delete(void* p) noexcept {
  for (auto& slot : staged) if (slot && slot==p) {slot=nullptr;--staged_live;break;}
  std::free(p);
}
void* operator new[](std::size_t n) {return ::operator new(n);}
void operator delete[](void* p) noexcept {::operator delete(p);}
void operator delete(void* p, std::size_t) noexcept {::operator delete(p);}
void operator delete[](void* p, std::size_t) noexcept {::operator delete(p);}
static bool allow_reserve = true;
namespace cth3ds { bool runtime_audio_reserve(size_t, const char*) {return allow_reserve;} }
struct Mix_Chunk { int id; };
static int freed=0, halted=0;
void Mix_FreeChunk(Mix_Chunk* p) {if (p) {++freed;delete p;}}
int Mix_HaltChannel(int) {++halted;return 0;}
void sound_observe(const char*,const char*,const char*,size_t,size_t) {}
struct sound_archive {size_t count;size_t get_number_of_sounds() const {return count;}};
class sound_player {
 public:
  static constexpr int number_of_channels=32;
  Mix_Chunk** sounds=nullptr;size_t sound_count=0;
  sound_archive* archive=nullptr;
  std::vector<uint64_t> used_at;
  std::vector<size_t> allocated_bytes;
  std::array<std::atomic<bool>,number_of_channels> finished{};
  std::array<int,number_of_channels> channels{};
  size_t cache_bytes=0;uint64_t cache_clock=0;
  ~sound_player() {populate_from(nullptr);}
  void populate_from(sound_archive*);
  size_t owner_bytes() const {return cache_bytes+sound_count*sizeof(Mix_Chunk*)+
    used_at.capacity()*sizeof(uint64_t)+allocated_bytes.capacity()*sizeof(size_t);}
  void release_channel(int c) {
    if (channels[c]) assert(allocated_bytes.size()==sound_count && sounds);
    channels[c]=0;
  }
};
'''

SOUND_INIT_CASES = r'''
int main() {
  sound_archive old_archive{747}, new_archive{13}, empty_archive{0};
  for (bool replace : {false,true}) for (int failure=-1;failure<3;++failure) {
    sound_player p;
    if (replace) {
      p.populate_from(&old_archive);
      p.sounds[1]=new Mix_Chunk{17};p.allocated_bytes[1]=99;
      p.cache_bytes=99;p.used_at[1]=31;p.cache_clock=31;p.channels[0]=1;
    }
    auto old_sounds=p.sounds;auto old_used=p.used_at.data();
    auto old_allocated=p.allocated_bytes.data();auto old_owner=p.owner_bytes();
    int old_freed=freed,old_halted=halted;
    attempted=0;fail_at=failure;allow_reserve=failure!=-1;
    bool caught=false;
    try {p.populate_from(&new_archive);} catch (const std::bad_alloc&) {caught=true;}
    fail_at=-1;allow_reserve=true;
    assert(caught && (failure==-1 || attempted==failure+1));
    assert(staged_live==0 && freed==old_freed && halted==old_halted);
    assert(p.sounds==old_sounds && p.used_at.data()==old_used &&
           p.allocated_bytes.data()==old_allocated && p.owner_bytes()==old_owner);
    assert(p.archive==(replace ? &old_archive : nullptr));
    assert(p.sound_count==(replace ? 747u : 0u));
    if (replace) assert(p.sounds[1]->id==17 && p.channels[0]==1 && p.cache_clock==31);
    p.populate_from(&new_archive); // Same object retries after every failure.
    assert(p.sound_count==13 && p.archive==&new_archive && p.cache_bytes==0);
    assert(p.used_at.size()==13 && p.allocated_bytes.size()==13);
    assert(p.cache_clock==0 && p.channels[0]==0 && p.sounds[0]==nullptr);
    assert(freed==old_freed+(replace ? 1 : 0));
    p.populate_from(&new_archive); // Valid same-archive replacement.
    p.populate_from(&empty_archive);
    assert(p.sound_count==0 && p.sounds==nullptr && p.owner_bytes()==0);
    p.populate_from(nullptr);assert(p.archive==nullptr && p.owner_bytes()==0);
  }
  for (int i=0;i<100;++i) {
    sound_player p;p.populate_from(&old_archive);p.sounds[1]=new Mix_Chunk{19};
    fail_at=0;attempted=0;allow_reserve=false;
    p.populate_from(nullptr); // Cleanup must allocate nothing or require reserve.
    assert(attempted==0 && p.sound_count==0 && p.sounds==nullptr && p.owner_bytes()==0);
    fail_at=-1;allow_reserve=true;
  }
  assert(staged_live==0);
  std::cout << "PASS initial=4 replacement=4 retry=8 release=100\n";
}
'''
