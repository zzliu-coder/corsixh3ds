#include "test_framework.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "cth3ds/resource_pack.hpp"

namespace {

std::filesystem::path temp_pack(const std::string& name) {
  const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
  return std::filesystem::temp_directory_path() /
         ("cth3ds-" + name + "-" + std::to_string(stamp) + ".thp");
}

std::vector<std::uint8_t> bytes(const std::string& value) {
  return {value.begin(), value.end()};
}

}  // namespace

TEST(resource_pack_round_trip_and_sorted_paths) {
  const auto path = temp_pack("roundtrip");
  std::string error;
  std::vector<cth3ds::PackInputFile> files{
      {"Data/Z.dat", bytes("zeta"), 0},
      {"Lua/app.lua", bytes("print('ok')"), 1},
      {"Data/A.dat", bytes("alpha"), 0},
  };
  EXPECT_TRUE(cth3ds::write_resource_pack(path, std::move(files), error));
  cth3ds::ResourcePack pack;
  EXPECT_TRUE(pack.open(path, error));
  EXPECT_EQ(pack.file_count(), std::size_t{3});
  const auto paths = pack.paths();
  EXPECT_EQ(paths.front(), std::string("Data/A.dat"));
  EXPECT_EQ(paths.back(), std::string("Lua/app.lua"));
  const auto data = pack.read("Data\\Z.dat", true, error);
  EXPECT_TRUE(data.has_value());
  EXPECT_EQ(std::string(data->begin(), data->end()), std::string("zeta"));
  pack.close();
  std::filesystem::remove(path);
}

TEST(resource_pack_detects_corrupted_payload) {
  const auto path = temp_pack("corrupt");
  std::string error;
  EXPECT_TRUE(cth3ds::write_resource_pack(
      path, {{"file.bin", bytes("payload"), 0}}, error));
  {
    std::fstream stream(path, std::ios::binary | std::ios::in | std::ios::out);
    stream.seekp(-1, std::ios::end);
    stream.put('X');
  }
  cth3ds::ResourcePack pack;
  EXPECT_TRUE(pack.open(path, error));
  EXPECT_FALSE(pack.read("file.bin", true, error).has_value());
  EXPECT_TRUE(error.find("checksum") != std::string::npos);
  pack.close();
  std::filesystem::remove(path);
}

TEST(resource_pack_rejects_duplicate_paths) {
  const auto path = temp_pack("duplicate");
  std::string error;
  EXPECT_FALSE(cth3ds::write_resource_pack(
      path,
      {{"a.bin", bytes("a"), 0}, {"a.bin", bytes("b"), 0}}, error));
  EXPECT_TRUE(error.find("duplicate") != std::string::npos);
  std::filesystem::remove(path);
}
