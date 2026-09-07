#include "test_framework.hpp"
#include "cth3ds/bounded_log.hpp"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>

namespace {
struct LogFixture {
  std::filesystem::path dir = std::filesystem::temp_directory_path() /
    ("cth3ds-bounded-log-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
  std::string current=(dir/"boot.log").string(), previous=(dir/"boot.previous.log").string(),
    oldest=(dir/"boot.older.log").string();
  cth3ds::BoundedLog log;
  LogFixture() { std::filesystem::create_directory(dir); }
  ~LogFixture() { log.close(); std::filesystem::remove_all(dir); }
  bool open() { return log.open(current.c_str(),previous.c_str(),oldest.c_str()); }
  static std::string read(const std::string& p) {
    std::ifstream f(p,std::ios::binary);
    return {std::istreambuf_iterator<char>(f),std::istreambuf_iterator<char>()};
  }
};
}
TEST(bounded_log_retains_exact_three_runs) {
  LogFixture f;
  for (const char value : std::string("1234")) {
    EXPECT_TRUE(f.open()); f.log.write(&value,1); f.log.close();
  }
  EXPECT_EQ(LogFixture::read(f.current),std::string("4"));
  EXPECT_EQ(LogFixture::read(f.previous),std::string("3"));
  EXPECT_EQ(LogFixture::read(f.oldest),std::string("2"));
}
TEST(bounded_log_caps_normal_writes_and_reserves_fatal_evidence) {
  LogFixture f; EXPECT_TRUE(f.open());
  const std::string block(1024,'x');
  for (int i=0;i<2000;++i) f.log.write(block.data(),block.size());
  EXPECT_TRUE(f.log.truncated());
  EXPECT_TRUE(f.log.bytes() <= cth3ds::BoundedLog::kLimit-cth3ds::BoundedLog::kReserve+128);
  f.log.emergency(); f.log.write("FATAL preserved\n",16);
  for (int i=0;i<2000;++i) f.log.write(block.data(),block.size());
  f.log.close(); const auto text=LogFixture::read(f.current);
  EXPECT_TRUE(text.size() <= cth3ds::BoundedLog::kLimit);
  EXPECT_TRUE(text.find("FATAL preserved") != std::string::npos);
  const auto marker=text.find("log-truncated:");
  EXPECT_TRUE(marker != std::string::npos);
  EXPECT_EQ(text.find("log-truncated:",marker+1),std::string::npos);
}
TEST(bounded_log_rotation_failure_keeps_current_and_disables_writer) {
  LogFixture f; EXPECT_TRUE(f.open()); f.log.write("keep",4); f.log.close();
  std::filesystem::create_directory(f.oldest);
  std::ofstream(f.oldest+"/protected") << "keep";
  EXPECT_FALSE(f.open()); EXPECT_FALSE(f.log.available());
  f.log.write("wrong",5);
  EXPECT_EQ(LogFixture::read(f.current),std::string("keep"));
}
