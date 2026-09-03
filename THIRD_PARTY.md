# Third-party components

This repository contains a porting overlay and does not redistribute the
CorsixTH source tree or proprietary Theme Hospital data.

The build scripts obtain pinned revisions of:

- CorsixTH — MIT License.
- SDL 2 — zlib License.
- SDL_mixer 2 — zlib License, with codec-specific notices in its source tree.
- Lua 5.4 — MIT License.
- LuaFileSystem — MIT License.
- LPeg — MIT License.
- devkitPro / libctru and Nintendo 3DS port libraries — their upstream licenses.

The original Theme Hospital graphics, sounds, levels and other game data remain
copyrighted assets. Users must supply their own lawful copy. `tools/th3ds_pack.py`
validates and stages those files without adding them to this repository.
