// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <map>
#include <string>
#include <vector>
namespace runner {
using Fields = std::map<std::string, std::string>;
constexpr const char *SDROOT = "sdmc:/3ds/ftpd-runner";
constexpr const char *SELF = "sdmc:/3ds/ftpd-runner/runner.3dsx";
std::string sha256(const std::string &bytes);
std::string hashFile(const std::string &path);
std::string read(const std::string &path, size_t limit = 16384);
bool exists(const std::string &path);
void atomicWrite(const std::string &path, const std::string &bytes);
Fields parse(const std::string &bytes);
std::string encode(const Fields &f);
bool validId(const std::string &id);
bool validHash(const std::string &hash);
struct Job {
  std::string id, sha, configSha, inputSha, manifestSha;
  std::string dir(const std::string &root) const {
    return root + "/runs/" + id;
  }
  std::string target(const std::string &root) const {
    return dir(root) + "/program.3dsx";
  }
};
Job loadJob(const std::string &root, const std::string &marker,
            bool verify = true);
Fields validateResult(const Job &job, const std::string &bytes);
// Receipt only appears on a new launcher process after the target exited.
void recover(const std::string &root, const std::string &boot);
void reject(const std::string &root, const std::string &marker,
            const std::string &boot, const std::string &reason);
} // namespace runner
