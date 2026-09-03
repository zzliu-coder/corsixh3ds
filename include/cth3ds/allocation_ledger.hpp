#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>

#include "cth3ds/memory_telemetry.hpp"

namespace cth3ds {

enum class AllocationBackend : std::uint8_t {
  Regular,
  Linear,
  Count,
};

enum class AllocationState : std::uint8_t {
  Reserved,
  Live,
  Freed,
};

enum class UsableQuality : std::uint8_t {
  ExactUsable,
  BackendRequestFallback,
};

enum class LedgerError : std::uint8_t {
  None,
  ZeroAllocation,
  AlignmentInvalid,
  ArithmeticOverflow,
  PoolInvalid,
  BackendInvalid,
  PoolBudgetExceeded,
  BackendAllocationFailed,
  AllocationUnknown,
  AllocationNotLive,
  PointerMismatch,
  BackendMismatch,
  TouchRangeInvalid,
  ReconciliationOverflow,
};

struct AllocationRequest {
  std::uint64_t requested_bytes{0U};
  std::uint64_t alignment_bytes{0U};
  ResourcePool pool{ResourcePool::Count};
  AllocationBackend backend{AllocationBackend::Count};
  std::uint64_t transaction_generation{0U};
};

struct AllocationRecord {
  std::uint64_t allocation_id{0U};
  std::uintptr_t pointer_identity{0U};
  AllocationState state{AllocationState::Reserved};
  ResourcePool pool{ResourcePool::Count};
  AllocationBackend backend{AllocationBackend::Count};
  std::uint64_t requested_bytes{0U};       // R
  std::uint64_t alignment_bytes{0U};       // A
  std::uint64_t aligned_payload_bytes{0U}; // P
  std::uint64_t backend_request_bytes{0U}; // B
  std::uint64_t usable_bytes{0U};          // U, only exact when quality says so
  UsableQuality usable_quality{UsableQuality::BackendRequestFallback};
  std::uint64_t budget_charge_bytes{0U};     // Q
  std::uint64_t backend_accounted_bytes{0U}; // T
  std::uint64_t transaction_generation{0U};
};

struct LedgerAllocation {
  std::uint64_t allocation_id{0U};
  void* pointer{nullptr};
  std::size_t requested_size{0U};

  [[nodiscard]] bool valid() const noexcept {
    return allocation_id != 0U && pointer != nullptr;
  }
};

template <typename T>
struct LedgerResult {
  T value{};
  LedgerError error{LedgerError::None};

  [[nodiscard]] bool ok() const noexcept { return error == LedgerError::None; }
  [[nodiscard]] explicit operator bool() const noexcept { return ok(); }
};

struct Reconciliation {
  std::int64_t regular_delta_bytes{0};
  std::int64_t linear_delta_bytes{0};
  std::uint64_t runtime_page_size{0U};
  std::uint64_t touched_page_bytes{0U};
  bool regular_measurement_available{false};
  bool linear_measurement_available{false};
  bool valid{true};
};

using BackendAllocate = void* (*)(std::uint64_t bytes,
                                  std::uint64_t alignment,
                                  void* context) noexcept;
using BackendUsable = std::uint64_t (*)(void* pointer,
                                        void* context) noexcept;
using BackendRelease = void (*)(void* pointer, void* context) noexcept;
using BackendMeasure = std::uint64_t (*)(void* context) noexcept;

enum class BackendMeasureKind : std::uint8_t {
  Unavailable,
  LiveBytes,
  FreeBytes,
};

struct AllocationBackendApi {
  BackendAllocate allocate{nullptr};
  BackendUsable usable{nullptr};
  BackendRelease release{nullptr};
  BackendMeasure measure{nullptr};
  BackendMeasureKind measure_kind{BackendMeasureKind::Unavailable};
  void* context{nullptr};
};

struct AllocationLedgerConfig {
  std::array<std::uint64_t, static_cast<std::size_t>(ResourcePool::Count)>
      pool_caps{};
  std::array<AllocationBackendApi,
             static_cast<std::size_t>(AllocationBackend::Count)>
      backends{};
  std::uint64_t runtime_page_size{0U};
};

struct AllocationLedgerSnapshot {
  std::array<std::uint64_t, static_cast<std::size_t>(ResourcePool::Count)>
      pool_budget_bytes{};
  std::array<std::uint64_t,
             static_cast<std::size_t>(AllocationBackend::Count)>
      backend_accounted_bytes{};
  std::uint64_t requested_bytes{0U};
  std::uint64_t aligned_payload_bytes{0U};
  std::uint64_t backend_request_bytes{0U};
  std::uint64_t usable_bytes{0U};
  std::uint64_t budget_charge_bytes{0U};
  std::uint64_t backend_accounted_total_bytes{0U};
  std::size_t reserved_records{0U};
  std::size_t live_records{0U};
  std::size_t freed_records{0U};
  Reconciliation reconciliation{};
};

[[nodiscard]] AllocationLedgerConfig default_allocation_ledger_config() noexcept;
[[nodiscard]] std::uint64_t runtime_page_size() noexcept;
[[nodiscard]] bool checked_align_up(std::uint64_t value,
                                    std::uint64_t alignment,
                                    std::uint64_t& result) noexcept;

class AllocationLedger {
 public:
  explicit AllocationLedger(
      AllocationLedgerConfig config = default_allocation_ledger_config());
  ~AllocationLedger();

  AllocationLedger(const AllocationLedger&) = delete;
  AllocationLedger& operator=(const AllocationLedger&) = delete;
  AllocationLedger(AllocationLedger&&) noexcept;
  AllocationLedger& operator=(AllocationLedger&&) noexcept;

  [[nodiscard]] LedgerResult<LedgerAllocation> allocate(
      const AllocationRequest& request) noexcept;
  [[nodiscard]] LedgerError release(
      std::uint64_t allocation_id, const void* expected_pointer,
      AllocationBackend expected_backend) noexcept;
  [[nodiscard]] LedgerResult<LedgerAllocation> reallocate(
      std::uint64_t allocation_id, const void* expected_pointer,
      std::uint64_t new_requested_bytes) noexcept;
  [[nodiscard]] LedgerError record_touch(std::uint64_t allocation_id,
                                         std::uint64_t offset,
                                         std::uint64_t bytes) noexcept;

  [[nodiscard]] std::optional<AllocationRecord> record(
      std::uint64_t allocation_id) const noexcept;
  [[nodiscard]] AllocationLedgerSnapshot snapshot() const noexcept;
  [[nodiscard]] Reconciliation reconcile(
      std::int64_t measured_regular_delta_bytes,
      std::int64_t measured_linear_delta_bytes) const noexcept;
  [[nodiscard]] std::uint64_t pool_live_bytes(ResourcePool pool) const noexcept;

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace cth3ds
