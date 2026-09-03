#include <algorithm>
#include <array>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <unistd.h>

#include "cth3ds/resource_manager.hpp"
#include "test_framework.hpp"

namespace {

struct FixtureResource {
  cth3ds::ResourceId id{};
  cth3ds::ResourceKind kind{cth3ds::ResourceKind::UiBitmap};
  std::uint32_t group{1U};
  std::uint32_t flags{cth3ds::kTh3dsRequiredFlag};
  std::vector<std::uint8_t> bytes{};
};

std::filesystem::path temporary_file(const std::string& name) {
  static std::uint64_t sequence = 0U;
  return std::filesystem::temp_directory_path() /
         ("cth3ds-runtime-" + std::to_string(static_cast<long long>(::getpid())) +
          "-" + name + "-" + std::to_string(++sequence) + ".bin");
}

std::shared_ptr<cth3ds::MountedBundle> make_bundle(
    const std::vector<FixtureResource>& resources,
    std::uint64_t texture_budget = cth3ds::resource_pool_limit(
        cth3ds::ResourcePool::Texture)) {
  auto bundle = std::make_shared<cth3ds::MountedBundle>();
  cth3ds::MountedPackage package;
  package.path = temporary_file("payload");
  for (std::size_t index = 0U;
       index < static_cast<std::size_t>(cth3ds::ResourcePool::Count); ++index) {
    package.budgets.bytes[index] = cth3ds::resource_pool_limit(
        static_cast<cth3ds::ResourcePool>(index));
  }
  package.budgets.bytes[static_cast<std::size_t>(cth3ds::ResourcePool::Texture)] =
      texture_budget;
  std::ofstream output(package.path, std::ios::binary | std::ios::trunc);
  std::uint64_t offset = 0U;
  for (const FixtureResource& item : resources) {
    cth3ds::ResourceDescriptor descriptor;
    descriptor.id = item.id;
    descriptor.kind = item.kind;
    descriptor.codec = cth3ds::ResourceCodec::None;
    descriptor.flags = item.flags;
    descriptor.group_id = item.group;
    descriptor.alignment = 64U;
    descriptor.data_offset = offset;
    descriptor.stored_size = static_cast<std::uint32_t>(item.bytes.size());
    descriptor.decoded_size = descriptor.stored_size;
    descriptor.stored_sha256 = cth3ds::sha256(item.bytes.data(), item.bytes.size());
    descriptor.decoded_sha256 = descriptor.stored_sha256;
    package.resources.push_back(descriptor);
    if (!item.bytes.empty()) {
      output.write(reinterpret_cast<const char*>(item.bytes.data()),
                   static_cast<std::streamsize>(item.bytes.size()));
    }
    offset += item.bytes.size();
  }
  output.close();
  bundle->packages.push_back(std::move(package));
  auto catalog = cth3ds::ResourceCatalog::build(bundle->packages);
  EXPECT_TRUE(catalog.ok());
  bundle->catalog = std::move(catalog.value());
  return bundle;
}

cth3ds::ResourceId id(std::uint8_t value) {
  cth3ds::ResourceId result{};
  result[0] = value;
  return result;
}

FixtureResource bitmap(std::uint8_t identity, std::size_t size,
                       std::uint32_t group = 1U, std::uint32_t flags = 1U) {
  return {id(identity), cth3ds::ResourceKind::UiBitmap, group, flags,
          std::vector<std::uint8_t>(size, identity)};
}

cth3ds::AcquirePolicy bitmap_policy() {
  cth3ds::AcquirePolicy policy;
  policy.expected_kind = cth3ds::ResourceKind::UiBitmap;
  return policy;
}

std::uint64_t charge(std::uint64_t bytes) {
  return cth3ds::resource_allocation_reservation(bytes, 64U);
}

class RejectGate final : public cth3ds::ResourceBudgetGate {
 public:
  bool allow_allocation(cth3ds::ResourceStage, cth3ds::ResourcePool,
                        std::uint64_t, std::uint64_t, std::uint64_t,
                        cth3ds::ResourceError& error) noexcept override {
    error = {cth3ds::ResourceErrorCode::BudgetContract, "synthetic gate", {}};
    return false;
  }
  bool allow_operation(cth3ds::TransitionKind,
                       cth3ds::ResourceError&) noexcept override {
    return true;
  }
};

class RejectOperationGate final : public cth3ds::ResourceBudgetGate {
 public:
  bool allow_allocation(cth3ds::ResourceStage, cth3ds::ResourcePool,
                        std::uint64_t, std::uint64_t, std::uint64_t,
                        cth3ds::ResourceError&) noexcept override {
    return true;
  }
  bool allow_operation(cth3ds::TransitionKind kind,
                       cth3ds::ResourceError& error) noexcept override {
    error = {kind == cth3ds::TransitionKind::SaveLoad
                 ? cth3ds::ResourceErrorCode::SaveReserve
                 : cth3ds::ResourceErrorCode::TransitionReserve,
             "synthetic operation reserve failure", {}};
    return false;
  }
};

class FailOnce final : public cth3ds::ResourceFaultInjector {
 public:
  explicit FailOnce(cth3ds::AllocationPoint point) : point_(point) {}
  bool fail(cth3ds::AllocationPoint point) noexcept override {
    if (!armed_ || point != point_) return false;
    armed_ = false;
    return true;
  }
  void arm(cth3ds::AllocationPoint point) noexcept {
    point_ = point;
    armed_ = true;
  }

