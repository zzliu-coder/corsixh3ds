#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <sstream>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#include <unistd.h>

#include "cth3ds/runtime_session.hpp"
#include "cth3ds/sha256.hpp"

namespace {

std::filesystem::path make_runtime_fixture(
    const std::filesystem::path& fixture) {
  static std::uint64_t sequence = 0U;
  const auto root = std::filesystem::temp_directory_path() /
                    ("cth3ds-v2-c2-h1-" +
                     std::to_string(static_cast<long long>(::getpid())) + "-" +
                     std::to_string(++sequence));
  std::filesystem::create_directories(root / "lang");
  std::filesystem::copy_file(fixture / "core.package.bin",
                             root / "core.th3ds");
  std::filesystem::copy_file(fixture / "lang" / "en.package.bin",
                             root / "lang" / "en.th3ds");
  std::filesystem::copy_file(fixture / "bundle.json", root / "bundle.json");
  return root;
}

std::string read_text(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(input),
          std::istreambuf_iterator<char>()};
}

std::size_t declared_level_count(const std::string& manifest) {
  constexpr std::string_view marker{"\"role\":\"level\""};
  std::size_t count = 0U;
  std::size_t cursor = 0U;
  while ((cursor = manifest.find(marker, cursor)) != std::string::npos) {
    ++count;
    cursor += marker.size();
  }
  return count;
}

const char* state_name(cth3ds::RuntimeSessionState state) {
  switch (state) {
    case cth3ds::RuntimeSessionState::Closed: return "CLOSED";
    case cth3ds::RuntimeSessionState::Starting: return "STARTING";
    case cth3ds::RuntimeSessionState::Menu: return "MENU_STABLE";
    case cth3ds::RuntimeSessionState::Transitioning: return "TRANSITIONING";
    case cth3ds::RuntimeSessionState::Level: return "LEVEL_STABLE";
    case cth3ds::RuntimeSessionState::Suspended: return "SUSPENDED";
    case cth3ds::RuntimeSessionState::ShuttingDown: return "SHUTTING_DOWN";
    case cth3ds::RuntimeSessionState::Error: return "ERROR";
  }
  return "UNKNOWN";
}

std::vector<std::string> mounted_package_ids(const cth3ds::MountedBundle& bundle) {
  std::vector<std::string> result;
  result.reserve(bundle.packages.size());
  for (const auto& package : bundle.packages) {
    result.push_back(cth3ds::resource_id_hex(package.id));
  }
  std::sort(result.begin(), result.end());
  return result;
}

std::string catalog_fingerprint(const cth3ds::MountedBundle& bundle) {
  std::vector<std::string> rows;
  for (const auto& package : bundle.packages) {
    const std::string package_id = cth3ds::resource_id_hex(package.id);
    rows.push_back("package=" + package_id);
    for (const auto& descriptor : package.resources) {
      std::ostringstream row;
      row << "resource=" << cth3ds::resource_id_hex(descriptor.id)
          << "|package=" << package_id
          << "|kind=" << static_cast<unsigned>(descriptor.kind)
          << "|group=" << descriptor.group_id
          << "|size=" << descriptor.decoded_size
          << "|hash=" << cth3ds::sha256_hex(descriptor.decoded_sha256);
      rows.push_back(row.str());
    }
  }
  std::sort(rows.begin(), rows.end());
  cth3ds::Sha256 hash;
  constexpr char domain[] = "cth3ds-runtime-core-catalog-v1\n";
  hash.update(domain, sizeof(domain) - 1U);
  for (const auto& row : rows) {
    hash.update(row.data(), row.size());
    constexpr char newline = '\n';
    hash.update(&newline, 1U);
  }
  return cth3ds::sha256_hex(hash.finish());
}

void print_string_array(const std::vector<std::string>& values) {
  std::cout << '[';
  for (std::size_t index = 0U; index < values.size(); ++index) {
    if (index != 0U) std::cout << ',';
    std::cout << '"' << values[index] << '"';
  }
  std::cout << ']';
}

template <typename T, std::size_t N>
void print_integer_array(const std::array<T, N>& values) {
  std::cout << '[';
  for (std::size_t index = 0U; index < values.size(); ++index) {
    if (index != 0U) std::cout << ',';
    std::cout << values[index];
  }
  std::cout << ']';
}

