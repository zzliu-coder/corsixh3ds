"""Playable boot, original assets and save/load integration."""

from __future__ import annotations

from handheld_ui import patch_handheld_ui, check_handheld_ui
from load_recovery import patch_load_recovery, check_load_recovery
from pathlib import Path
from sound_callbacks import patch_sound_callbacks, check_sound_callbacks
from sound_lifetime import (sound_transaction, patch_sound_lifetime,
                            check_sound_lifetime, SoundPatchError)
from sprite_residency import patch_sprite_residency, check_sprite_residency
import shutil
import tempfile
from .common import (
    Change,
    IntegrationError,
    read_text,
    write_text,
)
from .source_patches import (
    patch_sources,
)
from .sound_init import (
    SOUND_INIT_R41_TRANSACTION,
    patch_sound_initialization,
)


def validate_product_upgrade(root: Path) -> None:
    # This boundary upgrade needs fresh pinned sources. Refuse an older already
    # assembled tree before mutating any file; repeated current assembly is safe.
    r68_markers={
        'CorsixTH/Lua/app.lua':'CORSIXTH_3DS_LOAD_CALLER_R68',
        'CorsixTH/Lua/persistance.lua':'CORSIXTH_3DS_LOAD_OWNER_R68',
        'CorsixTH/Lua/dialogs/resizables/file_browsers/save_game.lua':'CORSIXTH_3DS_SAVE_UI_R68',
        'CorsixTH/Lua/dialogs/resizables/file_browsers/load_game.lua':'CORSIXTH_3DS_LOAD_UI_R68',
    }
    for relative,required in r68_markers.items():
        path=root/relative
        if path.exists():
            previous=read_text(path)
            if 'CORSIXTH_3DS_PRODUCT_U1' in previous and required not in previous:
                raise IntegrationError('R68 requires fresh pinned assembly: '+relative+' missing '+required)
    save_path=root/'CorsixTH/Lua/dialogs/resizables/file_browsers/save_game.lua'
    if save_path.exists():
        previous=read_text(save_path)
        if 'CORSIXTH_3DS_PRODUCT_U1' in previous and 'CORSIXTH_3DS_SAVE_OWNER_R74' not in previous:
            raise IntegrationError('R74 requires fresh pinned assembly: save UI missing CORSIXTH_3DS_SAVE_OWNER_R74')