 private:
  cth3ds::AllocationPoint point_;
  bool armed_{true};
};

}  // namespace

TEST(resource_manager_lease_reuses_one_owner_and_rejects_double_release) {
  auto bundle = make_bundle({bitmap(1U, 4U)});
  cth3ds::ResourceManager manager(bundle);
  auto first = manager.acquire(id(1U), bitmap_policy());
  auto second = manager.acquire(id(1U), bitmap_policy());
  EXPECT_TRUE(first.ok());
  EXPECT_TRUE(second.ok());
  EXPECT_EQ(first.value().bytes().data, second.value().bytes().data);
  EXPECT_EQ(manager.snapshot().entries, 1U);
  EXPECT_EQ(manager.snapshot().leases, 2U);
  EXPECT_TRUE(first.value().release().ok());
  const auto repeated = first.value().release();
  EXPECT_FALSE(repeated.ok());
  EXPECT_EQ(repeated.error().code, cth3ds::ResourceErrorCode::RefcountCorrupt);
  EXPECT_EQ(manager.snapshot().leases, 1U);
}

TEST(resource_manager_lru_is_deterministic_and_never_evicts_live_or_pinned) {
  auto bundle = make_bundle({bitmap(1U, 4U), bitmap(2U, 4U), bitmap(3U, 4U)},
                            charge(4U) * 2U);
  cth3ds::ResourceManager manager(bundle);
  auto first = manager.acquire(id(1U), bitmap_policy());
  auto second = manager.acquire(id(2U), bitmap_policy());
  EXPECT_TRUE(first.ok());
  EXPECT_TRUE(second.ok());
  EXPECT_TRUE(first.value().release().ok());
  EXPECT_TRUE(second.value().release().ok());
  auto third = manager.acquire(id(3U), bitmap_policy());
  EXPECT_TRUE(third.ok());
  EXPECT_EQ(manager.snapshot().evictions, 1U);
  auto reacquire_first = manager.acquire(id(1U), bitmap_policy());
  EXPECT_TRUE(reacquire_first.ok());
  EXPECT_EQ(manager.snapshot().evictions, 2U);

  auto live_bundle = make_bundle({bitmap(4U, 4U), bitmap(5U, 4U)}, charge(4U));
  cth3ds::ResourceManager live_manager(live_bundle);
  auto live = live_manager.acquire(id(4U), bitmap_policy());
  EXPECT_TRUE(live.ok());
  auto rejected = live_manager.acquire(id(5U), bitmap_policy());
  EXPECT_FALSE(rejected.ok());
  EXPECT_EQ(rejected.error().code, cth3ds::ResourceErrorCode::BudgetTexture);

  auto pinned_bundle = make_bundle({bitmap(6U, 4U), bitmap(7U, 4U)}, charge(4U));
  cth3ds::ResourceManager pinned_manager(pinned_bundle);
  auto pinned = pinned_manager.acquire(id(6U), bitmap_policy());
  EXPECT_TRUE(pinned.ok());
  EXPECT_TRUE(pinned_manager.pin(id(6U)).ok());
  EXPECT_TRUE(pinned.value().release().ok());
  auto pinned_reject = pinned_manager.acquire(id(7U), bitmap_policy());
  EXPECT_FALSE(pinned_reject.ok());
}

