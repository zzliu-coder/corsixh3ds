#!/usr/bin/env python3
"""Run a Lua chunk with the host's actual Lua5.4 shared library (no interpreter needed)."""
import ctypes
import os
import ctypes.util
import sys
from pathlib import Path


def execute(source: bytes) -> tuple[int, str]:
    name = os.environ.get('CTH3DS_LUA_LIBRARY') or ctypes.util.find_library('lua5.4')
    if not name: raise RuntimeError('liblua5.4 is required')
    lua = ctypes.CDLL(name)
    pointer = ctypes.c_void_p
    lua.luaL_newstate.restype = pointer
    lua.luaL_openlibs.argtypes = [pointer]
    lua.luaL_loadbufferx.argtypes = [pointer, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_char_p]
    lua.lua_pcallk.argtypes = [pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ssize_t, pointer]
    lua.lua_tolstring.argtypes = [pointer, ctypes.c_int, ctypes.POINTER(ctypes.c_size_t)]
    lua.lua_tolstring.restype = ctypes.c_char_p
    lua.lua_close.argtypes = [pointer]
    state = lua.luaL_newstate()
    if not state: raise MemoryError('luaL_newstate failed')
    try:
        lua.luaL_openlibs(state)
        status = lua.luaL_loadbufferx(state, source, len(source), b'load-recovery-test', b't')
        if status == 0: status = lua.lua_pcallk(state, 0, 0, 0, 0, None)
        error = lua.lua_tolstring(state, -1, None) if status else b''
        return status, (error or b'<non-string error>').decode('utf-8', 'replace')
    finally:
        lua.lua_close(state)

if __name__ == '__main__':
    status, message = execute(Path(sys.argv[1]).read_bytes())
    if status: print(message, file=sys.stderr)
    raise SystemExit(status)
