// hb:ldr IPC and argv wire layout adapted from devkitPro/3ds-hbmenu
// source/loaders/rosalina.c and source/launch.c (pinned in upstream-lock.json).
// Credit: smea, fincs, devkitPro contributors; see docs/upstream.md.
#include "rosalina.hpp"
#include "core.hpp"
#if defined(CTH3DS_STUB_BUILD)
#include <stdexcept>
namespace runner {
bool loaderAvailable(){return false;}
void nextLoad(const std::string&,const std::vector<std::string>&){throw std::runtime_error("native_loader_unavailable");}
std::string bootId(){throw std::runtime_error("native_loader_unavailable");}
}
#else
#include <3ds.h>
#include <array>
#include <cerrno>
#include <cstring>
#include <stdexcept>
#include <sys/stat.h>
namespace runner {
bool loaderAvailable() {
  if (!envIsHomebrew() || !(envGetSystemRunFlags() & RUNFLAG_APTCHAINLOAD) ||
      (envGetSystemRunFlags() & RUNFLAG_APTREINIT))
    return false;
  Handle h;
  auto rc = svcConnectToPort(&h, "hb:ldr");
  if (R_FAILED(rc))
    return false;
  svcCloseHandle(h);
  return true;
}
static Result send(Handle h, unsigned command, const void *bytes, unsigned size,
                   unsigned slot) {
  u32 *c = getThreadCommandBuffer();
  c[0] = IPC_MakeHeader(command, 0, 2);
  c[1] = IPC_Desc_StaticBuffer(size, slot);
  c[2] = (u32)bytes;
  auto rc = svcSendSyncRequest(h);
  return R_FAILED(rc) ? rc : c[1];
}
void nextLoad(const std::string &path, const std::vector<std::string> &args) {
  if (!loaderAvailable())
    throw std::runtime_error("Rosalina_APTCHAINLOAD_required");
  if (path.rfind("sdmc:/3ds/ftpd-runner/", 0) != 0 ||
      path.find("..") != std::string::npos)
    throw std::runtime_error("invalid_loader_path");
  alignas(4) std::array<char, 0x400> buf{};
  size_t pos = 4;
  uint32_t argc = 1 + args.size();
  memcpy(buf.data(), &argc, 4);
  auto add = [&](const std::string &s) {
    if (pos + s.size() + 1 > buf.size())
      throw std::runtime_error("argv_overflow");
    memcpy(buf.data() + pos, s.c_str(), s.size() + 1);
    pos += s.size() + 1;
  };
  add(path);
  for (const auto &s : args)
    add(s);
  Handle h;
  auto rc = svcConnectToPort(&h, "hb:ldr");
  if (R_FAILED(rc))
    throw std::runtime_error("hbldr_connect_failed");
  // Argv first: if target selection fails, no target has been changed.
  rc = send(h, 3, buf.data(), buf.size(), 1);
  if (R_SUCCEEDED(rc))
    rc = send(h, 2, path.c_str() + 5, path.size() - 4, 0);
  svcCloseHandle(h);
  if (R_FAILED(rc))
    throw std::runtime_error("hbldr_request_failed_" + std::to_string(rc));
  // libctru already configures APT chainload-to-self from RUNFLAG_APTCHAINLOAD.
  // The 3dsx path is passed only to hb:ldr, never aptSetChainloader.
}
std::string bootId() {
  const std::string directory = std::string(SDROOT) + "/boots";
  if (mkdir(directory.c_str(), 0777) != 0 && errno != EEXIST)
    throw std::runtime_error("boot_directory_failed");
  const auto seed =
      std::to_string(osGetTime()) + "-" + std::to_string(svcGetSystemTick());
  for (unsigned i = 0; i < 100; i++) {
    auto id = sha256(seed + "-" + std::to_string(i)).substr(0, 32);
    if (mkdir((directory + "/" + id).c_str(), 0777) == 0)
      return id;
    if (errno != EEXIST)
      throw std::runtime_error("boot_identity_persist_failed");
  }
  throw std::runtime_error("boot_identity_collision_limit");
}
} // namespace runner
#endif