TEST(resource_manager_pin_owners_are_independent_capabilities) {
  auto bundle = make_bundle({bitmap(8U, 4U)});
  cth3ds::ResourceManager manager(bundle);
  auto lease = manager.acquire(id(8U), bitmap_policy());
  EXPECT_TRUE(lease.ok());
  EXPECT_TRUE(manager.pin(id(8U), cth3ds::PinOwner::Session).ok());
  EXPECT_TRUE(manager.pin(id(8U), cth3ds::PinOwner::Adapter).ok());
  EXPECT_EQ(manager.snapshot().pins, 2U);
  EXPECT_TRUE(manager.unpin(id(8U), cth3ds::PinOwner::Session).ok());
  EXPECT_TRUE(lease.value().release().ok());
  manager.purge_zero_reference();
  EXPECT_EQ(manager.snapshot().entries, 1U);
  EXPECT_TRUE(manager.unpin(id(8U), cth3ds::PinOwner::Adapter).ok());
  manager.purge_zero_reference();
  EXPECT_EQ(manager.snapshot().entries, 0U);
}

TEST(resource_manager_budget_boundaries_and_preallocation_gate_fail_closed) {
  auto at_cap_bundle = make_bundle({bitmap(1U, 64U)}, charge(64U));
  cth3ds::ResourceManager at_cap(at_cap_bundle);
  EXPECT_TRUE(at_cap.acquire(id(1U), bitmap_policy()).ok());

  auto over_cap_bundle = make_bundle({bitmap(2U, 65U)}, charge(65U) - 1U);
  cth3ds::ResourceManager over_cap(over_cap_bundle);
  const auto over = over_cap.acquire(id(2U), bitmap_policy());
  EXPECT_FALSE(over.ok());
  EXPECT_EQ(over.error().code, cth3ds::ResourceErrorCode::BudgetTexture);
  EXPECT_EQ(over_cap.snapshot().entries, 0U);
  EXPECT_EQ(over_cap.snapshot().pool_bytes[static_cast<std::size_t>(
                cth3ds::ResourcePool::Texture)], 0U);

  auto gated_bundle = make_bundle({bitmap(3U, 5U)}, charge(5U));
  cth3ds::ResourceManager gated(gated_bundle, {},
                                std::make_shared<RejectGate>());
  const auto gated_result = gated.acquire(id(3U), bitmap_policy());
  EXPECT_FALSE(gated_result.ok());
  EXPECT_EQ(gated.snapshot().entries, 0U);
  EXPECT_EQ(gated.snapshot().rejects, 1U);
}

