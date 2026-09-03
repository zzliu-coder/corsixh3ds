#include "test_framework.hpp"

#include <array>
#include <cstdlib>
#include <cstring>
#include <limits>

#include "cth3ds/allocation_ledger.hpp"

namespace {

struct FakeBackend {
  std::uint64_t usable_override{0U};
  std::uint64_t last_request{0U};
  std::size_t allocate_calls{0U};
  std::size_t release_calls{0U};
  bool fail_next{false};
};

void* fake_allocate(std::uint64_t bytes, std::uint64_t alignment,
                    void* opaque) noexcept {
  auto& backend = *static_cast<FakeBackend*>(opaque);
  ++backend.allocate_calls;
  backend.last_request = bytes;
  if (backend.fail_next) {
    backend.fail_next = false;
    return nullptr;
  }
  void* pointer = nullptr;
  if (posix_memalign(&pointer, static_cast<std::size_t>(alignment),
                     static_cast<std::size_t>(bytes)) != 0) {
    return nullptr;
  }
  return pointer;
}

std::uint64_t fake_usable(void*, void* opaque) noexcept {
  const auto& backend = *static_cast<FakeBackend*>(opaque);
  return backend.usable_override == 0U ? backend.last_request
                                       : backend.usable_override;
}

void fake_release(void* pointer, void* opaque) noexcept {
  auto& backend = *static_cast<FakeBackend*>(opaque);
  ++backend.release_calls;
  std::free(pointer);
}

cth3ds::AllocationLedgerConfig fake_config(FakeBackend& regular,
                                            FakeBackend& linear,
                                            std::uint64_t cap = 16U * 1024U * 1024U,
                                            std::uint64_t page_size = 4096U) {
  cth3ds::AllocationLedgerConfig config;
  config.pool_caps.fill(cap);
  config.runtime_page_size = page_size;
  config.backends[static_cast<std::size_t>(
      cth3ds::AllocationBackend::Regular)] = {
      fake_allocate, fake_usable, fake_release, nullptr,
      cth3ds::BackendMeasureKind::Unavailable, &regular};
  config.backends[static_cast<std::size_t>(
      cth3ds::AllocationBackend::Linear)] = {
      fake_allocate, fake_usable, fake_release, nullptr,
      cth3ds::BackendMeasureKind::Unavailable, &linear};
  return config;
}

cth3ds::AllocationRequest request(
    std::uint64_t bytes, cth3ds::ResourcePool pool = cth3ds::ResourcePool::Texture,
    cth3ds::AllocationBackend backend = cth3ds::AllocationBackend::Regular,
    std::uint64_t alignment = 64U) {
  return {bytes, alignment, pool, backend, 7U};
}

std::size_t pool(cth3ds::ResourcePool value) {
  return static_cast<std::size_t>(value);
}

std::size_t backend(cth3ds::AllocationBackend value) {
  return static_cast<std::size_t>(value);
}

struct AddressBackend {
  std::array<std::uintptr_t, 2U> addresses{{0x1003U, 0x2FF0U}};
  std::size_t next{0U};
};

void* address_allocate(std::uint64_t, std::uint64_t, void* opaque) noexcept {
  auto& backend = *static_cast<AddressBackend*>(opaque);
  if (backend.next >= backend.addresses.size()) return nullptr;
  return reinterpret_cast<void*>(backend.addresses[backend.next++]);
}

void address_release(void*, void*) noexcept {}

cth3ds::AllocationLedgerConfig address_config(AddressBackend& address_backend,
                                               std::uint64_t page_size) {
  FakeBackend unused;
  auto config = fake_config(unused, unused, 1U * 1024U * 1024U, page_size);
  config.backends[backend(cth3ds::AllocationBackend::Regular)] = {
      address_allocate, nullptr, address_release, nullptr,
      cth3ds::BackendMeasureKind::Unavailable, &address_backend};
  config.backends[backend(cth3ds::AllocationBackend::Linear)] = {};
  return config;
}

}  // namespace

