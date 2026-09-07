#pragma once
struct lua_register_state {};
enum class lua_metatable {sound_archive,sound_fx};
// Public registration plumbing is outside this focused suite. The actual
// functions are invoked as real Lua C closures by the harness.
template <typename T> class lua_class_binding {
 public:
  template<typename... A> explicit lua_class_binding(A...) {}
  template<typename... A> void add_function(A...) {}
  template<typename... A> void add_metamethod(A...) {}
};