TEST(resource_manager_stream_reads_are_bounded_and_do_not_cache_container) {
  FixtureResource stream = bitmap(
      9U, 128U, 2U,
      cth3ds::kTh3dsRequiredFlag | cth3ds::kTh3dsStreamableFlag);
  auto bundle = make_bundle({stream});
  cth3ds::ResourceManager manager(bundle);
  const auto baseline_scratch = manager.snapshot().pool_bytes[
      static_cast<std::size_t>(cth3ds::ResourcePool::Scratch)];
  const auto whole = manager.acquire(id(9U), bitmap_policy());
  EXPECT_FALSE(whole.ok());
  EXPECT_EQ(whole.error().code, cth3ds::ResourceErrorCode::StreamRequired);
  std::vector<std::uint8_t> observed;
  const auto range = manager.read_stream_range(
      id(9U), cth3ds::ResourceKind::UiBitmap, 7U, 13U,
      [&observed](cth3ds::ByteView bytes) {
        observed.assign(bytes.data, bytes.data + bytes.size);
        return cth3ds::ResourceResult<void>::success();
      });
  EXPECT_TRUE(range.ok());
  EXPECT_EQ(observed.size(), 13U);
  EXPECT_EQ(observed[0], 9U);
  EXPECT_EQ(manager.snapshot().entries, 0U);
  EXPECT_EQ(manager.snapshot().pool_bytes[static_cast<std::size_t>(
                cth3ds::ResourcePool::Scratch)], baseline_scratch);
}

TEST(resource_manager_transitions_hold_old_group_until_leases_release) {
  auto bundle = make_bundle({bitmap(1U, 4U, 10U)});
  cth3ds::ResourceManager manager(bundle);
  auto initial = manager.begin_menu_transition(10U);
  EXPECT_TRUE(initial.ok());
  EXPECT_TRUE(initial.value().commit().ok());
  auto lease = manager.acquire(id(1U), bitmap_policy());
  EXPECT_TRUE(lease.ok());
  auto busy = manager.begin_first_level_transition(20U);
  EXPECT_FALSE(busy.ok());
  EXPECT_EQ(busy.error().code, cth3ds::ResourceErrorCode::GroupBusy);
  EXPECT_TRUE(lease.value().release().ok());
  auto transition = manager.begin_world_transition(20U);
  EXPECT_TRUE(transition.ok());
  EXPECT_TRUE(manager.snapshot().transition_active);
  EXPECT_TRUE(transition.value().commit().ok());
  EXPECT_EQ(manager.snapshot().active_group, 20U);
  EXPECT_FALSE(manager.snapshot().transition_active);
  auto save = manager.begin_save_load();
  EXPECT_TRUE(save.ok());
  save.value().cancel();
}

TEST(resource_manager_operation_reserve_failures_are_atomic_and_typed) {
  auto bundle = make_bundle({bitmap(10U, 4U, 1U)});
  cth3ds::ResourceManager manager(
      bundle, {}, std::make_shared<RejectOperationGate>());
  const auto baseline = manager.snapshot();
  const auto save = manager.begin_save_load();
  EXPECT_FALSE(save.ok());
  EXPECT_EQ(save.error().code, cth3ds::ResourceErrorCode::SaveReserve);
  EXPECT_FALSE(manager.snapshot().transition_active);
  EXPECT_EQ(manager.snapshot().entries, baseline.entries);
  const auto level = manager.begin_world_transition(2U);
  EXPECT_FALSE(level.ok());
  EXPECT_EQ(level.error().code, cth3ds::ResourceErrorCode::TransitionReserve);
  EXPECT_FALSE(manager.snapshot().transition_active);
  EXPECT_EQ(manager.snapshot().entries, baseline.entries);
}

TEST(decoded_hash_verifier_checks_size_and_digest) {
  const std::array<std::uint8_t, 3> bytes{{1U, 2U, 3U}};
  cth3ds::ResourceDescriptor descriptor;
  descriptor.id = id(3U);
  descriptor.decoded_size = static_cast<std::uint32_t>(bytes.size());
  descriptor.decoded_sha256 = cth3ds::sha256(bytes.data(), bytes.size());
  cth3ds::DecodedHashVerifier verifier(descriptor);
  verifier.update({bytes.data(), 1U});
  verifier.update({bytes.data() + 1U, 2U});
  EXPECT_TRUE(verifier.finish().ok());

  cth3ds::DecodedHashVerifier mismatch(descriptor);
  mismatch.update({bytes.data(), 2U});
  const auto failed = mismatch.finish();
  EXPECT_FALSE(failed.ok());
  EXPECT_EQ(failed.error().code, cth3ds::ResourceErrorCode::HashDecoded);
}