TEST(A01_fields_are_distinct_and_usable_can_exceed_aligned) {
  FakeBackend regular;
  FakeBackend linear;
  regular.usable_override = 192U;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  const auto allocated = ledger.allocate(request(65U));
  EXPECT_TRUE(allocated.ok());
  const auto record = ledger.record(allocated.value.allocation_id);
  EXPECT_TRUE(record.has_value());
  EXPECT_EQ(record->requested_bytes, std::uint64_t{65U});
  EXPECT_EQ(record->aligned_payload_bytes, std::uint64_t{128U});
  EXPECT_EQ(record->backend_request_bytes, std::uint64_t{128U});
  EXPECT_EQ(record->usable_bytes, std::uint64_t{192U});
  EXPECT_EQ(record->budget_charge_bytes, std::uint64_t{128U});
  EXPECT_EQ(record->backend_accounted_bytes, std::uint64_t{192U});
  EXPECT_EQ(record->usable_quality, cth3ds::UsableQuality::ExactUsable);
}

TEST(A02_ui_bitmap_153600_usable_163840_succeeds) {
  FakeBackend regular;
  FakeBackend linear;
  regular.usable_override = 163840U;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  const auto allocated = ledger.allocate(request(153600U));
  EXPECT_TRUE(allocated.ok());
  const auto record = ledger.record(allocated.value.allocation_id);
  EXPECT_TRUE(record.has_value());
  EXPECT_EQ(record->aligned_payload_bytes, std::uint64_t{153600U});
  EXPECT_EQ(record->budget_charge_bytes, std::uint64_t{153600U});
  EXPECT_EQ(record->usable_bytes, std::uint64_t{163840U});
  EXPECT_EQ(record->backend_accounted_bytes, std::uint64_t{163840U});
}

TEST(A03_pool_cap_uses_Q_boundary) {
  FakeBackend regular;
  FakeBackend linear;
  regular.usable_override = 4096U;
  auto config = fake_config(regular, linear, 192U);
  cth3ds::AllocationLedger ledger(std::move(config));
  const auto first = ledger.allocate(request(65U));
  EXPECT_TRUE(first.ok());
  const auto exact = ledger.allocate(request(64U));
  EXPECT_TRUE(exact.ok());
  const auto over = ledger.allocate(request(1U));
  EXPECT_FALSE(over.ok());
  EXPECT_EQ(over.error, cth3ds::LedgerError::PoolBudgetExceeded);
  EXPECT_EQ(ledger.snapshot().pool_budget_bytes[pool(
                cth3ds::ResourcePool::Texture)], std::uint64_t{192U});
}

TEST(A04_regular_linear_no_double_count) {
  FakeBackend regular;
  FakeBackend linear;
  regular.usable_override = 96U;
  linear.usable_override = 160U;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  EXPECT_TRUE(ledger.allocate(request(64U)).ok());
  EXPECT_TRUE(ledger.allocate(request(65U, cth3ds::ResourcePool::Sprite,
                                      cth3ds::AllocationBackend::Linear)).ok());
  const auto snapshot = ledger.snapshot();
  EXPECT_EQ(snapshot.backend_accounted_bytes[backend(
                cth3ds::AllocationBackend::Regular)], std::uint64_t{96U});
  EXPECT_EQ(snapshot.backend_accounted_bytes[backend(
                cth3ds::AllocationBackend::Linear)], std::uint64_t{160U});
  EXPECT_EQ(snapshot.backend_accounted_total_bytes, std::uint64_t{256U});
}

TEST(A05_alignment_and_overflow_fail_closed) {
  FakeBackend regular;
  FakeBackend linear;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  EXPECT_EQ(ledger.allocate(request(1U, cth3ds::ResourcePool::Texture,
                                    cth3ds::AllocationBackend::Regular, 0U)).error,
            cth3ds::LedgerError::AlignmentInvalid);
  EXPECT_EQ(ledger.allocate(request(1U, cth3ds::ResourcePool::Texture,
                                    cth3ds::AllocationBackend::Regular, 96U)).error,
            cth3ds::LedgerError::AlignmentInvalid);
  EXPECT_EQ(ledger.allocate(request(1U, cth3ds::ResourcePool::Texture,
                                    cth3ds::AllocationBackend::Regular, 128U)).error,
            cth3ds::LedgerError::AlignmentInvalid);
  EXPECT_EQ(ledger.allocate(request(1U, cth3ds::ResourcePool::Count)).error,
            cth3ds::LedgerError::PoolInvalid);
  EXPECT_EQ(ledger.allocate(request(1U, cth3ds::ResourcePool::Texture,
                                    cth3ds::AllocationBackend::Count)).error,
            cth3ds::LedgerError::BackendInvalid);
  EXPECT_EQ(ledger.allocate(request(
                std::numeric_limits<std::uint64_t>::max())).error,
            cth3ds::LedgerError::ArithmeticOverflow);
  EXPECT_EQ(ledger.snapshot().live_records, std::size_t{0U});
  EXPECT_EQ(regular.allocate_calls, std::size_t{0U});
}

