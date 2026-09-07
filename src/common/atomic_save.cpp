#include "cth3ds/atomic_save.hpp"

#include <cerrno>
#include <cstdio>
#include <fstream>
#include <system_error>

#if defined(_WIN32)
#include <io.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

namespace cth3ds {
namespace {

std::filesystem::path temp_path_for(const std::filesystem::path& final_path) {
  return final_path.string() + ".tmp";
}

std::filesystem::path backup_path_for(const std::filesystem::path& final_path) {
  return final_path.string() + ".bak";
}

bool sync_file(const std::filesystem::path& path, std::string& error) {
#if defined(_WIN32)
  FILE* file = nullptr;
  if (fopen_s(&file, path.string().c_str(), "rb") != 0 || file == nullptr) {
    error = "cannot open temporary file for sync";
    return false;
  }
  const int result = _commit(_fileno(file));
  std::fclose(file);
  if (result != 0) {
    error = "failed to flush temporary file";
    return false;
  }
  return true;
#else
  const int fd = ::open(path.c_str(), O_RDONLY);
  if (fd < 0) {
    error = "cannot open temporary file for sync: " +
            std::error_code(errno, std::generic_category()).message();
    return false;
  }
  const int result = ::fsync(fd);
  const int saved_errno = errno;
  const int close_result=::close(fd);
  if (close_result != 0 && result == 0) {error="sync close failed";return false;}
  if (result != 0) {
    error = "failed to flush temporary file: " +
            std::error_code(saved_errno, std::generic_category()).message();
    return false;
  }
  return true;
#endif
}

bool sync_directory(const std::filesystem::path& directory, std::string& error) {
#if defined(_WIN32)
  (void)directory;
  (void)error;
  return true;
#elif defined(__3DS__)
  // newlib on 3DS does not expose O_DIRECTORY consistently. The temporary
  // file itself is fsync'ed before rename; closing and renaming through the
  // SDMC device is the strongest portable guarantee available here.
  (void)directory;
  (void)error;
  return true;
#else
  const int fd = ::open(directory.c_str(), O_RDONLY | O_DIRECTORY);
  if (fd < 0) {
    error = "cannot open save directory for sync: " +
            std::error_code(errno, std::generic_category()).message();
    return false;
  }
  const int result = ::fsync(fd);
  const int saved_errno = errno;
  const int close_result=::close(fd);
  if (close_result != 0 && result == 0) {error="sync close failed";return false;}
  if (result != 0) {
    error = "failed to flush save directory: " +
            std::error_code(saved_errno, std::generic_category()).message();
    return false;
  }
  return true;
#endif
}

}  // namespace

AtomicSaveResult atomic_commit_existing(const std::filesystem::path& temporary_path,
                                        const std::filesystem::path& final_path,
                                        bool keep_backup) {
  AtomicSaveResult result;
  std::error_code ec;
  if (!std::filesystem::exists(temporary_path, ec) || ec) {
    result.error = "temporary save file does not exist";
    return result;
  }
  if (!final_path.parent_path().empty()) {
    std::filesystem::create_directories(final_path.parent_path(), ec);
    if (ec) {
      result.error = "cannot create save directory: " + ec.message();
      return result;
    }
  }

  if (!sync_file(temporary_path, result.error)) {
    return result;
  }

  const std::filesystem::path backup = backup_path_for(final_path);
  const bool final_exists=std::filesystem::exists(final_path,ec);
  if(ec){result.error="cannot inspect final save: "+ec.message();return result;}
  if (keep_backup && final_exists) {
    std::filesystem::remove(backup, ec);
    if(ec){result.error="cannot remove old backup: "+ec.message();return result;}
    std::filesystem::rename(final_path, backup, ec);
    if (ec) {
      result.error = "cannot rotate previous save: " + ec.message();
      return result;
    }
  } else if (!keep_backup) {
    // Rename replaces final atomically on supported platforms. Preserve final
    // until replacement; failure leaves the previous committed file intact.
  }

  std::filesystem::rename(temporary_path, final_path, ec);
  if (ec) {
    if (keep_backup && std::filesystem::exists(backup)) {
      std::error_code restore_error;
      std::filesystem::rename(backup, final_path, restore_error);
    }
    result.error = "cannot install new save: " + ec.message();
    return result;
  }

  const std::filesystem::path directory = final_path.parent_path().empty()
                                              ? std::filesystem::current_path()
                                              : final_path.parent_path();
  if (!sync_directory(directory, result.error)) {
    return result;
  }
  result.ok = true;
  return result;
}

AtomicSaveResult atomic_write_file(const std::filesystem::path& final_path,
                                   const AtomicWriter& writer,
                                   bool keep_backup) {
  const std::filesystem::path temporary = temp_path_for(final_path);
  std::error_code ec;
  std::filesystem::remove(temporary, ec);
  std::string writer_error;
  if (!writer(temporary, writer_error)) {
    std::filesystem::remove(temporary, ec);
    return {false, writer_error.empty() ? "save writer failed" : writer_error};
  }
  return atomic_commit_existing(temporary, final_path, keep_backup);
}

AtomicSaveResult recover_atomic_file(const std::filesystem::path& final_path,
                                     const AtomicValidator& validate) {
  if(!validate)return {false,"recovery requires a save-format validator"};
  std::error_code ec;
  std::string error;
  for(const auto& path : {final_path,backup_path_for(final_path)}) {
    bool exists=std::filesystem::exists(path,ec);
    if(ec)return {false,"recovery inspect: "+ec.message()};
    if(!exists)continue;
    if(!validate(path,error))continue;
    if(path==final_path)return {true,{}};
    // Keep the verified backup intact while restoring final.
    auto result=atomic_write_file(final_path,[&](const auto& temporary,std::string& detail){
      std::filesystem::copy_file(path,temporary,std::filesystem::copy_options::overwrite_existing,ec);
      if(ec){detail=ec.message();return false;}return true;
    },false);
    return result;
  }
  return {false,error.empty()?"no validated final or backup save found":error};
}

}  // namespace cth3ds