TEST(derived_stream_payloads_are_manager_owned_and_texture_keeps_sprite_alive) {
  FixtureResource source = bitmap(
      11U, 32U, 7U,
      cth3ds::kTh3dsRequiredFlag | cth3ds::kTh3dsStreamableFlag);
  source.kind = cth3ds::ResourceKind::SpriteSheet;
  auto bundle = make_bundle({source});
  bundle->packages[0].resources[0].decoded_size = 8U;
  cth3ds::ResourceManager manager(bundle);
  cth3ds::DerivedAcquirePolicy sprite_policy;
  sprite_policy.source_id = id(11U);
  sprite_policy.expected_source_kind = cth3ds::ResourceKind::SpriteSheet;
  sprite_policy.kind = cth3ds::DerivedResourceKind::SpritePixels;
  sprite_policy.ordinal = 3U;
  auto sprite = manager.acquire_derived(
      sprite_policy,
      [](const cth3ds::ResourceDescriptor&, cth3ds::MutableByteView destination,
         cth3ds::MutableByteView scratch, const cth3ds::DerivedRead& read) {
        auto result = read(0U, scratch);
        if (!result) return cth3ds::ResourceResult<std::size_t>::failure(result.error());
        for (std::size_t index = 0U; index < destination.size; ++index) {
          destination.data[index] = scratch.data[index % scratch.size];
        }
        return cth3ds::ResourceResult<std::size_t>::success(destination.size);
      });
  EXPECT_TRUE(sprite.ok());
  EXPECT_EQ(sprite.value().bytes().size, 8U);
  EXPECT_EQ(sprite.value().bytes().data[0], 11U);

  cth3ds::DerivedAcquirePolicy texture_policy = sprite_policy;
  texture_policy.kind = cth3ds::DerivedResourceKind::Texture;
  auto texture = manager.acquire_derived(
      texture_policy,
      [](const cth3ds::ResourceDescriptor&, cth3ds::MutableByteView destination,
         cth3ds::MutableByteView, const cth3ds::DerivedRead&) {
        std::fill(destination.data, destination.data + destination.size, 0x55U);
        return cth3ds::ResourceResult<std::size_t>::success(destination.size);
      });
  EXPECT_TRUE(texture.ok());
  EXPECT_EQ(texture.value().bytes().size, 16U);
  EXPECT_TRUE(sprite.value().release().ok());
  EXPECT_TRUE(texture.value().release().ok());
  manager.purge_zero_reference();
  EXPECT_EQ(manager.snapshot().entries, 0U);
  EXPECT_EQ(manager.snapshot().evictions, 2U);
}

TEST(resource_manager_ten_thousand_lease_cycles_return_to_baseline) {
  auto bundle = make_bundle({bitmap(12U, 32U)});
  cth3ds::ResourceManager manager(bundle);
  const auto baseline = manager.snapshot();
  for (std::size_t iteration = 0U; iteration < 10000U; ++iteration) {
    auto lease = manager.acquire(id(12U), bitmap_policy());
    EXPECT_TRUE(lease.ok());
    EXPECT_TRUE(lease.value().release().ok());
  }
  EXPECT_EQ(manager.snapshot().leases, 0U);
  manager.purge_zero_reference();
  const auto finished = manager.snapshot();
  EXPECT_EQ(finished.entries, baseline.entries);
  EXPECT_EQ(finished.backend_bytes, baseline.backend_bytes);
  EXPECT_EQ(finished.pool_bytes[static_cast<std::size_t>(
                cth3ds::ResourcePool::Texture)],
            baseline.pool_bytes[static_cast<std::size_t>(
                cth3ds::ResourcePool::Texture)]);
}

