"""Bound the serializer's largest temporary index allocation; format unchanged."""
from sound_lifetime import replace_exact

BUCKET=r'''
  // R59: strong keys are retained exactly as before, split over 256 tables.
  // A large hospital no longer requires a single doubled hash allocation
  // while its previous index allocation is still live. Bucket order is never
  // serialized; the original visitation order and object IDs are unchanged.
  void push_cache_for(int index) {
    std::uint32_t hash=2166136261U;
    if(lua_type(L,index)==LUA_TSTRING) {
      size_t length=0;const auto* s=lua_tolstring(L,index,&length);
      for(size_t i=0;i<length;++i)hash=(hash^static_cast<unsigned char>(s[i]))*16777619U;
    } else {
      auto pointer=reinterpret_cast<std::uintptr_t>(lua_topointer(L,index));
      pointer^=pointer>>16U;pointer^=pointer>>8U;hash=static_cast<std::uint32_t>(pointer>>3U);
    }
    const int slot=2+static_cast<int>(hash&255U);
    lua_getfenv(L,1);
    lua_rawgeti(L,-1,slot);
    if(lua_isnil(L,-1)) {
      lua_pop(L,1);lua_createtable(L,1,8);
      lua_pushvalue(L,2);lua_rawseti(L,-2,1);
      lua_pushvalue(L,-1);lua_rawseti(L,-3,slot);
    }
    lua_remove(L,-2);
  }
'''

FILE_METHODS = r'''
#if LUA_VERSION_NUM >= 502
  // CORSIXTH_3DS_SAVE_STREAM_R65: the caller owns this standard Lua file.
  // Its userdata is rooted on the outer dump_file stack until we return.
  lua_persist_basic_writer(lua_State* state, luaL_Stream* stream, uint8_t* scratch, size_t capacity)
      : L(state), output(stream), buffer(scratch), buffer_capacity(capacity),
        file_clock(cth3ds::cpu_work.clock_us), file_started(file_tick()) {}

  // CORSIXTH_3DS_SAVE_IO_R74: two clock reads per FILE call, never per graph object.
  // This is the runtime's existing monotonic clock, independent of whether
  // detailed entity profiling is enabled. Missing/backwards clocks stay unknown.
  uint64_t file_tick() const { return file_clock ? file_clock() : 0; }
  uint64_t file_elapsed(uint64_t start) {
    const auto end = file_tick();
    if (!file_clock || end < start) { file_timing_valid = false; return 0; }
    return end - start;
  }

  bool flush_buffer() {
    if (had_error) return false;
    if (!output->closef || !output->f) {
      set_error("save stream: closed file");
      return false;
    }
    if (!buffered) return true;
    errno = 0;
    ++flushes;
    const auto started = file_tick();
    const size_t count = std::fwrite(buffer, 1, buffered, output->f);
    const int saved_errno = errno;
    const auto elapsed = file_elapsed(started);
    file_write_us += elapsed;
    if (elapsed > file_write_max_us) file_write_max_us = elapsed;
    written += count;
    if (count != buffered || std::ferror(output->f)) {
      char message[96];
      std::snprintf(message, sizeof(message), "save stream write failed (errno=%d)", saved_errno);
      set_error(message);
      return false;
    }
    buffered = 0;
    return true;
  }

  int finish_file() {
    if (flush_buffer()) {
      errno = 0;
      const auto started = file_tick();
      const int status = std::fflush(output->f);
      const int saved_errno = errno;
      file_flush_us = file_elapsed(started);
      if (status != 0 || std::ferror(output->f)) {
        char message[96];
        std::snprintf(message, sizeof(message), "save stream flush failed (errno=%d)", saved_errno);
        set_error(message);
      }
    }
    if (had_error) return finish();
    lua_pushboolean(L, 1);
    lua_pushinteger(L, static_cast<lua_Integer>(written));
    lua_pushinteger(L, static_cast<lua_Integer>(flushes));
    const uint64_t total = file_elapsed(file_started);
    for (const auto value : {total, file_write_us, file_write_max_us, file_flush_us}) {
      if (file_timing_valid) lua_pushinteger(L, static_cast<lua_Integer>(value));
      else lua_pushnil(L);
    }
    return 7; // first three values and all serialized bytes remain unchanged
  }
#endif
'''

