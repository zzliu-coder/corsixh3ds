#include <algorithm>
#include <filesystem>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <unistd.h>

#include "cth3ds/runtime_session.hpp"
#include "test_framework.hpp"

namespace {

cth3ds::ResourceId session_id(std::uint8_t value) {
  cth3ds::ResourceId result{};
  result[0] = value;
  return result;
}

std::shared_ptr<cth3ds::MountedBundle> session_bundle() {
  static std::uint64_t sequence = 0U;
  auto bundle = std::make_shared<cth3ds::MountedBundle>();
  cth3ds::MountedPackage package;
  package.role = cth3ds::PackageRole::Core;
  package.path = std::filesystem::temp_directory_path() /
                 ("cth3ds-session-" +
                  std::to_string(static_cast<long long>(::getpid())) + "-" +
                  std::to_string(++sequence) + ".bin");
  for (std::size_t index = 0U;
       index < static_cast<std::size_t>(cth3ds::ResourcePool::Count); ++index) {
    package.budgets.bytes[index] = cth3ds::resource_pool_limit(
        static_cast<cth3ds::ResourcePool>(index));
  }
  std::ofstream output(package.path, std::ios::binary | std::ios::trunc);
  for (std::uint8_t value = 1U; value <= 2U; ++value) {
    const std::vector<std::uint8_t> bytes(32U, value);
    cth3ds::ResourceDescriptor descriptor;
    descriptor.id = session_id(value);
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
  EXPECT_TRUE(catalog.ok());
  bundle->catalog = std::move(catalog.value());
  return bundle;
}

cth3ds::ResourceResult<void> synthetic_failure() {
  return cth3ds::ResourceResult<void>::failure(
      {cth3ds::ResourceErrorCode::Io, "synthetic operation failure", {}});
}

}  // namespace

TEST(runtime_session_owns_mount_pins_and_reverses_them_on_shutdown) {
  auto started = cth3ds::RuntimeSession::start_mounted_for_test(session_bundle());
  EXPECT_TRUE(started.ok());
  auto& session = *started.value();
  EXPECT_EQ(session.snapshot().state, cth3ds::RuntimeSessionState::Menu);
  EXPECT_EQ(session.snapshot().mounted_packages, 1U);
  EXPECT_EQ(session.snapshot().mount_generation, std::uint64_t{1U});
  EXPECT_EQ(session.snapshot().catalog_generation, std::uint64_t{1U});
  const auto published = session.snapshot();
  EXPECT_EQ(session.snapshot().mount_generation, published.mount_generation);
  EXPECT_EQ(session.snapshot().catalog_generation, published.catalog_generation);
  EXPECT_EQ(session.snapshot().resources.entries, 1U);
  EXPECT_EQ(session.snapshot().resources.pins, 1U);
  EXPECT_TRUE(session.shutdown().ok());
  EXPECT_EQ(session.snapshot().state, cth3ds::RuntimeSessionState::Closed);
  EXPECT_EQ(session.snapshot().mounted_packages, 0U);
  EXPECT_EQ(session.snapshot().mount_generation, std::uint64_t{1U});
  EXPECT_EQ(session.snapshot().catalog_generation, std::uint64_t{1U});
  EXPECT_TRUE(session.snapshot().ledger_at_baseline);
}

TEST(runtime_session_transition_and_save_failures_restore_the_stable_world) {
  auto started = cth3ds::RuntimeSession::start_mounted_for_test(session_bundle());
  EXPECT_TRUE(started.ok());
  auto& session = *started.value();
  const auto before = session.snapshot();
  const auto failed_level = session.enter_level(
      2U, [](cth3ds::ResourceManager& manager) {
        cth3ds::AcquirePolicy policy;
        policy.expected_kind = cth3ds::ResourceKind::UiBitmap;
        auto target = manager.acquire(session_id(2U), policy);
        if (!target) return cth3ds::ResourceResult<void>::failure(target.error());
        auto released = target.value().release();
        if (!released) return released;
        return synthetic_failure();
      });
  EXPECT_FALSE(failed_level.ok());
  EXPECT_EQ(session.snapshot().state, cth3ds::RuntimeSessionState::Menu);
  EXPECT_EQ(session.snapshot().resources.entries, before.resources.entries);
  EXPECT_EQ(session.snapshot().resources.payload_bytes,
            before.resources.payload_bytes);

  EXPECT_TRUE(session.enter_level(
      2U, [](cth3ds::ResourceManager& manager) {
        cth3ds::AcquirePolicy policy;
        policy.expected_kind = cth3ds::ResourceKind::UiBitmap;
        auto target = manager.acquire(session_id(2U), policy);
        if (!target) return cth3ds::ResourceResult<void>::failure(target.error());
        return target.value().release();
      }).ok());
  EXPECT_EQ(session.snapshot().state, cth3ds::RuntimeSessionState::Level);
  const auto level = session.snapshot();
  EXPECT_FALSE(session.save_or_load(
      [](cth3ds::ResourceManager&) { return synthetic_failure(); }).ok());
  EXPECT_EQ(session.snapshot().state, cth3ds::RuntimeSessionState::Level);
  EXPECT_EQ(session.snapshot().resources.entries, level.resources.entries);
  EXPECT_TRUE(session.enter_menu(1U).ok());
  EXPECT_TRUE(session.shutdown().ok());
}

TEST(runtime_session_shutdown_refuses_live_leases_and_then_closes_cleanly) {
  auto started = cth3ds::RuntimeSession::start_mounted_for_test(session_bundle());
  EXPECT_TRUE(started.ok());
  auto& session = *started.value();
  auto lease = session.acquire(session_id(1U), cth3ds::ResourceKind::UiBitmap);
  EXPECT_TRUE(lease.ok());
  const auto blocked = session.shutdown();
  EXPECT_FALSE(blocked.ok());
  EXPECT_EQ(blocked.error().code, cth3ds::ResourceErrorCode::GroupBusy);
  EXPECT_EQ(session.snapshot().state, cth3ds::RuntimeSessionState::Menu);
  EXPECT_TRUE(lease.value().release().ok());
  EXPECT_TRUE(session.shutdown().ok());
}

TEST(runtime_session_home_lifecycle_quiesces_before_suspend_and_shutdown) {
  std::size_t quiesce_count = 0U;
  cth3ds::RuntimeSessionConfig config;
  config.quiesce_clients = [&quiesce_count]() {
    ++quiesce_count;
    return cth3ds::ResourceResult<void>::success();
  };
  auto started = cth3ds::RuntimeSession::start_mounted_for_test(
      session_bundle(), std::move(config));
  EXPECT_TRUE(started.ok());
  auto& session = *started.value();
  EXPECT_TRUE(session.suspend().ok());
  EXPECT_EQ(session.snapshot().state, cth3ds::RuntimeSessionState::Suspended);
  EXPECT_TRUE(session.resume().ok());
  EXPECT_EQ(session.snapshot().state, cth3ds::RuntimeSessionState::Menu);
  EXPECT_TRUE(session.shutdown().ok());
  EXPECT_EQ(quiesce_count, 2U);
  const auto& trace = session.trace();
  EXPECT_TRUE(std::find(trace.begin(), trace.end(),
                        cth3ds::RuntimeSessionEvent::Suspend) != trace.end());
  EXPECT_TRUE(std::find(trace.begin(), trace.end(),
                        cth3ds::RuntimeSessionEvent::ShutdownCommit) != trace.end());
}

TEST(runtime_session_contains_throwing_operation_callbacks) {
  auto started = cth3ds::RuntimeSession::start_mounted_for_test(session_bundle());
  EXPECT_TRUE(started.ok());
  auto& session = *started.value();
  const auto result = session.save_or_load([](cth3ds::ResourceManager&)
      -> cth3ds::ResourceResult<void> {
    throw std::runtime_error("synthetic callback exception");
  });
  EXPECT_FALSE(result.ok());
  EXPECT_EQ(result.error().code, cth3ds::ResourceErrorCode::Internal);
  EXPECT_EQ(session.snapshot().state, cth3ds::RuntimeSessionState::Menu);
  EXPECT_TRUE(session.shutdown().ok());
}

TEST(runtime_session_save_load_token_spans_external_operation) {
  auto bundle = session_bundle();
  auto session_result = cth3ds::RuntimeSession::start_mounted_for_test(bundle);
  EXPECT_TRUE(session_result.ok());
  auto& session = *session_result.value();

  EXPECT_TRUE(session.begin_save_load().ok());
  EXPECT_FALSE(session.begin_save_load().ok());
  EXPECT_TRUE(session.finish_save_load(false).ok());
  EXPECT_FALSE(session.finish_save_load(true).ok());
  EXPECT_TRUE(session.begin_save_load().ok());
  EXPECT_TRUE(session.finish_save_load(true).ok());
  EXPECT_TRUE(session.shutdown().ok());
}

TEST(runtime_session_ten_thousand_owner_mount_and_shutdown_cycles) {
  auto bundle = session_bundle();
  for (std::size_t iteration = 0U; iteration < 10000U; ++iteration) {
    auto started = cth3ds::RuntimeSession::start_mounted_for_test(bundle);
    EXPECT_TRUE(started.ok());
    auto& session = *started.value();
    EXPECT_TRUE(session.enter_level(2U).ok());
    EXPECT_TRUE(session.begin_save_load().ok());
    EXPECT_TRUE(session.finish_save_load(true).ok());
    EXPECT_TRUE(session.enter_menu(1U).ok());
    EXPECT_TRUE(session.shutdown().ok());
    const auto closed = session.snapshot();
    EXPECT_TRUE(closed.ledger_at_baseline);
    EXPECT_EQ(closed.mounted_packages, 0U);
    EXPECT_EQ(closed.resources.entries, 0U);
    EXPECT_EQ(closed.resources.leases, 0U);
    EXPECT_EQ(closed.resources.pins, 0U);
  }
}
