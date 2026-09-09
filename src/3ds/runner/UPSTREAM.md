Runner protocol source: old3ds-runner cab2721, device/core.cpp, core.hpp,
rosalina.cpp and rosalina.hpp. core.cpp adds a 3DS-only _DEFAULT_SOURCE feature
selection before system headers so strict C++17/newlib declares POSIX stream APIs; its
fflush/fsync/close/rename persistence sequence is retained. Durable writes now
capture the failed operation's errno immediately and name its stage, before
cleanup can alter errno. The added atomicWriteNew entry uses exclusive temporary
creation and refuses existing final names for single-writer immutable snapshots;
failed temporary files remain. Compile-time host-only fault injection exercises
write/flush/fsync/close/rename errors. rosalina.cpp adds
an explicit disabled loader for host stub builds. GPL-3.0-or-later; LICENSE
is retained here. This reuse does not change the existing project LICENSE.

Rosalina IPC/argv layout derives from devkitPro/3ds-hbmenu revision
5a0110a6e8f790c1b6a621e91ed6c733ebfcefd7, source/loaders/rosalina.c and
source/launch.c. Credit: smea, fincs and devkitPro contributors.
HBMENU-NOTICE.md retains that upstream notice.

adapter.cpp is the narrow CorsixTH integration: it reuses the runner job,
hash, durable-result and normal chainload-return protocol. It does not
implement FTP, a new loader, input replay, or a general scenario SDK.

Installed Lua files are hashed each run; large assets retain the supplied
installation receipt identity and are explicitly not fully reverified.
The host supplies a small installed integration receipt path and hash.
Host preparation is tools/prepare_runner_benchmark.py; its output receipt
contains an argv list for the existing runner host CLI. Each invocation of
runner run allocates a fresh run ID and automatically waits for return.
Do not delete benchmark-used-r63.txt or reuse an already started run ID.
