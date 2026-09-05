#include "test_framework.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>

#include "cth3ds/atomic_save.hpp"

namespace {

std::filesystem::path temporary_directory(const std::string& suffix) {
  const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
  const auto path = std::filesystem::temp_directory_path() /
                    ("cth3ds-test-" + suffix + "-" + std::to_string(stamp));
  std::filesystem::create_directories(path);
  return path;
}

std::string read_text(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

void write_text(const std::filesystem::path& path, const std::string& value) {
  std::ofstream output(path, std::ios::binary | std::ios::trunc);
  output << value;
}

}  // namespace

TEST(atomic_save_commits_and_rotates_backup) {
  const auto directory = temporary_directory("commit");
  const auto final_path = directory / "autosave.sav";
  write_text(final_path, "old");
  const auto result = cth3ds::atomic_write_file(
      final_path,
      [](const std::filesystem::path& path, std::string&) {
        write_text(path, "new");
        return true;
      });
  EXPECT_TRUE(result.ok);
  EXPECT_EQ(read_text(final_path), std::string("new"));
  EXPECT_EQ(read_text(final_path.string() + ".bak"), std::string("old"));
  std::filesystem::remove_all(directory);
}

TEST(atomic_save_writer_failure_preserves_old_save) {
  const auto directory = temporary_directory("failure");
  const auto final_path = directory / "autosave.sav";
  write_text(final_path, "old");
  const auto result = cth3ds::atomic_write_file(
      final_path,
      [](const std::filesystem::path&, std::string& error) {
        error = "intentional";
        return false;
      });
  EXPECT_FALSE(result.ok);
  EXPECT_EQ(read_text(final_path), std::string("old"));
  EXPECT_FALSE(std::filesystem::exists(final_path.string() + ".tmp"));
  std::filesystem::remove_all(directory);
}

TEST(atomic_save_recovery_promotes_temporary_file) {
  const auto directory = temporary_directory("recover");
  const auto final_path = directory / "autosave.sav";
  write_text(final_path.string() + ".tmp", "recovered");
  const auto result = cth3ds::recover_atomic_file(final_path);
  EXPECT_FALSE(result.ok);
  EXPECT_FALSE(std::filesystem::exists(final_path));
  EXPECT_EQ(read_text(final_path.string()+".tmp"),std::string("recovered"));
  std::filesystem::remove_all(directory);
}

TEST(atomic_save_validated_backup_wins_over_orphan_tmp) {
  const auto directory=temporary_directory("validated");const auto file=directory/"progress.sav";
  write_text(file,"corrupt");write_text(file.string()+".bak","good");write_text(file.string()+".tmp","truncated");
  const auto result=cth3ds::recover_atomic_file(file,[](const auto& candidate,std::string& error){
    if(read_text(candidate)=="good")return true;error="corrupt";return false;
  });
  EXPECT_TRUE(result.ok);EXPECT_EQ(read_text(file),std::string("good"));
  EXPECT_EQ(read_text(file.string()+".bak"),std::string("good"));
  std::filesystem::remove_all(directory);
}