FILE_WRITE = r'''
#if LUA_VERSION_NUM >= 502
    if (output) {
      const uint64_t maximum = static_cast<uint64_t>((~lua_Unsigned{0}) >> 1);
      if (iCount > maximum - written - buffered) {
        set_error("save stream: output size overflow");
        return;
      }
      while (iCount && !had_error) {
        const size_t available = buffer_capacity - buffered;
        const size_t count = iCount < available ? iCount : available;
        std::memcpy(buffer + buffered, pBytes, count);
        buffered += count;
        pBytes += count;
        iCount -= count;
        if (buffered == buffer_capacity && !flush_buffer()) return;
      }
      return;
    }
#endif
'''

FILE_ENTRY = r'''
#if LUA_VERSION_NUM >= 502
int l_dump_file_toplevel(lua_State* L) {
  luaL_checktype(L, 2, LUA_TTABLE);
  auto* stream = static_cast<luaL_Stream*>(luaL_checkudata(L, 3, LUA_FILEHANDLE));
  luaL_argcheck(L, stream->closef && stream->f, 3, "open file required");
  // CORSIXTH_3DS_SAVE_BUFFER_R75: explicit per-call experiment; no global state.
  // Preserve the shipping default until hardware A/B demonstrates a benefit.
  luaL_argcheck(L, lua_isnoneornil(L, 4) || lua_type(L, 4) == LUA_TNUMBER, 4, "numeric buffer size required");
  const lua_Integer requested = lua_isnoneornil(L, 4) ? 16384 : luaL_checkinteger(L, 4);
  luaL_argcheck(L, requested == 16384 || requested == 65536, 4, "16384 or 65536 required");
  const auto capacity = static_cast<size_t>(requested);
  lua_settop(L, 3);
  lua_pushvalue(L, 1);
  void* storage = lua_newuserdata(L, sizeof(lua_persist_basic_writer) + capacity);
  auto* scratch = static_cast<uint8_t*>(storage) + sizeof(lua_persist_basic_writer);
  auto* writer = new (storage) lua_persist_basic_writer(L, stream, scratch, capacity);
  lua_replace(L, 1); // writer, permanents, strong file owner, root object
  const char* failure = nullptr;
  try {
    writer->init();
    writer->write_stack_object(4);
    return writer->finish();
  } catch (const std::bad_alloc&) {
    failure = "save stream: native allocation failed";
  } catch (...) {
    failure = "save stream: native serialization exception";
  }
  // No C++ exception is active when Lua may longjmp. GC only destroys the
  // writer; neither its destructor nor this entry closes or flushes the file.
  // A throwing native __persist may leave inner Lua call frames active: raise
  // to the caller's pcall so Lua restores them instead of returning normally.
  writer->set_error(failure);
  return luaL_error(L, "%s", writer->get_error());
}
#endif
'''