def patch_product_sources(root: Path, dry_run: bool) -> list[Change]:
    validate_product_upgrade(root)
    if dry_run:
        with tempfile.TemporaryDirectory(prefix="cth3ds-product-preview-") as temp:
            preview=Path(temp)/"upstream"
            shutil.copytree(root,preview,ignore=shutil.ignore_patterns(".git"))
            patch_sources(preview,False)
            changes = patch_product_sources(preview,False) + patch_sound_initialization(preview)
            changes.extend(Change(path, "sound-lifetime") for path in
                           patch_sound_lifetime(preview, SOUND_INIT_R41_TRANSACTION))
            changes.extend(Change(path, "load-recovery") for path in
                           patch_load_recovery(preview))
            changes.extend(Change(path, "sound-callbacks") for path in
                           patch_sound_callbacks(preview))
            changes.extend(Change(path, "sprite-residency") for path in
                           patch_sprite_residency(preview))
            changes.extend(Change(path, "handheld-ui") for path in patch_handheld_ui(preview))
            return changes
    changes = []
    def patch(relative, replacements):
        path = root / relative
        if not path.exists():
            raise IntegrationError(f"missing product target: {relative}")
        text = read_text(path)
        marker = "CORSIXTH_3DS_PRODUCT_U1"
        if marker in text:
            return
        for old, new in replacements:
            if old not in text:
                raise IntegrationError(f"product anchor missing in {relative}: {old[:80]}")
            text = text.replace(old, new)
        if relative in ("CorsixTH/Lua/audio.lua", "CorsixTH/Lua/game_ui.lua", "CorsixTH/Lua/persistance.lua"):
            text = 'local native_ok, TH3DS = pcall(require,"th3ds")\nlocal IS_3DS = native_ok and TH3DS.is_platform()\n' + text
        prefix = "-- " if relative.endswith(".lua") else "// "
        write_text(path, prefix + marker + "\n" + text, dry_run)
        changes.append(Change(relative, "product-u1"))
    patch('CorsixTH/Src/th_sound.h', [
        ('#include <array>',
         r'''#include <array>
#ifdef CORSIXTH_3DS
#include <atomic>
#include <string>
#endif'''),
        ('  bool load_from_th_file',
         r'''#ifdef CORSIXTH_3DS
  bool load_from_file(const char* path);
  bool pcm_requirement(size_t index, size_t& converted, size_t& scratch);
  size_t metadata_bytes() const;
#endif
  bool load_from_th_file'''),
        ('  std::vector<uint8_t> data;',
         r'''#ifdef CORSIXTH_3DS
  std::string file_path;
#endif
  std::vector<uint8_t> data;'''),
        ('  Mix_Chunk** sounds;',
         r'''#ifdef CORSIXTH_3DS
 public:
  size_t cached_bytes() const {return cache_bytes;}
  size_t owner_bytes() const {return cache_bytes+(archive?archive->metadata_bytes():0)+sound_count*sizeof(Mix_Chunk*)+used_at.capacity()*sizeof(uint64_t)+allocated_bytes.capacity()*sizeof(size_t)+sizeof(*this);}
  size_t pinned_bytes() const {size_t total=0;for(size_t j=0;j<sound_count;++j){bool pin=false;for(int c=0;c<number_of_channels;++c)if(channels[c]!=null_handle&&channel_sound[c]==j)pin=true;if(pin)total+=allocated_bytes[j]+sizeof(Mix_Chunk);}return total;}
  size_t decoded_clip_count() const {size_t n=0;for(size_t i=0;i<sound_count;++i)if(sounds[i])++n;return n;}
 private:
  sound_archive* archive{nullptr}; // Lua soundEffects environment retains archive.
  std::array<std::atomic<bool>, number_of_channels> finished{};
  std::array<size_t, number_of_channels> channel_sound{};
  std::vector<uint64_t> used_at;
  std::vector<size_t> allocated_bytes;
  size_t cache_bytes{0};
  uint64_t cache_clock{0};
  void drain_finished();
  bool ensure_sound(size_t index);
#endif
  Mix_Chunk** sounds;'''),
    ])
    patch('CorsixTH/Src/th_sound.cpp', [
        ('#include "th.h"',
         r'''#include "th.h"
#ifdef CORSIXTH_3DS
#include "3ds/runtime_3ds.hpp"
#include <cstdio>
#include <memory>
#include <climits>
#endif
#ifdef CORSIXTH_3DS
namespace {
void sound_observe(const char* site,const char* phase,const char* id,size_t request,size_t held,bool failed=false) {
  cth3ds::runtime_observe_memory(site,phase,id,cth3ds::MemoryGate::Operation,request,true,held,true,failed,true);
}
struct SoundSlice { FILE* file; Sint64 start, length, cursor; };
Sint64 slice_size(SDL_RWops* rw) { return static_cast<SoundSlice*>(rw->hidden.unknown.data1)->length; }
Sint64 slice_seek(SDL_RWops* rw, Sint64 offset, int whence) {
  auto* s = static_cast<SoundSlice*>(rw->hidden.unknown.data1);
  Sint64 base = whence == RW_SEEK_SET ? 0 : whence == RW_SEEK_CUR ? s->cursor : whence == RW_SEEK_END ? s->length : -1;
  if (base < 0 || offset < -base || offset > s->length-base) return -1;
  if (std::fseek(s->file, static_cast<long>(s->start+base+offset), SEEK_SET)) return -1;
  return s->cursor = base+offset;
}
size_t slice_read(SDL_RWops* rw, void* ptr, size_t size, size_t count) {
  auto* s = static_cast<SoundSlice*>(rw->hidden.unknown.data1);
  if (!size) return 0;
  count = std::min(count, static_cast<size_t>(s->length-s->cursor)/size);
  char identity[96];std::snprintf(identity,sizeof(identity),"offset=%lld length=%lld cursor=%lld",(long long)s->start,(long long)s->length,(long long)s->cursor);
  sound_observe("sound_read","before",identity,size*count,0);
  size_t n=std::fread(ptr,size,count,s->file);s->cursor+=n*size;
  sound_observe("sound_read","after",identity,size*count,n*size,n!=count);return n;
}
size_t slice_write(SDL_RWops*, const void*, size_t, size_t) { return 0; }
int slice_close(SDL_RWops* rw) {
  auto* s = static_cast<SoundSlice*>(rw->hidden.unknown.data1);
  int result = std::fclose(s->file); delete s; SDL_FreeRW(rw); return result;
}
SDL_RWops* open_slice(const std::string& path, uint32_t start, uint32_t length) {
  FILE* f=std::fopen(path.c_str(),"rb"); if (!f) return nullptr;
  if (std::fseek(f,0,SEEK_END) || std::ftell(f)<static_cast<int64_t>(start)+length || std::fseek(f,start,SEEK_SET)) { std::fclose(f); return nullptr; }
  SDL_RWops* rw=SDL_AllocRW(); if (!rw) {std::fclose(f); return nullptr;}
  auto* s=new(std::nothrow) SoundSlice{f,start,length,0};
  if (!s) {std::fclose(f);SDL_FreeRW(rw);return nullptr;}
  rw->size=slice_size;rw->seek=slice_seek;rw->read=slice_read;rw->write=slice_write;rw->close=slice_close;
  rw->type=SDL_RWOPS_UNKNOWN;rw->hidden.unknown.data1=s;return rw;
}
struct WaveInfo { uint32_t rate=0, bytes=0; uint16_t channels=0,bits=0; };
bool wave_info(SDL_RWops* rw, WaveInfo& info) {
  uint8_t h[16]; const auto length=SDL_RWsize(rw);
  if (length<12 || SDL_RWread(rw,h,1,12)!=12 || std::memcmp(h,"RIFF",4) || std::memcmp(h+8,"WAVE",4)) return false;
  uint64_t end=uint64_t(bytes_to_uint32_le(h+4))+8;
  if (end>static_cast<uint64_t>(length)) return false;
  bool fmt=false,pcm=false;
  while (SDL_RWtell(rw)<static_cast<Sint64>(end)) {
    if (end-SDL_RWtell(rw)<8 || SDL_RWread(rw,h,1,8)!=8) return false;
    uint32_t n=bytes_to_uint32_le(h+4); uint64_t next=uint64_t(SDL_RWtell(rw))+n;
    if (next>end) return false;
    if (!std::memcmp(h,"fmt ",4)) {
      if (fmt || n<16 || SDL_RWread(rw,h,1,16)!=16) return false;
      info.channels=h[2]|h[3]<<8;info.rate=bytes_to_uint32_le(h+4);info.bits=h[14]|h[15]<<8;
      uint16_t align=h[12]|h[13]<<8;
      if ((h[0]|h[1]<<8)!=1 || (info.channels!=1&&info.channels!=2) || (info.bits!=8&&info.bits!=16) || info.rate<4000 || info.rate>192000 || align!=info.channels*(info.bits/8)) return false;
      fmt=true;
    } else if (!std::memcmp(h,"data",4)) { if(pcm) return false;info.bytes=n;pcm=true; }
    if (SDL_RWseek(rw,next+(n&1),RW_SEEK_SET)<0) return false;
  }
  return fmt&&pcm&&info.bytes&&info.bytes%(info.channels*(info.bits/8))==0;
}
}

bool sound_archive::load_from_file(const char* path) {
  if (!file_path.empty() || !path || !*path || std::strlen(path)>1024) return false;
  std::unique_ptr<FILE,decltype(&std::fclose)> f(std::fopen(path,"rb"),std::fclose);
  if (!f || std::fseek(f.get(),0,SEEK_END)) return false;
  long length=std::ftell(f.get());if(length<238 || length>INT32_MAX) return false;
  auto read=[&](uint32_t offset,void* dst,size_t n){return uint64_t(offset)+n<=uint64_t(length)&&!std::fseek(f.get(),offset,SEEK_SET)&&std::fread(dst,1,n,f.get())==n;};
  uint8_t h[234];if(!read(length-4,h,4)) return false;
  uint32_t hp=bytes_to_uint32_le(h);if(uint64_t(hp)+234>uint64_t(length)-4 || !read(hp,h,234))return false;
  uint32_t tp=bytes_to_uint32_le(h+50),tl=bytes_to_uint32_le(h+58);
  if(!tl || tl%32 || tl/32>4096 || uint64_t(tp)+tl>uint64_t(length)-4 || (tp<uint64_t(hp)+234 && hp<uint64_t(tp)+tl))return false;
  sound_observe("sound_index","before",path,tl,0);
  std::vector<sound_dat_sound_info> index;
  try{index.resize(tl/32);}catch(const std::bad_alloc&){sound_observe("sound_index","allocation-failed",path,tl,0,true);throw;}
  for(size_t i=0;i<index.size();++i) {
    uint8_t e[32];if(!read(tp+i*32,e,32))return false;
    auto& v=index[i];std::copy_n(e,18,v.sound_name.begin());
    v.position=bytes_to_uint32_le(e+18);v.length=bytes_to_uint32_le(e+26);
    // The original format reserves slot zero; animation sound index zero
    // means no sound. Retain its index and never open it as a WAV.
    if(i==0 && std::all_of(e,e+18,[](uint8_t c){return c==0;})) {v.length=0;continue;}
    if(!e[0] || !std::memchr(e,0,18) || !v.length || uint64_t(v.position)+v.length>uint64_t(length)-4 || (v.position<uint64_t(tp)+tl && tp<uint64_t(v.position)+v.length) || (v.position<uint64_t(hp)+234 && hp<uint64_t(v.position)+v.length))return false;
    for(size_t k=0;k<18&&e[k];++k)if(e[k]<32||e[k]>=127)return false;
    for(size_t j=0;j<i;++j) {
      const auto& other=index[j];if(!other.length)continue;
      bool same_name=!SDL_strcasecmp(v.sound_name.data(),other.sound_name.data());
      if(same_name && v.position==other.position && v.length==other.length)continue; // exact original alias
      if(same_name || (v.position<uint64_t(other.position)+other.length && other.position<uint64_t(v.position)+v.length))return false;
    }
  }
  data.clear();data.shrink_to_fit();file_path=path;sound_files.swap(index);
  sound_observe("sound_index","after",path,tl,metadata_bytes());
  sound_observe("sound_archive_copy","file-backed",path,0,0);
  return true;
}
size_t sound_archive::metadata_bytes() const {return sound_files.capacity()*sizeof(sound_dat_sound_info)+file_path.capacity()+sizeof(*this);}
bool sound_archive::pcm_requirement(size_t index,size_t& converted,size_t& scratch) {
  SDL_RWops* rw=load_sound(index);if(!rw)return false;
  WaveInfo w;bool valid=wave_info(rw,w);SDL_RWclose(rw);if(!valid)return false;
  int rate,channels;Uint16 format;if(!Mix_QuerySpec(&rate,&format,&channels))return false;
  SDL_AudioCVT cvt{};
  int result=SDL_BuildAudioCVT(&cvt,w.bits==8?AUDIO_U8:AUDIO_S16LSB,w.channels,w.rate,format,channels,rate);
  if(result<0 || cvt.len_mult<1)return false;
  uint64_t reserve=uint64_t(w.bytes)*cvt.len_mult;
  uint64_t output=(uint64_t(w.bytes)/(w.channels*(w.bits/8))*rate+w.rate-1)/w.rate;
  output=(output+64)*channels*(SDL_AUDIO_BITSIZE(format)/8);
  if(reserve>SIZE_MAX || output>SIZE_MAX)return false;
  converted=static_cast<size_t>(std::max<uint64_t>(reserve,output));
  scratch=static_cast<size_t>(reserve)+w.bytes+65536;
  return true;
}
#endif
'''),
        ('  if (iDataLength < sizeof(uint32_t)',
         r'''#ifdef CORSIXTH_3DS
  // Device callers must supply a file path; never allocate an archive copy.
  (void)pData; (void)iDataLength; return false;
#endif
  if (iDataLength < sizeof(uint32_t)'''),
        ('  sound_dat_sound_info pFile = sound_files[iIndex];',
         r'''  sound_dat_sound_info pFile = sound_files[iIndex];
#ifdef CORSIXTH_3DS
  if (!pFile.length) return nullptr;
  return open_slice(file_path, pFile.position, pFile.length);
#endif'''),
        ('sound_player::~sound_player() {', '''sound_player::~sound_player() {
#ifdef CORSIXTH_3DS
  Mix_ChannelFinished(nullptr); // synchronizes with mixer callbacks before destruction
#endif'''),
        ('  pThis->release_channel(iChannel);',
         r'''#ifdef CORSIXTH_3DS
  if (iChannel>=0 && iChannel<number_of_channels)
    pThis->finished[iChannel].store(true,std::memory_order_release);
#else
  pThis->release_channel(iChannel);
#endif'''),
        ('void sound_player::populate_from(sound_archive* pArchive) {',
         r'''void sound_player::populate_from(sound_archive* pArchive) {
#ifdef CORSIXTH_3DS
  Mix_HaltChannel(-1); // synchronous: no callback can access the freed bank
  for(int c=0;c<number_of_channels;++c) {finished[c].store(false);release_channel(c);}
  sound_observe("sound_release","bank-before","bank",0,owner_bytes());
  archive=pArchive;cache_bytes=0;used_at.clear();used_at.shrink_to_fit();allocated_bytes.clear();allocated_bytes.shrink_to_fit();
#endif'''),
        ('  sounds = new Mix_Chunk*[pArchive->get_number_of_sounds()];',
         r'''#ifdef CORSIXTH_3DS
  sound_count=pArchive->get_number_of_sounds();
  sounds=new Mix_Chunk*[sound_count]();used_at.resize(sound_count);allocated_bytes.resize(sound_count);
  sound_observe("sound_index","player-metadata","bank",0,owner_bytes());
  return;
#endif
  sounds = new Mix_Chunk*[pArchive->get_number_of_sounds()];'''),
        ('iIndex >= sound_count || !sounds[iIndex]',
         'iIndex >= sound_count'),
        (r'''  std::scoped_lock lock(channel_mutex);
  for (size_t i = 0; i < channels.size(); ++i) {''',
         r'''#ifdef CORSIXTH_3DS
  drain_finished();
#endif
  std::scoped_lock lock(channel_mutex);
  for (size_t i = 0; i < channels.size(); ++i) {'''),
        ('  channels[iChannel] = null_handle;',
         r'''  if(iChannel<0 || iChannel>=number_of_channels)return;
  channels[iChannel] = null_handle;
#ifdef CORSIXTH_3DS
  channel_sound[iChannel]=SIZE_MAX;
  sound_observe("sound_release","channel-after","pins",0,pinned_bytes());
#endif'''),
        ('  int iChannel = reserve_channel();',
         r'''#ifdef CORSIXTH_3DS
  if (!ensure_sound(iIndex)) {
    cth3ds::report_allocation_failure("sound",archive ? archive->get_sound_name(iIndex) : "no-archive",0,"mixer",SDL_GetError());
    cth3ds::report_fatal(SDL_GetError());
    return null_handle;
  }
#endif
  int iChannel = reserve_channel();'''),
        (r'''  Mix_Volume(iChannel, iVolume);
  Mix_PlayChannel(iChannel, sounds[iIndex], loops);''',
         r'''#ifdef CORSIXTH_3DS
  finished[iChannel].store(false,std::memory_order_release);
  channel_sound[iChannel]=iIndex;
#endif
  Mix_Volume(iChannel, iVolume);
#ifdef CORSIXTH_3DS
  sound_observe("sound_play","pin-before",archive->get_sound_name(iIndex),0,pinned_bytes());
#endif
  if (Mix_PlayChannel(iChannel, sounds[iIndex], loops)<0) {
#ifdef CORSIXTH_3DS
    sound_observe("sound_play","play-failed",archive->get_sound_name(iIndex),0,pinned_bytes(),true);
#endif
    release_channel(iChannel);return null_handle;
  }
#ifdef CORSIXTH_3DS
  sound_observe("sound_play","pin-after",archive->get_sound_name(iIndex),0,pinned_bytes());
#endif'''),
        (r'''  std::scoped_lock lock(channel_mutex);

  if (handle == null_handle)''',
         r'''#ifdef CORSIXTH_3DS
  drain_finished();
#endif
  std::scoped_lock lock(channel_mutex);

  if (handle == null_handle)'''),
        ('  if (pArchive == nullptr) return;', '''#ifdef CORSIXTH_3DS
  sound_observe("sound_release","bank-after","bank",0,owner_bytes());
#endif
  if (pArchive == nullptr) return;'''),
        ('sound_player* sound_player::singleton = nullptr;',
         r'''#ifdef CORSIXTH_3DS
void sound_player::drain_finished() {
  for (int i=0;i<number_of_channels;++i) {
    if (finished[i].exchange(false,std::memory_order_acquire)) {
      // Completion is delivered while the mixer lock is held. Mix_Playing
      // acquires that lock before a channel can be reused on this thread.
      if (!Mix_Playing(i)) release_channel(i);
    }
  }
}
bool sound_player::ensure_sound(size_t index) {
  drain_finished();
  if(index>=sound_count || !archive)return false;
  if(sounds[index]) {used_at[index]=++cache_clock;return true;}
  size_t pcm=0,scratch=0;
  if(!archive->pcm_requirement(index,pcm,scratch)) {SDL_SetError("invalid required sound slice/WAV/mixer");return false;}
  constexpr size_t limit=3*1024*1024;
  size_t metadata=owner_bytes()-cache_bytes;
  if(pcm+sizeof(Mix_Chunk)>limit || metadata>limit-pcm-sizeof(Mix_Chunk)) {SDL_SetError("required sound exceeds 3MiB PCM+metadata");return false;}
  while(cache_bytes+metadata+pcm+sizeof(Mix_Chunk)>limit) {
    size_t victim=sound_count;uint64_t oldest=UINT64_MAX;
    for(size_t j=0;j<sound_count;++j) {
      bool pinned=false;for(int c=0;c<number_of_channels;++c)if(channels[c]!=null_handle&&channel_sound[c]==j)pinned=true;
      if(sounds[j]&&!pinned&&used_at[j]<oldest){oldest=used_at[j];victim=j;}
    }
    if(victim==sound_count){SDL_SetError("audio cache pinned: required clip rejected");return false;}
    sound_observe("sound_evict","before",archive->get_sound_name(victim),allocated_bytes[victim]+sizeof(Mix_Chunk),owner_bytes());
    cache_bytes-=allocated_bytes[victim]+sizeof(Mix_Chunk);Mix_FreeChunk(sounds[victim]);sounds[victim]=nullptr;
    sound_observe("sound_evict","after",archive->get_sound_name(victim),0,owner_bytes());
  }
  // Actual conversion scratch plus operation reserve must coexist with cache.
  if(!cth3ds::runtime_audio_reserve(scratch+pcm+sizeof(Mix_Chunk),archive->get_sound_name(index)))return false;
  sound_observe("sound_decode","before",archive->get_sound_name(index),scratch+pcm,owner_bytes());
  SDL_RWops* rw=archive->load_sound(index);if(!rw)return false;
  Mix_Chunk* chunk=Mix_LoadWAV_RW(rw,1);if(!chunk){sound_observe("sound_decode","decode-failed",archive->get_sound_name(index),scratch+pcm,owner_bytes(),true);return false;}
  if(chunk->alen>pcm || cache_bytes+metadata+chunk->alen+sizeof(Mix_Chunk)>limit){Mix_FreeChunk(chunk);SDL_SetError("mixer output exceeded preflight");return false;}
  sounds[index]=chunk;allocated_bytes[index]=pcm;cache_bytes+=pcm+sizeof(Mix_Chunk);used_at[index]=++cache_clock;
  Mix_VolumeChunk(chunk,MIX_MAX_VOLUME);
  sound_observe("sound_decode","chunk-after",archive->get_sound_name(index),pcm,chunk->alen+sizeof(Mix_Chunk));
  sound_observe("sound_decode","owner-after",archive->get_sound_name(index),0,owner_bytes());
  return true;
}
#endif

sound_player* sound_player::singleton = nullptr;'''),
    ])
    patch('CorsixTH/Src/th_lua_sound.cpp', [
        ('int l_soundarc_count(lua_State* L) {',
         r'''#ifdef CORSIXTH_3DS
int l_soundarc_load_file(lua_State* L) {
  sound_archive* archive=luaT_testuserdata<sound_archive>(L);
  lua_pushboolean(L,archive->load_from_file(luaL_checkstring(L,2)));
  return 1;
}
#endif
int l_soundarc_count(lua_State* L) {'''),
        ('    lcb.add_function(l_soundarc_load, "load");',
         r'''    lcb.add_function(l_soundarc_load, "load");
#ifdef CORSIXTH_3DS
    lcb.add_function(l_soundarc_load_file, "loadFromFile");
#endif'''),
    ])
    patch('CorsixTH/Lua/audio.lua', [
        (r'''    self.not_loaded = true
    self.has_bg_music = false''',
         r'''    if IS_3DS then error("audio initialize: " .. tostring(err)) end
    self.not_loaded = true
    self.has_bg_music = false'''),
        (r'''function Audio:initSpeech(speech_file)
''',
         r'''function Audio:initSpeech(speech_file)
  if IS_3DS then
    speech_file=speech_file or "Sound-0.dat"
    if self.speech_file_name==speech_file then return true end
    assert(not self.not_loaded,"audio device unavailable")
    assert(not self.app.fs.provider,"loose sound requires physical files")
    local path,err=self.app.fs:_getFilePath("Sound"..pathsep.."Data"..pathsep..speech_file)
    assert(path,"sound path: "..tostring(err))
    local archive=TH.soundArchive()
    assert(archive:loadFromFile(path),"sound index invalid: "..path)
    if self.sound_fx then self.sound_fx:setSoundArchive(archive) else
      self.sound_fx=TH.soundEffects()
      self.sound_fx:setSoundArchive(archive)
    end
    self.sound_archive=archive
    self.speech_file_name=speech_file
    self:setSoundStage()
    return true
  end
'''),
    ])
    patch('CorsixTH/Lua/config_finder.lua', [
        ('    language = [[English]],',
         r'''    asset_mode = [[loose]],
    language = [[English]],'''),
        ("param(config_values, 'language')",
         "param(config_values, 'asset_mode') .. param(config_values, 'language')"),
    ])
    patch('CorsixTH/Lua/app.lua', [
        (r'''    -- CORSIXTH_3DS_BEGIN: platform-attach
    if IS_3DS then
      self.is_3ds = true
      self._3ds = require("3ds.platform").attach(self, TH3DS)
    end
    -- CORSIXTH_3DS_END: platform-attach
''',
         ''),
        ('    self.config.width = 640',
         r'''    self.config.asset_mode=self.config.asset_mode or "loose"
    assert(self.config.asset_mode=="loose", "Player entry requires loose; th3ds is an unsupported resource experiment")
    self.config.language="English"
    self.config.use_new_graphics=false
    self.config.audio_frequency=22050
    self.config.audio_channels=2
    self.config.width = 640'''),
        ('  self.good_install_folder = good_install_folder',
         r'''  if IS_3DS then assert(good_install_folder,"game filesystem prerequisites failed") end
  self.good_install_folder = good_install_folder'''),
        ('  self:initSavegameDir()',
         r'''  local saves_ok=self:initSavegameDir()
  if IS_3DS then assert(saves_ok,"save directory initialization failed") end'''),
        ('  th3ds_stage("S35", "VIDEO READY")',
         r'''  th3ds_stage("S35", "VIDEO READY")
  if IS_3DS then
    local ok,caps=TH3DS.initialize(self.config.asset_mode)
    assert(ok==true,tostring(caps))
    self._3ds_capabilities=caps
  end'''),
        ('  local language_load_success, language_error = self:initLanguage()',
         r'''  local language_load_success, language_error = self:initLanguage()
  if IS_3DS then assert(language_load_success,language_error) end'''),
        (r'''    self:loadMainMenu()
    self.audio:playRandomBackgroundTrack()''',
         r'''    self:loadMainMenu()
    -- CORSIXTH_3DS_BEGIN: platform-attach
    if IS_3DS then
      local module=TH3DS.adapter_module()
      module.attach(self,TH3DS,self._3ds_capabilities)
      self.is_3ds=true
      assert(TH3DS.mark_ready())
    end
    -- CORSIXTH_3DS_END: platform-attach
    self.audio:playRandomBackgroundTrack()'''),
        ('  if IS_3DS and not TH3DS.probe_regular_heap("LEVEL READY") then',
         '  if IS_3DS and not TH3DS.probe_regular_heap("LEVEL READY", "LevelStable") then'),
        ('    error("E-HEAP-PROBE: level has less than 2 MiB contiguous heap")',
         '    error("E-HEAP-PROBE: LevelStable policy failed; see requested probe and reserve in boot.log")'),
        ('  th3ds_stage("S120", "LEVEL READY")',
         '  th3ds_stage("S120", "LEVEL VALIDATING")'),
        ('  return SaveGameFile(self.savegame_dir .. filename)',
         '  return self:save(self.savegame_dir .. filename)'),
        (r'''  if self.world then
    self:worldExited()
  end
  return LoadGameFile(filepath)''',
         r'''  if not IS_3DS and self.world then self:worldExited() end
  return LoadGameFile(filepath)'''),
        (r'''      local status, err = pcall(self.load, self, self.savegame_dir .. self.command_line.load)
      if not status then
        err = _S.errors.load_prefix .. err
        print(err)
        self.ui:addWindow(UIInformation(self.ui, { err }))
      end''',
         r'''      -- CORSIXTH_3DS_LOAD_CALLER_R68
      local previous=self._3ds and self._3ds.operations.last
      local status, accepted, err = pcall(self.load, self, self.savegame_dir .. self.command_line.load)
      if not status or accepted ~= true then
        if not status then err=accepted end
        if IS_3DS then
          local result=self._3ds and self._3ds.operations.last
          if not (result~=previous and result and result.reported) then
            local message=type(err)=="string" and err or ("non-string Lua error ("..type(err)..")")
            message=(message:match("^[^\n]+") or message):sub(1,150)
            pcall(print,message)
            local shown=pcall(function()self.ui:addWindow(UIInformation(self.ui,{message}))end)
            if result~=previous and result then result.reported=shown end
          end
        else
          err = _S.errors.load_prefix .. tostring(err)
          print(err)
          self.ui:addWindow(UIInformation(self.ui, { err }))
        end
      end'''),
        (r'''function App:reset()
''',
         r'''function App:reset()
  if IS_3DS and self.world then
    local ok,result=pcall(self.save,self,self.savegame_dir.."recovery-before-reset.sav")
    if not ok or result~=true then return false,result end
  end
'''),
        ('  tracy.Message("Loading level: " .. (level_name or level or "map editor"))',
         r'''  if IS_3DS and err ~= true then status=false;err=err or "map loader rejected level" end
  tracy.Message("Loading level: " .. (level_name or level or "map editor"))'''),
        (r'''    error("E-HEAP-PROBE: LevelStable policy failed; see requested probe and reserve in boot.log")
  end
end''',
         r'''    error("E-HEAP-PROBE: LevelStable policy failed; see requested probe and reserve in boot.log")
  end
  th3ds_stage("S120", "LEVEL READY")
  return true
end'''),
    ])
    patch('CorsixTH/Lua/persistance.lua', [
        (r'''  local result, err, obj = persist.dump(state, MakePermanentObjectsTable(false))
  state.map:afterSave()''',
         r'''  local dumped, result, err, obj = pcall(function()
    return persist.dump(state, MakePermanentObjectsTable(false))
  end)
  local cleaned, cleanup_error = pcall(state.map.afterSave,state.map)
  if not dumped then error("save dump: "..tostring(result)) end
  if not cleaned then error("save afterSave: "..tostring(cleanup_error)) end'''),
        (r'''  local f = TheApp:writeToFileOrTmp(filename, "wb")
  f:write(data)
  f:close()''',
         r'''  local f,err
  if IS_3DS then f,err=io.open(filename,"wb") else f=TheApp:writeToFileOrTmp(filename,"wb") end
  assert(f,"save open: "..tostring(err))
  local wrote,result,write_error=pcall(f.write,f,data)
  local closed,close_result,close_error=pcall(f.close,f)
  if not wrote or not result then error("save write: "..tostring(write_error or result)) end
  if not closed or not close_result then error("save close: "..tostring(close_error or close_result)) end
  return true'''),
        (r'''function LoadGame(data)
''',
         r'''-- CORSIXTH_3DS_LOAD_OWNER_R68: preserve raw decode/publication errors.
local function loadDescription(value)
  if type(value)=="string" then return value:sub(1,240) end
  return "non-string Lua error ("..type(value)..")"
end
local function loadErrorValue(value)
  if type(value)=="string" and debug and debug.traceback then return debug.traceback(value,2) end
  return value
end
local function loadDiagnostic(message)
  local owner=TheApp._3ds and TheApp._3ds.operations
  local operation=owner and owner.current
  local callback=TH3DS and TH3DS.diagnostic_line or print
  if operation then return owner:diagnostic(operation,"load_report",callback,message) end
  return pcall(callback,message)
end
local function loadCleanup(value)
  local owner=TheApp._3ds and TheApp._3ds.operations
  if owner and owner.current then owner:cleanupFailure(owner.current,"publication_menu",value)
  elseif TH3DS and TH3DS.operation_block then pcall(TH3DS.operation_block) end
end
local function decodeGame(data)
'''),
        (r'''  if not TheApp:checkCompatibility(state.world.savegame_version, state.world.gfx_set) then return end
  state.ui:resync(TheApp.ui)''',
         r'''  if not TheApp:checkCompatibility(state.world.savegame_version, state.world.gfx_set) then
    return false,"incompatible savegame"
  end
  return state
end

local function publishGame(state)
  state.ui:resync(TheApp.ui)
  if TheApp.world then TheApp:worldExited() end'''),
        (r'''  TheApp.world:updateScreenBlueFilter()
end''',
         r'''  TheApp.world:updateScreenBlueFilter()
  return true
end

local function checkedPublish(state)
  local ok,result=xpcall(publishGame,loadErrorValue,state)
  if ok and result==true then return true end
  -- loadMainMenu normally returns nil. Validate the published safe state.
  local menu_ok,menu_error=xpcall(TheApp.loadMainMenu,loadErrorValue,TheApp)
  local safe_menu=menu_ok and TheApp.world==nil and TheApp.map==nil and type(TheApp.ui)=="table"
  if not safe_menu then
    if menu_ok then menu_error="main menu did not clear world/map and publish UI" end
    loadCleanup(menu_error)
  end
  local owner=TheApp._3ds and TheApp._3ds.operations
  if owner and owner.current then
    owner.current.publication_failed=true;owner.current.recovered_menu=safe_menu
  end
  local detail="load publication/afterLoad failed: "..loadDescription(result).."; prior progress: recovery-before-load.sav"
  loadDiagnostic(detail)
  return false,result
end

function LoadGame(data)
  local ok,state,err=xpcall(decodeGame,loadErrorValue,data)
  if not ok then return false,state end
  if not state then return false,err end
  return checkedPublish(state)
end'''),
        (r'''  local f = assert(io.open(filename, "rb"))
  local data = f:read("*a")
  f:close()
  LoadGame(data)''',
         r'''  local first_error,has_error=nil,false
  -- Validate committed final then backup. Never promote an uncommitted tmp.
  local paths=IS_3DS and {filename,filename..".bak"} or {filename}
  for _,path in ipairs(paths) do
    local f,err=io.open(path,"rb")
    if f then
      local read_ok,data,read_error=pcall(f.read,f,"*a")
      local close_ok,closed,close_error=pcall(f.close,f)
      if read_ok and data and close_ok and closed then
        local decoded,state,reason=xpcall(decodeGame,loadErrorValue,data)
        if decoded and state then return checkedPublish(state) end
        if decoded then err=reason else err=state end
      elseif not read_ok then err=data
      elseif not close_ok then err=closed
      elseif not data then err=read_error
      else err=close_error end
    end
    if not has_error then first_error=err;has_error=true end
    loadDiagnostic(path..": "..loadDescription(err))
  end
  return false,first_error'''),
    ])
    patch('CorsixTH/Lua/dialogs/resizables/file_browsers/save_game.lua', [
        ('''  local status, err = pcall(app.save, app, filename)
  if not status then''',
         '''  -- CORSIXTH_3DS_SAVE_UI_R68
  -- CORSIXTH_3DS_SAVE_OWNER_R74: the current App owns this operation.
  local operations = app._3ds and app._3ds.operations
  local previous = operations and operations.last
  local status, err = pcall(app.save, app, filename)
  if not status and operations then
    -- R68: the operation owns the original error and committed-file fact.
    -- Suppress duplicates only when this request actually displayed a notice.
    local result = operations.last
    if result ~= previous and result and result.reported then return end
    local message = type(err)=="string" and err or ("non-string Lua error ("..type(err)..")")
    message = (message:match("^[^\\n]+") or message):sub(1,150)
    local shown = pcall(function() ui:addWindow(UIInformation(ui,{message})) end)
    if result ~= previous and result then result.reported = shown end
    return
  end
  if not status then'''),
    ])
    patch('CorsixTH/Lua/dialogs/resizables/file_browsers/load_game.lua', [
        ('''  local status, err = pcall(app.load, app, name)
  if not status then''',
         '''  -- CORSIXTH_3DS_LOAD_UI_R68
  if app._3ds and app._3ds.operations then
    local operations=app._3ds.operations
    local previous=operations.last
    local called,accepted,detail=pcall(app.load,app,name)
    if called and accepted==true then return end
    if not called then detail=accepted end
    local result=operations.last
    if result~=previous and result and result.reported then return end
    local message=type(detail)=="string" and detail or ("non-string Lua error ("..type(detail)..")")
    message=(message:match("^[^\\n]+") or message):sub(1,150)
    -- The reader already recovered the menu or locked unsafe publication.
    -- Display must not attempt another menu transition or replace its error.
    local shown=pcall(function()app.ui:addWindow(UIInformation(app.ui,{message}))end)
    if result~=previous and result then result.reported=shown end
    return
  end
  local status, err = pcall(app.load, app, name)
  if not status then'''),
    ])
    patch('CorsixTH/Lua/game_ui.lua', [
        ('  local msg = mapeditor and _S.confirmation.quit_mapeditor or _S.confirmation.quit',
         '  local msg = IS_3DS and "Save and exit?" or (mapeditor and _S.confirmation.quit_mapeditor or _S.confirmation.quit)'),
        (r'''    self.app:loadMainMenu()
    -- Release the mouse regardless of setting''',
         r'''    if IS_3DS then return self.app._3ds:saveAndExit() end
    self.app:loadMainMenu()
    -- Release the mouse regardless of setting'''),
    ])
    patch('CorsixTH/Src/sdl_core.cpp', [
        (r'''  if (!cth3ds::runtime_initialize(L)) {
    std::fprintf(stderr, "CorsixTH 3DS: platform runtime initialization failed\n");
  }''',
         r'''  if (!cth3ds::runtime_assert_ready(L)) {
    cth3ds::runtime_shutdown(L);
    cth3ds::report_fatal("CorsixTH 3DS: mainloop requires completed ready state");
    return;
  }'''),
    ])
    patch('CorsixTH/SrcUnshared/main.cpp', [
        ('    // CORSIXTH_3DS_END: init-failure-guard',
         r'''#ifdef CORSIXTH_3DS
    cth3ds::runtime_shutdown(L.get());
#endif
    // CORSIXTH_3DS_END: init-failure-guard'''),
    ])
    return changes