std::string call_result(const cth3ds::ResourceResult<void>& result) {
  if (result.ok()) return "OK";
  if (!result.error().message.empty()) return result.error().message;
  return cth3ds::resource_error_name(result.error().code);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 7 || std::string(argv[1]) != "--run-id" ||
      std::string(argv[3]) != "--fixture" ||
      std::string(argv[5]) != "--level") {
    std::cerr << "usage: test_h1_level_requires_package --run-id HEX32 "
                 "--fixture DIR --level CANONICAL_ID\n";
    return 2;
  }

  const std::string run_id = argv[2];
  const bool run_id_valid = run_id.size() == 32U &&
      std::all_of(run_id.begin(), run_id.end(), [](unsigned char value) {
        return std::isdigit(value) != 0 || (value >= 'a' && value <= 'f');
      });
  if (!run_id_valid) {
    std::cerr << "H1 run id is invalid\n";
    return 2;
  }
  const std::filesystem::path fixture = argv[4];
  const std::string requested = argv[6];
  const std::string manifest = read_text(fixture / "bundle.json");
  const std::string origin = read_text(fixture / "fixture-manifest.json");
  const std::size_t levels = declared_level_count(manifest);
  if (manifest.empty() || manifest.find("\"start_level\":null") ==
                              std::string::npos ||
      origin.find("\"payload_origin\":\"generated_synthetic\"") ==
          std::string::npos ||
      levels != 0U || requested != "hospital-01") {
    std::cerr << "H1 fixture contract is invalid\n";
    return 2;
  }

  std::filesystem::path runtime_fixture;
  try {
    runtime_fixture = make_runtime_fixture(fixture);
  } catch (const std::exception& error) {
    std::cerr << "H1 fixture materialization failed: " << error.what() << '\n';
    return 2;
  }

  auto started = cth3ds::RuntimeSession::start(runtime_fixture / "bundle.json");
  if (!started) {
    std::error_code ignored;
    std::filesystem::remove_all(runtime_fixture, ignored);
    std::cerr << "H1 session start failed: "
              << static_cast<unsigned>(started.error().code) << '\n';
    return 2;
  }

  auto& session = *started.value();
  const auto* bundle_before = session.bundle();
  if (bundle_before == nullptr) return 2;
  const auto package_ids_before = mounted_package_ids(*bundle_before);
  const std::string fingerprint_before = catalog_fingerprint(*bundle_before);
  const auto before = session.snapshot();
  const auto transition = session.enter_level(2U);
  const auto after = session.snapshot();
  const auto* bundle_after = session.bundle();
  if (bundle_after == nullptr) return 2;
  const auto package_ids_after = mounted_package_ids(*bundle_after);
  const std::string fingerprint_after = catalog_fingerprint(*bundle_after);

  const auto shutdown = session.shutdown();
  std::error_code ignored;
  std::filesystem::remove_all(runtime_fixture, ignored);
  if (!shutdown) {
    std::cerr << "H1 cleanup failed\n";
    return 2;
  }

  std::cout << "{\"schema\":\"cth3ds.runtime-core-raw-observation/v4\","
            << "\"stage_id\":\"C3\",\"run_id\":\"" << run_id
            << "\",\"gate_id\":\"RH09-H1\","
            << "\"oracle_id\":\"H1_LEVEL_REQUIRES_DECLARED_PACKAGE\","
            << "\"observations\":{"
            << "\"call_result\":\"" << call_result(transition) << "\","
            << "\"requested_level\":\"" << requested << "\","
            << "\"declared_level_count\":" << levels << ','
            << "\"state_before\":\"" << state_name(before.state) << "\","
            << "\"state_after\":\"" << state_name(after.state) << "\","
            << "\"mounted_package_ids_before\":";
  print_string_array(package_ids_before);
  std::cout << ",\"mounted_package_ids_after\":";
  print_string_array(package_ids_after);
  std::cout << ",\"mount_generation_before\":" << before.mount_generation
            << ",\"mount_generation_after\":" << after.mount_generation
            << ",\"catalog_generation_before\":" << before.catalog_generation
            << ",\"catalog_generation_after\":" << after.catalog_generation
            << ",\"catalog_fingerprint_before\":\"" << fingerprint_before
            << "\",\"catalog_fingerprint_after\":\"" << fingerprint_after
            << "\",\"entries_before\":" << before.resources.entries
            << ",\"entries_after\":" << after.resources.entries
            << ",\"leases_before\":" << before.resources.leases
            << ",\"leases_after\":" << after.resources.leases
            << ",\"pins_before\":" << before.resources.pins
            << ",\"pins_after\":" << after.resources.pins
            << ",\"dependencies_before\":" << before.resources.dependents
            << ",\"dependencies_after\":" << after.resources.dependents
            << ",\"allocation_records_before\":"
            << before.resources.allocation_records
            << ",\"allocation_records_after\":"
            << after.resources.allocation_records
            << ",\"pool_bytes_before\":";
  print_integer_array(before.resources.pool_bytes);
  std::cout << ",\"pool_bytes_after\":";
  print_integer_array(after.resources.pool_bytes);
  std::cout << ",\"backend_bytes_before\":";
  print_integer_array(before.resources.backend_bytes);
  std::cout << ",\"backend_bytes_after\":";
  print_integer_array(after.resources.backend_bytes);
  std::cout << ",\"regular_reconciliation_before\":"
            << before.resources.reconciliation.regular_delta_bytes
            << ",\"regular_reconciliation_after\":"
            << after.resources.reconciliation.regular_delta_bytes
            << ",\"linear_reconciliation_before\":"
            << before.resources.reconciliation.linear_delta_bytes
            << ",\"linear_reconciliation_after\":"
            << after.resources.reconciliation.linear_delta_bytes
            << ",\"transition_active_after\":"
            << (after.resources.transition_active ? "true" : "false")
            << "}}\n";
  return 0;
}
