// SPDX-License-Identifier: GPL-3.0-or-later
// Expose newlib's POSIX stream declarations under strict C++17 on the 3DS.
// Keep this feature selection before all system headers, local to this TU.
#if defined(__3DS__) && !defined(CTH3DS_STUB_BUILD) && !defined(_DEFAULT_SOURCE)
#define _DEFAULT_SOURCE 1
#endif
#include "core.hpp"
#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
namespace runner {
namespace {
struct SHA {
  uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                   0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  uint8_t b[64]{};
  uint64_t length = 0;
  size_t used = 0;
  static uint32_t r(uint32_t v, int n) { return (v >> n) | (v << (32 - n)); }
  void block() {
    static const uint32_t k[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
        0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
        0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
        0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
        0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
        0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
        0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
    uint32_t w[64];
    for (int i = 0; i < 16; i++)
      w[i] = (uint32_t(b[i * 4]) << 24) | (uint32_t(b[i * 4 + 1]) << 16) |
             (uint32_t(b[i * 4 + 2]) << 8) | b[i * 4 + 3];
    for (int i = 16; i < 64; i++) {
      auto x = w[i - 15], y = w[i - 2];
      w[i] = w[i - 16] + (r(x, 7) ^ r(x, 18) ^ (x >> 3)) + w[i - 7] +
             (r(y, 17) ^ r(y, 19) ^ (y >> 10));
    }
    auto a = h[0], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], v = h[7],
         bb = h[1];
    for (int i = 0; i < 64; i++) {
      auto t1 = v + (r(e, 6) ^ r(e, 11) ^ r(e, 25)) + ((e & f) ^ (~e & g)) +
                k[i] + w[i];
      auto t2 =
          (r(a, 2) ^ r(a, 13) ^ r(a, 22)) + ((a & bb) ^ (a & c) ^ (bb & c));
      v = g;
      g = f;
      f = e;
      e = d + t1;
      d = c;
      c = bb;
      bb = a;
      a = t1 + t2;
    }
    h[0] += a;
    h[1] += bb;
    h[2] += c;
    h[3] += d;
    h[4] += e;
    h[5] += f;
    h[6] += g;
    h[7] += v;
  }
  void add(const void *data, size_t n) {
    const auto *p = static_cast<const uint8_t *>(data);
    length += n;
    while (n) {
      size_t take = std::min(n, 64 - used);
      memcpy(b + used, p, take);
      p += take;
      n -= take;
      used += take;
      if (used == 64) {
        block();
        used = 0;
      }
    }
  }
  std::string finish() {
    uint64_t bits = length * 8;
    uint8_t one = 128, zero = 0;
    add(&one, 1);
    while (used != 56)
      add(&zero, 1);
    uint8_t tail[8];
    for (int i = 0; i < 8; i++)
      tail[i] = static_cast<uint8_t>((bits >> (56 - i * 8)) & 0xFFU);
    add(tail, 8);
    char out[65];
    for (int i = 0; i < 8; i++)
      snprintf(out + i * 8, 9, "%08lx", static_cast<unsigned long>(h[i]));
    return out;
  }
};
void require(bool value, const std::string &why) {
  if (!value)
    throw std::runtime_error(why);
}
std::string error(const std::string &path) {
  return path + ": " + strerror(errno);
}
void identity(const Job &j, const Fields &f) {
  for (auto [key, value] : Fields{{"version", "1"},
                                  {"run_id", j.id},
                                  {"artifact_sha256", j.sha},
                                  {"config_sha256", j.configSha},
                                  {"input_sha256", j.inputSha},
                                  {"manifest_sha256", j.manifestSha}}) {
    auto it = f.find(key);
    require(it != f.end() && it->second == value, "identity_mismatch_" + key);
  }
}
Fields base(const Job &j, const std::string &boot) {
  return {{"version", "1"},
          {"run_id", j.id},
          {"artifact_sha256", j.sha},
          {"config_sha256", j.configSha},
          {"input_sha256", j.inputSha},
          {"manifest_sha256", j.manifestSha},
          {"return_boot", boot}};
}
} // namespace
std::string sha256(const std::string &bytes) {
  SHA s;
  s.add(bytes.data(), bytes.size());
  return s.finish();
}
std::string hashFile(const std::string &path) {
  FILE *f = fopen(path.c_str(), "rb");
  if (!f)
    throw std::runtime_error(error(path));
  SHA s;
  // The default 3DS main stack is small. Hashing must leave room for the
  // protocol, stdio and exception frames, independent of the file size.
  std::array<char, 4096> b;
  size_t n;
  while ((n = fread(b.data(), 1, b.size(), f)))
    s.add(b.data(), n);
  bool bad = ferror(f);
  fclose(f);
  require(!bad, "read_failed");
  return s.finish();
}
bool exists(const std::string &path) {
  struct stat s;
  return stat(path.c_str(), &s) == 0;
}
std::string read(const std::string &path, size_t limit) {
  FILE *f = fopen(path.c_str(), "rb");
  if (!f)
    throw std::runtime_error(error(path));
  std::string s(limit + 1, '\0');
  size_t n = fread(s.data(), 1, s.size(), f);
  bool bad = ferror(f);
  fclose(f);
  require(!bad && n <= limit, "file_too_large_or_unreadable");
  s.resize(n);
  return s;
}
#ifdef CTH3DS_RUNNER_FAULT_TEST
const char* atomicWriteFaultStage=nullptr;
#endif
namespace {
bool writeFault(const char* stage){
#ifdef CTH3DS_RUNNER_FAULT_TEST
  if(atomicWriteFaultStage&&std::strcmp(stage,atomicWriteFaultStage)==0){errno=EIO;return true;}
#endif
  (void)stage;return false;
}
[[noreturn]] void writeError(const char* stage,const std::string& path,int code){
  throw std::runtime_error(std::string("durable_write stage=")+stage+" errno="+
    std::to_string(code)+" path="+path);
}
void requireAbsent(const std::string& path){
  struct stat info{};
  if(stat(path.c_str(),&info)==0)writeError("destination_exists",path,EEXIST);
  const int code=errno;
  if(code!=ENOENT)writeError("destination_stat",path,code);
}
void durableWrite(const std::string& path,const std::string& bytes,bool fresh){
  const auto tmp=path+".tmp";
  if(fresh)requireAbsent(path);
  const int fd=open(tmp.c_str(),O_WRONLY|O_CREAT|(fresh?O_EXCL:O_TRUNC),0666);
  if(fd<0){const int code=errno;writeError("open_temporary",tmp,code);}
  FILE* f=fdopen(fd,"wb");
  if(!f){const int code=errno;close(fd);writeError("fdopen",tmp,code);}
  const char* failed=nullptr;int code=0;
  if(writeFault("write")||fwrite(bytes.data(),1,bytes.size(),f)!=bytes.size()){
    code=errno;failed="write";
  }
  if(!failed&&(writeFault("flush")||fflush(f)!=0)){code=errno;failed="flush";}
  if(!failed&&(writeFault("fsync")||fsync(fd)!=0)){code=errno;failed="fsync";}
  const bool inject_close=writeFault("close");const int injected_errno=errno;
  const int closed=fclose(f);const int close_errno=errno;
  if(!failed&&(inject_close||closed!=0)){code=inject_close?injected_errno:close_errno;failed="close";}
  if(failed)writeError(failed,tmp,code);
  // The adapter is the sole writer in this run. Refuse existing final files
  // again immediately before publication; never delete them to make room.
  if(fresh)requireAbsent(path);
  if(writeFault("rename")||rename(tmp.c_str(),path.c_str())!=0){
    const int rename_errno=errno;writeError("rename",path,rename_errno);
  }
}
}
void atomicWrite(const std::string& path,const std::string& bytes){durableWrite(path,bytes,false);}
void atomicWriteNew(const std::string& path,const std::string& bytes){durableWrite(path,bytes,true);}
Fields parse(const std::string &s) {
  require(!s.empty() && s.size() <= 16384 && s.back() == '\n',
          "incomplete_fields");
  Fields out;
  size_t start = 0;
  while (start < s.size()) {
    size_t end = s.find('\n', start), eq = s.find('=', start);
    require(eq < end && eq > start, "invalid_field");
    auto key = s.substr(start, eq - start),
         value = s.substr(eq + 1, end - eq - 1);
    require(key.find_first_not_of("abcdefghijklmnopqrstuvwxyz_0123456789") ==
                std::string::npos,
            "invalid_key");
    require(value.find_first_of("\r\n\0", 0, 3) == std::string::npos,
            "invalid_value");
    require(out.emplace(key, value).second, "duplicate_field");
    start = end + 1;
  }
  return out;
}
std::string encode(const Fields &f) {
  std::string s;
  for (const auto &[k, v] : f)
    s += k + "=" + v + "\n";
  return s;
}
bool validId(const std::string &id) {
  return id.size() >= 8 && id.size() <= 64 &&
         id.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789-") ==
             std::string::npos;
}
bool validHash(const std::string &h) {
  return h.size() == 64 &&
         h.find_first_not_of("0123456789abcdef") == std::string::npos;
}
Job loadJob(const std::string &root, const std::string &marker, bool verify) {
  auto m = parse(marker);
  require(m.size() == 2 && validId(m["run_id"]) &&
              validHash(m["manifest_sha256"]),
          "invalid_marker");
  Job j;
  j.id = m.at("run_id");
  j.manifestSha = m.at("manifest_sha256");
  auto body = read(j.dir(root) + "/manifest.kv");
  require(sha256(body) == j.manifestSha, "manifest_hash_mismatch");
  auto f = parse(body);
  require(f.size() == 5 && f["version"] == "1" && f["run_id"] == j.id,
          "invalid_manifest");
  j.sha = f["artifact_sha256"];
  j.configSha = f["config_sha256"];
  j.inputSha = f["input_sha256"];
  require(validHash(j.sha) && validHash(j.configSha) && validHash(j.inputSha),
          "invalid_hash");
  if (verify) {
    require(hashFile(j.target(root)) == j.sha, "artifact_hash_mismatch");
    require(hashFile(j.dir(root) + "/config.bin") == j.configSha,
            "config_hash_mismatch");
    require(hashFile(j.dir(root) + "/input.bin") == j.inputSha,
            "input_hash_mismatch");
  }
  return j;
}
Fields validateResult(const Job &j, const std::string &bytes) {
  auto f = parse(bytes);
  identity(j, f);
  require(f["phase"] == "complete", "incomplete_result");
  require(f["outcome"] == "PASS" || f["outcome"] == "FAIL" ||
              f["outcome"] == "NOT_PROVEN",
          "invalid_outcome");
  for (const char *k : {"simulation_ticks", "frames", "elapsed_us"}) {
    auto v = f[k];
    require(!v.empty() && v.size() <= 18 &&
                v.find_first_not_of("0123456789") == std::string::npos,
            "invalid_metric");
  }
  require(!f["workload"].empty(), "missing_workload");
  return f;
}
void recover(const std::string &root, const std::string &boot) {
  if (!exists(root + "/active"))
    return;
  auto marker = read(root + "/active", 256);
  auto j = loadJob(root, marker, false);
  auto receipt = j.dir(root) + "/receipt.kv";
  if (!exists(receipt)) {
    auto f = base(j, boot);
    f["status"] = "INTERRUPTED";
    f["outcome"] = "NOT_PROVEN";
    f["reason"] = "no_complete_result";
    try {
      auto launch = parse(read(j.dir(root) + "/launch.kv"));
      identity(j, launch);
      require(launch.at("launch_boot") != boot, "same_process_return");
      f["launch_boot"] = launch.at("launch_boot");
      auto resultBytes = read(j.dir(root) + "/result.kv");
      auto result = validateResult(j, resultBytes);
      f["status"] = "COMPLETED";
      f["outcome"] = result.at("outcome");
      f["reason"] = "client_completed_and_launcher_reentered";
      f["result_sha256"] = sha256(resultBytes);
    } catch (const std::exception &e) {
      f["reason"] = e.what();
    }
    atomicWrite(receipt, encode(f));
  }
  require(remove((root + "/active").c_str()) == 0, "active_cleanup_failed");
}
void reject(const std::string &root, const std::string &marker,
            const std::string &boot, const std::string &reason) {
  // Invalid markers have no trustworthy run directory: keep active and block
  // for diagnosis.
  auto m = parse(marker);
  require(validId(m["run_id"]), "invalid_run_id");
  auto path = root + "/runs/" + m["run_id"] + "/receipt.kv";
  if (!exists(path))
    atomicWrite(path, encode({{"version", "1"},
                              {"run_id", m["run_id"]},
                              {"status", "REJECTED"},
                              {"outcome", "NOT_PROVEN"},
                              {"return_boot", boot},
                              {"reason", reason}}));
  require(remove((root + "/active").c_str()) == 0, "active_cleanup_failed");
}
} // namespace runner
