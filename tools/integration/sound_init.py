"""Sound initialization transaction and legacy migration."""

from __future__ import annotations

from pathlib import Path
from sound_lifetime import (sound_transaction, patch_sound_lifetime,
                            check_sound_lifetime, SoundPatchError)
from .common import (
    Change,
    IntegrationError,
    read_text,
    write_text,
)


SOUND_INIT_MARKER = "CORSIXTH_3DS_SOUND_INIT_TRANSACTION_V1"


SOUND_INIT_LEGACY = r'''
void sound_player::populate_from(sound_archive* pArchive) {
#ifdef CORSIXTH_3DS
  Mix_HaltChannel(-1); // synchronous: no callback can access the freed bank
  for(int c=0;c<number_of_channels;++c) {finished[c].store(false);release_channel(c);}
  sound_observe("sound_release","bank-before","bank",0,owner_bytes());
  archive=pArchive;cache_bytes=0;used_at.clear();used_at.shrink_to_fit();allocated_bytes.clear();allocated_bytes.shrink_to_fit();
#endif
  for (size_t i = 0; i < sound_count; ++i) {
    Mix_FreeChunk(sounds[i]);
  }
  delete[] sounds;
  sounds = nullptr;
  sound_count = 0;

#ifdef CORSIXTH_3DS
  sound_observe("sound_release","bank-after","bank",0,owner_bytes());
#endif
  if (pArchive == nullptr) return;

#ifdef CORSIXTH_3DS
  sound_count=pArchive->get_number_of_sounds();
  sounds=new Mix_Chunk*[sound_count]();used_at.resize(sound_count);allocated_bytes.resize(sound_count);
  sound_observe("sound_index","player-metadata","bank",0,owner_bytes());
  return;
#endif
  sounds = new Mix_Chunk*[pArchive->get_number_of_sounds()];
  for (; sound_count < pArchive->get_number_of_sounds(); ++sound_count) {
    sounds[sound_count] = nullptr;
    if (SDL_RWops* pRwop = pArchive->load_sound(sound_count)) {
      sounds[sound_count] = Mix_LoadWAV_RW(pRwop, 1);
      if (sounds[sound_count]) {
        Mix_VolumeChunk(sounds[sound_count], MIX_MAX_VOLUME);
      }
    }
  }
}
'''.strip()


SOUND_INIT_R41_TRANSACTION = r'''
void sound_player::populate_from(sound_archive* pArchive) {
#ifdef CORSIXTH_3DS
  // CORSIXTH_3DS_SOUND_INIT_TRANSACTION_V1
  // The caller retains the borrowed archive until a successful replacement or
  // release. Prepare all throwing work before touching the current bank/pins.
  const size_t next_count = pArchive ? pArchive->get_number_of_sounds() : 0;
  std::unique_ptr<Mix_Chunk*[]> next_sounds;
  std::vector<uint64_t> next_used_at;
  std::vector<size_t> next_allocated_bytes;
  if (next_count != 0) {
    const size_t metadata = next_count *
        (sizeof(Mix_Chunk*) + sizeof(uint64_t) + sizeof(size_t));
    if (!cth3ds::runtime_audio_reserve(metadata, "sound-player-metadata"))
      throw std::bad_alloc();
    next_sounds.reset(new Mix_Chunk*[next_count]());
    next_used_at.resize(next_count);
    next_allocated_bytes.resize(next_count);
  }

  // No allocating operations below this point. Halt synchronizes callbacks;
  // release pins while their old metadata and archive are still alive.
  Mix_HaltChannel(-1);
  for (int c = 0; c < number_of_channels; ++c) {
    finished[c].store(false, std::memory_order_release);
    release_channel(c);
  }
  sound_observe("sound_release", "bank-before", "bank", 0, owner_bytes());
  for (size_t i = 0; i < sound_count; ++i) Mix_FreeChunk(sounds[i]);
  delete[] sounds;

  sounds = next_sounds.release();
  used_at.swap(next_used_at);
  allocated_bytes.swap(next_allocated_bytes);
  sound_count = next_count;
  archive = pArchive;
  cache_bytes = 0;
  cache_clock = 0;
  sound_observe("sound_release", "bank-after", "bank", 0, owner_bytes());
  if (pArchive)
    sound_observe("sound_index", "player-metadata", "bank", 0, owner_bytes());
#else
  for (size_t i = 0; i < sound_count; ++i) {
    Mix_FreeChunk(sounds[i]);
  }
  delete[] sounds;
  sounds = nullptr;
  sound_count = 0;

  if (pArchive == nullptr) return;

  sounds = new Mix_Chunk*[pArchive->get_number_of_sounds()];
  for (; sound_count < pArchive->get_number_of_sounds(); ++sound_count) {
    sounds[sound_count] = nullptr;
    if (SDL_RWops* pRwop = pArchive->load_sound(sound_count)) {
      sounds[sound_count] = Mix_LoadWAV_RW(pRwop, 1);
      if (sounds[sound_count]) {
        Mix_VolumeChunk(sounds[sound_count], MIX_MAX_VOLUME);
      }
    }
  }
#endif
}
'''.strip()


SOUND_INIT_TRANSACTION = sound_transaction(SOUND_INIT_R41_TRANSACTION)


def patch_sound_initialization(root: Path, dry_run: bool = False) -> list[Change]:
    """Upgrade pristine U1, R41, and already-repaired generated sound consumers."""
    path = root / "CorsixTH/Src/th_sound.cpp"
    text = read_text(path)
    if text.count(SOUND_INIT_TRANSACTION) == 1:
        return []
    variants = [old for old in (SOUND_INIT_LEGACY, SOUND_INIT_R41_TRANSACTION)
                if text.count(old) == 1]
    if len(variants) != 1:
        raise IntegrationError("sound initialization source mismatch: CorsixTH/Src/th_sound.cpp")
    write_text(path, text.replace(variants[0], SOUND_INIT_TRANSACTION, 1), dry_run)
    return [Change("CorsixTH/Src/th_sound.cpp", "sound-init-transaction")]
