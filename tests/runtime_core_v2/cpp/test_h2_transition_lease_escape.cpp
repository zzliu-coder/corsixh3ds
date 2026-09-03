#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include <unistd.h>

#include "cth3ds/runtime_session.hpp"

namespace {

cth3ds::ResourceId resource_id(std::uint8_t value) {
  cth3ds::ResourceId id{};
  id[0] = value;
  return id;
}

std::shared_ptr<cth3ds::MountedBundle> make_bundle() {
  auto bundle = std::make_shared<cth3ds::MountedBundle>();
  cth3ds::MountedPackage package;
  package.id[0] = 0xC2U;
  package.role = cth3ds::PackageRole::Core;
  package.path = std::filesystem::temp_directory_path() /
                 ("cth3ds-v2-c2-h2-" +
                  std::to_string(static_cast<long long>(::getpid())) + ".bin");
  for (std::size_t index = 0U;
       index < static_cast<std::size_t>(cth3ds::ResourcePool::Count); ++index) {
    package.budgets.bytes[index] = cth3ds::resource_pool_limit(
        static_cast<cth3ds::ResourcePool>(index));
  }

  std::ofstream output(package.path, std::ios::binary | std::ios::trunc);
  for (std::uint8_t value = 1U; value <= 2U; ++value) {
    const std::vector<std::uint8_t> bytes(32U, value);
    cth3ds::ResourceDescriptor descriptor;
    descriptor.id = resource_id(value);
    descriptor.kind = cth3ds::ResourceKind::UiBitmap;
    descriptor.flags = cth3ds::kTh3dsRequiredFlag |
                       (value == 1U ? cth3ds::kTh3dsPinOnMountFlag : 0U);
    descriptor.group_id = value;
    descriptor.alignment = 64U;
    descriptor.data_offset = static_cast<std::uint64_t>((value - 1U) * 32U);
    descriptor.stored_size = static_cast<std::uint32_t>(bytes.size());
    descriptor.decoded_size = descriptor.stored_size;
    descriptor.stored_sha256 = cth3ds::sha256(bytes.data(), bytes.size());
    descriptor.decoded_sha256 = descriptor.stored_sha256;
    package.resources.push_back(descriptor);
    output.write(reinterpret_cast<const char*>(bytes.data()),
                 static_cast<std::streamsize>(bytes.size()));
  }
  output.close();
  bundle->packages.push_back(std::move(package));
  auto catalog = cth3ds::ResourceCatalog::build(bundle->packages);
  if (!catalog) return nullptr;
  bundle->catalog = std::move(catalog.value());
  return bundle;
}

cth3ds::ResourceResult<void> prepare_abort() {
  return cth3ds::ResourceResult<void>::failure(
      {cth3ds::ResourceErrorCode::Io, "E_TEST_PREPARE_ABORT", {}});
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

template <typename T, std::size_t N>
void print_values(const std::array<T, N>& values) {
  std::cout << '[';
  for (std::size_t index = 0U; index < N; ++index) {
    if (index != 0U) std::cout << ',';
    std::cout << values[index];
  }
  std::cout << ']';
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 5 || std::string(argv[1]) != "--run-id" ||
      std::string(argv[3]) != "--fault" ||
      std::string(argv[4]) != "after-first-staged-acquire") {
    std::cerr << "usage: test_h2_transition_lease_escape --run-id HEX32 "
                 "--fault after-first-staged-acquire\n";
    return 2;
  }
  const std::string run_id = argv[2];
  const bool run_id_valid = run_id.size() == 32U &&
      std::all_of(run_id.begin(), run_id.end(), [](unsigned char value) {
        return std::isdigit(value) != 0 || (value >= 'a' && value <= 'f');
      });
  if (!run_id_valid) {
    std::cerr << "H2 run id is invalid\n";
    return 2;
  }

  auto bundle = make_bundle();
  if (bundle == nullptr) {
    std::cerr << "H2 synthetic catalog build failed\n";
    return 2;
  }
  const auto payload_path = bundle->packages.front().path;
  auto started = cth3ds::RuntimeSession::start_mounted_for_test(bundle);
  if (!started) {
    std::cerr << "H2 session start failed\n";
    return 2;
  }

  auto& session = *started.value();
  const auto before = session.snapshot();
  cth3ds::ResourceLease escaped;
  const auto transition = session.enter_level(
      2U, [&escaped](cth3ds::ResourceManager& manager) {
        cth3ds::AcquirePolicy policy;
        policy.expected_kind = cth3ds::ResourceKind::UiBitmap;
        auto acquired = manager.acquire(resource_id(2U), policy);
        if (!acquired) {
          return cth3ds::ResourceResult<void>::failure(acquired.error());
        }
        escaped = std::move(acquired.value());
        return prepare_abort();
      });
  const auto after = session.snapshot();

  const bool escaped_valid = escaped.valid();
  const auto released = escaped.release();
  const auto shutdown = session.shutdown();
  std::error_code ignored;
  std::filesystem::remove(payload_path, ignored);
  if (!released || !shutdown) {
    std::cerr << "H2 cleanup failed\n";
    return 2;
  }

  const std::string code = transition.ok()
                               ? "OK"
                               : (!transition.error().message.empty()
                                      ? transition.error().message
                                      : cth3ds::resource_error_name(
                                            transition.error().code));
  std::cout << "{\"schema\":\"cth3ds.runtime-core-raw-observation/v4\","
            << "\"stage_id\":\"C3\",\"run_id\":\"" << run_id
            << "\",\"gate_id\":\"RH07-H2\","
            << "\"oracle_id\":\"H2_TRANSITION_CAPABILITY_ROLLBACK\","
            << "\"observations\":{"
            << "\"fault_point\":\"after-first-staged-acquire\","
            << "\"call_result\":\"" << code << "\","
            << "\"state_before\":\"" << state_name(before.state) << "\","
            << "\"state_after\":\"" << state_name(after.state) << "\","
            << "\"transition_active_before\":"
            << (before.resources.transition_active ? "true" : "false") << ','
            << "\"transition_active_after\":"
            << (after.resources.transition_active ? "true" : "false") << ','
            << "\"mounted_package_count_before\":" << before.mounted_packages
            << ",\"mounted_package_count_after\":" << after.mounted_packages
            << ",\"entries_before\":" << before.resources.entries
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
  print_values(before.resources.pool_bytes);
  std::cout << ",\"pool_bytes_after\":";
  print_values(after.resources.pool_bytes);
  std::cout << ",\"backend_bytes_before\":";
  print_values(before.resources.backend_bytes);
  std::cout << ",\"backend_bytes_after\":";
  print_values(after.resources.backend_bytes);
  std::cout << ",\"regular_reconciliation_before\":"
            << before.resources.reconciliation.regular_delta_bytes
            << ",\"regular_reconciliation_after\":"
            << after.resources.reconciliation.regular_delta_bytes
            << ",\"linear_reconciliation_before\":"
            << before.resources.reconciliation.linear_delta_bytes
            << ",\"linear_reconciliation_after\":"
            << after.resources.reconciliation.linear_delta_bytes
            << ",\"escaped_lease_valid_after\":"
            << (escaped_valid ? "true" : "false")
            << "}}\n";
  return 0;
}
