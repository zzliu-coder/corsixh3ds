"""Bound elapsed-time catch-up while retaining the upstream speed/tick rules."""

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
    ('    if (do_timer) {\n#ifdef CORSIXTH_3DS\n',
     '    // CORSIXTH_3DS_SIMULATION_BUDGET_R51\n'
     '#ifdef CORSIXTH_3DS\n'
     '    (void)do_timer; // wakeups are observations, elapsed time owns simulation\n'
     '    cth3ds::runtime_simulation_begin();\n'
     '    while (cth3ds::runtime_simulation_step())\n'
     '#else\n    if (do_timer)\n#endif\n    {\n#ifdef CORSIXTH_3DS\n'),
)

PRESENTATION_SITES = (
    ('  while ((wait_error = SDL_WaitEvent(&e)) != 0) {',
     '  // R52: poll input on a bounded wake even if no engine event arrived.\n'
     '#ifdef CORSIXTH_3DS\n'
     '  auto u3_wait = [&]() {\n'
     '    if (SDL_WaitEventTimeout(&e, 8) == 0) e.type = SDL_FIRSTEVENT;\n'
     '    return 1;\n  };\n'
     '  while ((wait_error = u3_wait()) != 0) {\n'
     '#else\n  while ((wait_error = SDL_WaitEvent(&e)) != 0) {\n#endif'),
    ('    if (do_frame || !fps.limit_fps) {',
     '#ifdef CORSIXTH_3DS\n'
     '    do_frame = cth3ds::runtime_frame_due(do_frame || !fps.limit_fps);\n'
     '#endif\n    if (do_frame\n#ifndef CORSIXTH_3DS\n        || !fps.limit_fps\n#endif\n    ) {'),
    ('      } while (fps.limit_fps == false && SDL_PollEvent(nullptr) == 0);',
     '#ifdef CORSIXTH_3DS\n      } while (false); // input and logic own the next turn\n'
     '#else\n      } while (fps.limit_fps == false && SDL_PollEvent(nullptr) == 0);\n#endif'),
)


def patch_simulation_clock(root: Path) -> list[Change]:
    # This upgrade also accepts a previously integrated R48 tree. Counter calls
    # stay on the main thread; the 18ms SDL timer never writes a log or Lua.
    path = root / "CorsixTH/Src/sdl_core.cpp"
    before = text = read_text(path)
    # Normalize only our own observation line so existing clock anchors and
    # their repeat-generation checks keep a single canonical owner.
    wait_phase = '    cth3ds::RuntimePhaseScope wait_phase(cth3ds::FramePhase::Wait); // R69 residency\n'
    if text.count(wait_phase) > 1:
        raise IntegrationError('duplicate frame tail wait phase')
    text = text.replace(wait_phase, '')
    for old, new in SIMULATION_CLOCK_SITES + PRESENTATION_SITES:
        if text.count(new) == 1:
            continue
        if text.count(old) != 1:
            raise IntegrationError("simulation clock anchor mismatch")
        text = text.replace(old, new, 1)
    anchor = '  auto u3_wait = [&]() {\n'
    if text.count(anchor) != 1:
        raise IntegrationError('frame tail wait anchor mismatch')
    text = text.replace(anchor, anchor + wait_phase, 1)
    if text == before:
        return []
    write_text(path, text, False)
    return [Change("CorsixTH/Src/sdl_core.cpp", "simulation-clock")]