TEST(A06_zero_size_no_backend_call) {
  FakeBackend regular;
  FakeBackend linear;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  const auto result = ledger.allocate(request(0U));
  EXPECT_FALSE(result.ok());
  EXPECT_EQ(result.error, cth3ds::LedgerError::ZeroAllocation);
  EXPECT_EQ(regular.allocate_calls, std::size_t{0U});
  EXPECT_EQ(ledger.snapshot().live_records, std::size_t{0U});
}

TEST(A07_backend_failure_atomic_rollback) {
  FakeBackend regular;
  FakeBackend linear;
  regular.fail_next = true;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  const auto before = ledger.snapshot();
  const auto failed = ledger.allocate(request(64U));
  EXPECT_EQ(failed.error, cth3ds::LedgerError::BackendAllocationFailed);
  const auto after = ledger.snapshot();
  EXPECT_EQ(after.pool_budget_bytes, before.pool_budget_bytes);
  EXPECT_EQ(after.backend_accounted_bytes, before.backend_accounted_bytes);
  EXPECT_EQ(after.live_records, before.live_records);
  EXPECT_EQ(after.reserved_records, before.reserved_records);
  const auto success = ledger.allocate(request(64U));
  EXPECT_TRUE(success.ok());
  EXPECT_EQ(success.value.allocation_id, std::uint64_t{2U});
}

TEST(A08_exact_free_double_foreign_mismatch) {
  FakeBackend regular;
  FakeBackend linear;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  const auto allocated = ledger.allocate(request(64U));
  EXPECT_TRUE(allocated.ok());
  const auto live = ledger.snapshot();
  EXPECT_EQ(ledger.release(999U, allocated.value.pointer,
                           cth3ds::AllocationBackend::Regular),
            cth3ds::LedgerError::AllocationUnknown);
  EXPECT_EQ(ledger.release(allocated.value.allocation_id,
                           reinterpret_cast<void*>(0x1234U),
                           cth3ds::AllocationBackend::Regular),
            cth3ds::LedgerError::PointerMismatch);
  EXPECT_EQ(ledger.release(allocated.value.allocation_id, allocated.value.pointer,
                           cth3ds::AllocationBackend::Linear),
            cth3ds::LedgerError::BackendMismatch);
  EXPECT_EQ(ledger.snapshot().pool_budget_bytes, live.pool_budget_bytes);
  EXPECT_EQ(ledger.release(allocated.value.allocation_id, allocated.value.pointer,
                           cth3ds::AllocationBackend::Regular),
            cth3ds::LedgerError::None);
  EXPECT_EQ(ledger.release(allocated.value.allocation_id, allocated.value.pointer,
                           cth3ds::AllocationBackend::Regular),
            cth3ds::LedgerError::AllocationNotLive);
}

TEST(A09_realloc_grow_shrink_and_failure_preserves_old) {
  FakeBackend regular;
  FakeBackend linear;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  auto allocation = ledger.allocate(request(64U));
  EXPECT_TRUE(allocation.ok());
  std::memset(allocation.value.pointer, 0x5AU, allocation.value.requested_size);
  regular.fail_next = true;
  const auto failed = ledger.reallocate(allocation.value.allocation_id,
                                        allocation.value.pointer, 128U);
  EXPECT_FALSE(failed.ok());
  EXPECT_EQ(static_cast<const std::uint8_t*>(allocation.value.pointer)[0],
            std::uint8_t{0x5AU});
  EXPECT_EQ(ledger.record(allocation.value.allocation_id)->state,
            cth3ds::AllocationState::Live);
  auto grown = ledger.reallocate(allocation.value.allocation_id,
                                 allocation.value.pointer, 128U);
  EXPECT_TRUE(grown.ok());
  EXPECT_EQ(static_cast<const std::uint8_t*>(grown.value.pointer)[63],
            std::uint8_t{0x5AU});
  auto shrunk = ledger.reallocate(grown.value.allocation_id,
                                  grown.value.pointer, 32U);
  EXPECT_TRUE(shrunk.ok());
  EXPECT_EQ(static_cast<const std::uint8_t*>(shrunk.value.pointer)[31],
            std::uint8_t{0x5AU});
  const auto empty = ledger.reallocate(shrunk.value.allocation_id,
                                       shrunk.value.pointer, 0U);
  EXPECT_TRUE(empty.ok());
  EXPECT_FALSE(empty.value.valid());
}

