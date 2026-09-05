#pragma once

#include <filesystem>
#include <functional>
#include <string>

namespace cth3ds {

struct AtomicSaveResult {
  bool ok{false};
  std::string error{};
};

using AtomicValidator = std::function<bool(const std::filesystem::path&, std::string&)>;

using AtomicWriter = std::function<bool(const std::filesystem::path&, std::string&)>;

[[nodiscard]] AtomicSaveResult atomic_write_file(
    const std::filesystem::path& final_path,
    const AtomicWriter& writer,
    bool keep_backup = true);

[[nodiscard]] AtomicSaveResult atomic_commit_existing(
    const std::filesystem::path& temporary_path,
    const std::filesystem::path& final_path,
    bool keep_backup = true);

[[nodiscard]] AtomicSaveResult recover_atomic_file(
    const std::filesystem::path& final_path,
    const AtomicValidator& validate = {});

}  // namespace cth3ds
