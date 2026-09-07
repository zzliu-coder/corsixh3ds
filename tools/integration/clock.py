"""Observe delivered upstream timer events without changing game speed."""

from __future__ import annotations

from pathlib import Path
from .common import (
    Change,
    IntegrationError,
    read_text,
    write_text,
)


SIMULATION_CLOCK_SITES = (
    ('        case SDL_USEREVENT_TICK:\n          do_timer = true;',
     '        case SDL_USEREVENT_TICK:\n#ifdef CORSIXTH_3DS\n'
     '          cth3ds::runtime_note_timer_event();\n#endif\n          do_timer = true;'),
    ('      u3_logic.finish(res == LUA_OK);\n#endif',
     '      u3_logic.finish(res == LUA_OK);\n'
     '      cth3ds::runtime_note_logic_callback(res == LUA_OK);\n#endif'),
)


def patch_simulation_clock(root: Path) -> list[Change]:
    # This upgrade also accepts a previously integrated R48 tree. Counter calls
    # stay on the main thread; the 18ms SDL timer never writes a log or Lua.
    path = root / "CorsixTH/Src/sdl_core.cpp"
    before = text = read_text(path)
    for old, new in SIMULATION_CLOCK_SITES:
        if text.count(new) == 1:
            continue
        if text.count(old) != 1:
            raise IntegrationError("simulation clock anchor mismatch")
        text = text.replace(old, new, 1)
    if text == before:
        return []
    write_text(path, text, False)
    return [Change("CorsixTH/Src/sdl_core.cpp", "simulation-clock")]
