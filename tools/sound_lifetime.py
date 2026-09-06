#!/usr/bin/env python3
"""Small, source-anchored lifetime corrections for the R41 sound consumers.

Runs AFTER R41's native initialization transaction. All allocating preparation
happens before a bank is published. No new runtime framework or cache is added.
"""
from __future__ import annotations
from pathlib import Path
from typing import Mapping

MARKER = 'CORSIXTH_3DS_SOUND_LIFETIME_V1'

class SoundPatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    """Accept a complete old or complete new block; refuse ambiguous edits."""
    if new in text:
        if text.count(new) != 1:
            raise SoundPatchError(f'duplicate completed block: {label}')
        return text
    if text.count(old) != 1:
        raise SoundPatchError(f'expected one source anchor: {label}')
    return text.replace(old, new, 1)


def sound_transaction(original: str) -> str:
    text = replace_exact(original,
        '  const size_t next_count = pArchive ? pArchive->get_number_of_sounds() : 0;',
        '''  const size_t next_count = pArchive ? pArchive->get_number_of_sounds() : 0;
  // Teardown never dereferences a borrowed Lua userdata. GC finalization order
  // is independent of the archive reference in the player's environment.
  const size_t next_archive_metadata = pArchive ? pArchive->metadata_bytes() : 0;''',
        'transaction metadata preparation')
    text = replace_exact(text, '  Mix_HaltChannel(-1);',
        '''  // Only the current owner may stop the global mixer. A retired Lua
  // userdata can be collected after a replacement player has started.
  if (singleton == this) Mix_HaltChannel(-1);''', 'transaction mixer ownership')
    return replace_exact(text, '  archive = pArchive;\n  cache_bytes = 0;',
        '  archive = pArchive;\n  archive_metadata_bytes = next_archive_metadata;\n  cache_bytes = 0;',
        'transaction metadata publication')

SET_ARCHIVE_OLD = '''int l_soundfx_set_archive(lua_State* L) {
  sound_player* pEffects = luaT_testuserdata<sound_player>(L);
  sound_archive* pArchive = luaT_testuserdata<sound_archive>(L, 2);
  pEffects->populate_from(pArchive);
  lua_settop(L, 2);
  luaT_setenvfield(L, 1, "archive");
  return 1;
}'''
SET_ARCHIVE_NEW = '''int l_soundfx_set_archive(lua_State* L) {
  sound_player* pEffects = luaT_testuserdata<sound_player>(L);
  sound_archive* pArchive = luaT_testuserdata<sound_archive>(L, 2);
#ifdef CORSIXTH_3DS
  // CORSIXTH_3DS_SOUND_LIFETIME_V1: prepare Lua ownership before native commit.
  if (pEffects != sound_player::get_singleton())
    return luaL_error(L, "sound player is no longer active");
  lua_settop(L, 2);
  lua_getfenv(L, 1);                  // 3: old environment, retained on stack
  lua_newtable(L);                   // 4: prepared replacement environment
  lua_pushnil(L);
  while (lua_next(L, 3) != 0) {
    lua_pushvalue(L, -2);            // duplicate key
    lua_pushvalue(L, -2);            // duplicate value
    lua_rawset(L, 4);
    lua_pop(L, 1);
  }
  lua_pushliteral(L, "archive");
  lua_pushvalue(L, 2);
  lua_rawset(L, 4);                  // every potentially allocating Lua write

  // End the C++ catch scope before calling Lua's error API (which may longjmp).
  const char* failure = nullptr;
  try {
    pEffects->populate_from(pArchive);
  } catch (const std::bad_alloc&) {
    failure = "sound bank: out of memory";
  } catch (...) {
    failure = "sound bank: native preparation failed";
  }
  if (failure) return luaL_error(L, "%s", failure);
  // A userdata environment replacement does not allocate. The prepared table
  // pins the archive before the native bank can be observed by another call.
  lua_setfenv(L, 1);
  lua_settop(L, 1);
#else
  pEffects->populate_from(pArchive);
  lua_settop(L, 2);
  luaT_setenvfield(L, 1, "archive");
#endif
  return 1;
}'''
LOAD_FILE_OLD = '''int l_soundarc_load_file(lua_State* L) {
  sound_archive* archive=luaT_testuserdata<sound_archive>(L);
  lua_pushboolean(L,archive->load_from_file(luaL_checkstring(L,2)));
  return 1;
}'''
LOAD_FILE_NEW = '''int l_soundarc_load_file(lua_State* L) {
  sound_archive* archive=luaT_testuserdata<sound_archive>(L);
  const char* path = luaL_checkstring(L, 2);
  bool loaded = false;
  const char* failure = nullptr;
  try {
    loaded = archive->load_from_file(path);
  } catch (const std::bad_alloc&) {
    failure = "sound index: out of memory";
  } catch (...) {
    failure = "sound index: native preparation failed";
  }
  if (failure) return luaL_error(L, "%s", failure);
  lua_pushboolean(L, loaded);
  return 1;
}'''
NEW_PLAYER_OLD = '''int l_soundfx_new(lua_State* L) {
  luaT_stdnew<sound_player>(L, luaT_environindex, true);
  return 1;
}'''
NEW_PLAYER_NEW = '''int l_soundfx_new(lua_State* L) {
#ifdef CORSIXTH_3DS
  // Allocate the environment before constructing the global mixer owner.
  lua_newtable(L);
  const char* failure = nullptr;
  try {
    luaT_stdnew<sound_player>(L, luaT_environindex, false);
  } catch (const std::bad_alloc&) {
    failure = "sound player: out of memory";
  } catch (...) {
    failure = "sound player: native construction failed";
  }
  if (failure) return luaL_error(L, "%s", failure);
  lua_pushvalue(L, -2);
  lua_setfenv(L, -2);
  lua_remove(L, -2);
#else
  luaT_stdnew<sound_player>(L, luaT_environindex, true);
#endif
  return 1;
}'''
CTOR_OLD = '''  singleton = this;
  Mix_AllocateChannels(number_of_channels);
  Mix_ChannelFinished(on_channel_finished);
  channels.fill(null_handle);'''