def stream_writer(text):
    if 'CORSIXTH_3DS_SAVE_STREAM_R65' in text:
        if 'CORSIXTH_3DS_SAVE_BUFFER_R75' not in text:
            raise ValueError('save writer view predates R75; regenerate from pinned source')
        return text
    begin = text.index('class lua_persist_basic_writer :')
    end = text.index('class lua_persist_basic_reader', begin)
    writer = text[begin:end]
    writer = replace_exact(writer, '  int finish() {', FILE_METHODS+'\n  int finish() {', 'file writer methods')
    writer = replace_exact(writer, '    } else {\n      lua_pushlstring(L, data.c_str(), data.length());',
        '    } else {\n#if LUA_VERSION_NUM >= 502\n      if (output) return finish_file();\n#endif\n'
        '      lua_pushlstring(L, data.c_str(), data.length());', 'file finish avoids output string')
    writer = replace_exact(writer, '    data.append(reinterpret_cast<const char*>(pBytes), iCount);',
        FILE_WRITE+'\n    data.append(reinterpret_cast<const char*>(pBytes), iCount);', 'bounded file sink')
    writer = replace_exact(writer, '    // Use the written data buffer to store the error message',
        '''#if LUA_VERSION_NUM >= 502
    if (output) {
      // Keep the first diagnostic bounded, including allocation failures.
      std::strncpy(file_error, sError, sizeof(file_error) - 1);
      file_error[sizeof(file_error) - 1] = '\\0';
      return;
    }
#endif
    // Use the written data buffer to store the error message''', 'file error does not allocate')
    writer = replace_exact(writer, '    if (had_error)\n      return data.c_str();',
        '''#if LUA_VERSION_NUM >= 502
    if (had_error && output) return file_error;
#endif
    if (had_error)
      return data.c_str();''', 'file first error')
    writer = replace_exact(writer, '  bool had_error{false};', '''  bool had_error{false};
#if LUA_VERSION_NUM >= 502
  luaL_Stream* output{nullptr};
  uint8_t* buffer{nullptr}; // trailing userdata bytes, never stack or new[]
  size_t buffer_capacity{16384};
  size_t buffered{0};
  uint64_t written{0};
  uint64_t flushes{0};
  uint64_t (*file_clock)() noexcept{nullptr};
  uint64_t file_started{0}, file_write_us{0}, file_write_max_us{0}, file_flush_us{0};
  bool file_timing_valid{true};
  char file_error[256]{};
#endif''', 'bounded file writer fields')
    writer = writer.replace('luaL_error(L, get_error());', 'luaL_error(L, "%s", get_error());')
    text = text[:begin] + writer + text[end:]
    text = replace_exact(text, 'int l_load_toplevel(lua_State* L) {',
        FILE_ENTRY+'\nint l_load_toplevel(lua_State* L) {', 'file dump entry')
    text = replace_exact(text, '  lua_setfield(L, -6, "dump");', '''  lua_setfield(L, -6, "dump");
#if LUA_VERSION_NUM >= 502
  lua_pushvalue(L, -3);
  luaT_pushcclosure(L, l_dump_file_toplevel, 1);
  lua_setfield(L, -6, "dump_file");
#endif''', 'file dump registration with same prototype names')
    if '#include "cth3ds/cpu_work.hpp"' not in text:
        text = replace_exact(text, '#include <cstring>',
            '#include <cstring>\n#include "cth3ds/cpu_work.hpp"', 'shared save monotonic clock')
    return text

def transforms(root):
    path='CorsixTH/Src/persist_lua.cpp'
    text=(root/path).read_text()
    if BUCKET not in text:
        begin=text.index('class lua_persist_basic_writer :')
        end=text.index('class lua_persist_basic_reader',begin)
        writer=text[begin:end]
        writer=replace_exact(writer,'  void fast_write_stack_object(int iIndex) override {',
                             BUCKET+'\n  void fast_write_stack_object(int iIndex) override {','segmented save index')
        # Only the two seen-object lookup sites, not userdata environments.
        writer=replace_exact(writer,'    // Check for no cycle\n    lua_getfenv(L, 1);',
                             '    // Check for no cycle\n    push_cache_for(iIndex);','fast writer index')
        writer=replace_exact(writer,'      lua_getfenv(L, 1);\n      lua_pushvalue(L, iIndex);',
                             '      push_cache_for(iIndex);\n      lua_pushvalue(L, iIndex);','general writer index')
        writer=replace_exact(writer,'    lua_checkstack(L, top + 5);',
                             '    luaL_checkstack(L, 12, "save graph too deep");','checked writer stack')
        writer=replace_exact(writer,'        lua_checkstack(L, 20);',
                             '        luaL_checkstack(L, 20, "save userdata stack exhausted");','checked fast writer stack')
        text=text[:begin]+writer+text[end:]
        text=replace_exact(text,'#include <cstring>','#include <cstring>\n#include <cstdint>','index integer types')
    yield path,stream_writer(text)
    path='CorsixTH/Src/persist_lua.h'
    text=(root/path).read_text()
    if 'CORSIXTH_3DS_VARINT_STACK_R63' not in text:
        text=replace_exact(text, '      std::vector<uint8_t> bytes(iNumBytes);',
            '''      // CORSIXTH_3DS_VARINT_STACK_R63: base-128 uses at most ten
      // bytes for uint64_t. Avoid a heap allocation for every object reference.
      uint8_t bytes[(sizeof(T) * 8U + 6U) / 7U]{};''', 'bounded integer encoding scratch')
        text=replace_exact(text, '      write_byte_stream(bytes.data(), iNumBytes);',
            '      write_byte_stream(bytes, iNumBytes);', 'unchanged varint output')
    yield path,text