TEST(resource_manager_raw_allocation_faults_are_atomic) {
  const std::array<cth3ds::AllocationPoint, 3> points{{
      cth3ds::AllocationPoint::Payload,
      cth3ds::AllocationPoint::IndexNode,
      cth3ds::AllocationPoint::Publish,
  }};
  for (const auto point : points) {
    auto bundle = make_bundle({bitmap(13U, 32U)});
    auto faults = std::make_shared<FailOnce>(point);
    cth3ds::ResourceManager manager(bundle, {}, {}, faults);
    const auto baseline = manager.snapshot();
    const auto result = manager.acquire(id(13U), bitmap_policy());
    EXPECT_FALSE(result.ok());
    const auto after = manager.snapshot();
    EXPECT_EQ(after.entries, baseline.entries);
    EXPECT_EQ(after.leases, baseline.leases);
    EXPECT_EQ(after.payload_bytes, baseline.payload_bytes);
    EXPECT_EQ(after.allocation_overhead_bytes,
              baseline.allocation_overhead_bytes);
    EXPECT_EQ(after.pool_bytes[static_cast<std::size_t>(
                  cth3ds::ResourcePool::Texture)],
              baseline.pool_bytes[static_cast<std::size_t>(
                  cth3ds::ResourcePool::Texture)]);
  }
}

TEST(resource_manager_derived_faults_rollback_payload_scratch_index_and_edge) {
  FixtureResource source = bitmap(
      14U, 32U, 7U,
      cth3ds::kTh3dsRequiredFlag | cth3ds::kTh3dsStreamableFlag);
  source.kind = cth3ds::ResourceKind::SpriteSheet;
  auto bundle = make_bundle({source});
  bundle->packages[0].resources[0].decoded_size = 8U;
  auto faults = std::make_shared<FailOnce>(cth3ds::AllocationPoint::Scratch);
  cth3ds::ResourceManager manager(bundle, {}, {}, faults);
  cth3ds::DerivedAcquirePolicy sprite_policy;
  sprite_policy.source_id = id(14U);
  sprite_policy.expected_source_kind = cth3ds::ResourceKind::SpriteSheet;
  sprite_policy.kind = cth3ds::DerivedResourceKind::SpritePixels;
  sprite_policy.ordinal = 2U;
  const auto loader = [](
      const cth3ds::ResourceDescriptor&, cth3ds::MutableByteView destination,
      cth3ds::MutableByteView, const cth3ds::DerivedRead&) {
    std::fill(destination.data, destination.data + destination.size, 0x2AU);
    return cth3ds::ResourceResult<std::size_t>::success(destination.size);
  };
  const auto baseline = manager.snapshot();
  for (const auto point : {cth3ds::AllocationPoint::Scratch,
                           cth3ds::AllocationPoint::Payload,
                           cth3ds::AllocationPoint::IndexNode,
                           cth3ds::AllocationPoint::Publish}) {
    faults->arm(point);
    EXPECT_FALSE(manager.acquire_derived(sprite_policy, loader).ok());
    EXPECT_EQ(manager.snapshot().entries, baseline.entries);
    EXPECT_EQ(manager.snapshot().payload_bytes, baseline.payload_bytes);
    EXPECT_EQ(manager.snapshot().allocation_overhead_bytes,
              baseline.allocation_overhead_bytes);
  }
  faults->arm(cth3ds::AllocationPoint::DependencyEdge);
  auto sprite = manager.acquire_derived(sprite_policy, loader);
  EXPECT_TRUE(sprite.ok());
  cth3ds::DerivedAcquirePolicy texture_policy = sprite_policy;
  texture_policy.kind = cth3ds::DerivedResourceKind::Texture;
  EXPECT_FALSE(manager.acquire_derived(texture_policy, loader).ok());
  EXPECT_EQ(manager.snapshot().entries, 1U);
  EXPECT_EQ(manager.snapshot().dependents, 0U);
  EXPECT_TRUE(sprite.value().release().ok());
  manager.purge_zero_reference();
  EXPECT_EQ(manager.snapshot().entries, 0U);
}