CTOR_NEW = '''#ifdef CORSIXTH_3DS
  for (auto& done : finished) done.store(false, std::memory_order_relaxed);
  channel_sound.fill(SIZE_MAX);
  // Mixer allocation may fail; preserve the old owner until it succeeds.
  if (Mix_AllocateChannels(number_of_channels) < number_of_channels)
    throw std::bad_alloc();
  if (singleton) singleton->populate_from(nullptr);
  singleton = this;
  Mix_ChannelFinished(on_channel_finished);
#else
  singleton = this;
  Mix_AllocateChannels(number_of_channels);
  Mix_ChannelFinished(on_channel_finished);
#endif
  channels.fill(null_handle);'''
DTOR_OLD = '''  Mix_ChannelFinished(nullptr); // synchronizes with mixer callbacks before destruction'''
DTOR_NEW = '''  if (singleton == this) {
    Mix_ChannelFinished(nullptr); // detach this owner's callback synchronously
  }'''


def replacements(original_transaction: str) -> Mapping[str, list[tuple[str, str, str]]]:
    return {
        'th_sound.h': [
            ('cache_bytes+(archive?archive->metadata_bytes():0)+sound_count', 'cache_bytes+archive_metadata_bytes+sound_count', 'owner accounting'),
            ('  sound_archive* archive{nullptr}; // Lua soundEffects environment retains archive.',
             '''  sound_archive* archive{nullptr}; // Lua soundEffects environment retains archive.
  size_t archive_metadata_bytes{0}; // value snapshot; safe after archive finalization''', 'metadata field'),
        ],
        'th_sound.cpp': [
            (original_transaction, sound_transaction(original_transaction), 'native transaction'),
            (CTOR_OLD, CTOR_NEW, 'native constructor'),
            (DTOR_OLD, DTOR_NEW, 'native destructor'),
            ('''  if(reserve>SIZE_MAX || output>SIZE_MAX)return false;
  converted=static_cast<size_t>(std::max<uint64_t>(reserve,output));
  scratch=static_cast<size_t>(reserve)+w.bytes+65536;''',
             '''  const uint64_t scratch_needed = reserve + uint64_t(w.bytes) + 65536U;
  if(reserve>SIZE_MAX || output>SIZE_MAX || scratch_needed>SIZE_MAX)return false;
  converted=static_cast<size_t>(std::max<uint64_t>(reserve,output));
  scratch=static_cast<size_t>(scratch_needed);''', '32-bit scratch arithmetic'),
            ('if(pcm+sizeof(Mix_Chunk)>limit || metadata>limit-pcm-sizeof(Mix_Chunk))',
             'if(pcm>limit-sizeof(Mix_Chunk) || metadata>limit-pcm-sizeof(Mix_Chunk))', 'overflow-free cache bound'),
            ('''#ifdef CORSIXTH_3DS
  drain_finished();
#endif
  std::scoped_lock lock(channel_mutex);
  for (size_t i = 0; i < channels.size(); ++i) {''',
             '''#ifdef CORSIXTH_3DS
  if (singleton != this) return -1;
  drain_finished();
#endif
  std::scoped_lock lock(channel_mutex);
  for (size_t i = 0; i < channels.size(); ++i) {''', 'retired channel reservation'),
        ],
        'th_lua_sound.cpp': [
            (SET_ARCHIVE_OLD, SET_ARCHIVE_NEW, 'Lua archive publication'),
            (LOAD_FILE_OLD, LOAD_FILE_NEW, 'Lua archive error boundary'),
            (NEW_PLAYER_OLD, NEW_PLAYER_NEW, 'Lua player construction'),
        ],
    }


def planned_sources(root: Path, original_transaction: str) -> dict[Path, str]:
    """Validate every anchor before writing any file."""
    result: dict[Path, str] = {}
    for name, edits in replacements(original_transaction).items():
        path = root / 'CorsixTH' / 'Src' / name
        text = path.read_text(encoding='utf-8')
        for old, new, label in edits:
            text = replace_exact(text, old, new, f'{name}: {label}')
        result[path] = text
    return result


def patch_sound_lifetime(root: Path, original_transaction: str, dry_run: bool = False) -> list[str]:
    plan = planned_sources(root, original_transaction)
    changed: list[str] = []
    for path, text in plan.items():
        if path.read_text(encoding='utf-8') == text:
            continue
        changed.append(path.relative_to(root).as_posix())
        if not dry_run:
            temp = path.with_name(path.name + '.cth3ds-lifetime.tmp')
            with temp.open('w', encoding='utf-8', newline='\n') as stream:
                stream.write(text)
            temp.replace(path)
    return changed


def check_sound_lifetime(root: Path, original_transaction: str) -> list[str]:
    try:
        plan = planned_sources(root, original_transaction)
        return [f'sound lifetime patch missing: {path.relative_to(root)}'
                for path, text in plan.items() if path.read_text(encoding='utf-8') != text]
    except (OSError, SoundPatchError) as exc:
        return [str(exc)]