TEST(A10_linear_uses_allocate_copy_free) {
  FakeBackend regular;
  FakeBackend linear;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  auto allocation = ledger.allocate(request(
      64U, cth3ds::ResourcePool::Texture, cth3ds::AllocationBackend::Linear));
  EXPECT_TRUE(allocation.ok());
  std::memset(allocation.value.pointer, 0xA5U, allocation.value.requested_size);
  const auto grown = ledger.reallocate(allocation.value.allocation_id,
                                       allocation.value.pointer, 128U);
  EXPECT_TRUE(grown.ok());
  EXPECT_EQ(linear.allocate_calls, std::size_t{2U});
  EXPECT_EQ(linear.release_calls, std::size_t{1U});
  EXPECT_EQ(static_cast<const std::uint8_t*>(grown.value.pointer)[0],
            std::uint8_t{0xA5U});
}

TEST(A11_runtime_page_size_union_4096_16384) {
  for (const auto page_size : {std::uint64_t{4096U}, std::uint64_t{16384U}}) {
    AddressBackend addresses;
    cth3ds::AllocationLedger ledger(address_config(addresses, page_size));
    const auto first = ledger.allocate(request(8192U));
    const auto second = ledger.allocate(request(32U));
    EXPECT_TRUE(first.ok());
    EXPECT_TRUE(second.ok());
    const auto before = ledger.snapshot();
    EXPECT_EQ(ledger.record_touch(first.value.allocation_id, 0U, 8192U),
              cth3ds::LedgerError::None);
    EXPECT_EQ(ledger.record_touch(second.value.allocation_id, 0U, 32U),
              cth3ds::LedgerError::None);
    const auto after = ledger.snapshot();
    EXPECT_EQ(after.pool_budget_bytes, before.pool_budget_bytes);
    EXPECT_EQ(after.backend_accounted_bytes, before.backend_accounted_bytes);
    EXPECT_EQ(after.reconciliation.touched_page_bytes,
              page_size == 4096U ? std::uint64_t{12288U}
                                 : std::uint64_t{16384U});
  }
}

TEST(A12_signed_reconciliation_positive_zero_negative) {
  FakeBackend regular;
  FakeBackend linear;
  regular.usable_override = 128U;
  linear.usable_override = 256U;
  cth3ds::AllocationLedger ledger(fake_config(regular, linear));
  EXPECT_TRUE(ledger.allocate(request(64U)).ok());
  EXPECT_TRUE(ledger.allocate(request(64U, cth3ds::ResourcePool::Sprite,
                                      cth3ds::AllocationBackend::Linear)).ok());
  const auto positive_zero = ledger.reconcile(138, 256);
  EXPECT_TRUE(positive_zero.valid);
  EXPECT_EQ(positive_zero.regular_delta_bytes, std::int64_t{10});
  EXPECT_EQ(positive_zero.linear_delta_bytes, std::int64_t{0});
  const auto zero_negative = ledger.reconcile(128, 200);
  EXPECT_TRUE(zero_negative.valid);
  EXPECT_EQ(zero_negative.regular_delta_bytes, std::int64_t{0});
  EXPECT_EQ(zero_negative.linear_delta_bytes, std::int64_t{-56});
  const auto negative_positive = ledger.reconcile(100, 300);
  EXPECT_TRUE(negative_positive.valid);
  EXPECT_EQ(negative_positive.regular_delta_bytes, std::int64_t{-28});
  EXPECT_EQ(negative_positive.linear_delta_bytes, std::int64_t{44});
}
