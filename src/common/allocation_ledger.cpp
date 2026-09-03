#include "cth3ds/allocation_ledger.hpp"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <map>
#include <mutex>
#include <set>
#include <utility>

#if defined(__3DS__)
#include <3ds.h>
#include <malloc.h>
#elif defined(__APPLE__)
#include <malloc/malloc.h>
#include <unistd.h>
#elif defined(__GLIBC__)
#include <malloc.h>
#include <unistd.h>
#else
#include <unistd.h>
#endif

namespace cth3ds {
namespace {

constexpr std::size_t pool_index(ResourcePool pool) noexcept {
  return static_cast<std::size_t>(pool);
}

constexpr std::size_t backend_index(AllocationBackend backend) noexcept {
  return static_cast<std::size_t>(backend);
}

bool valid_pool(ResourcePool pool) noexcept {
  return pool_index(pool) < pool_index(ResourcePool::Count);
}

bool valid_backend(AllocationBackend backend) noexcept {
  return backend_index(backend) < backend_index(AllocationBackend::Count);
}

bool valid_alignment(std::uint64_t alignment) noexcept {
  return (alignment == 64U || alignment == 4096U) &&
         (alignment & (alignment - 1U)) == 0U;
}

bool checked_add(std::uint64_t left, std::uint64_t right,
                 std::uint64_t& result) noexcept {
  if (right > std::numeric_limits<std::uint64_t>::max() - left) return false;
  result = left + right;
  return true;
}

bool checked_signed_delta(std::int64_t measured, std::uint64_t classified,
                          std::int64_t& result) noexcept {
  if (classified > static_cast<std::uint64_t>(
                       std::numeric_limits<std::int64_t>::max())) {
    return false;
  }
  const auto classified_signed = static_cast<std::int64_t>(classified);
  if (classified_signed > 0 &&
      measured < std::numeric_limits<std::int64_t>::min() + classified_signed) {
    return false;
  }
  result = measured - classified_signed;
  return true;
}

bool measurement_delta(std::uint64_t baseline, std::uint64_t current,
                       BackendMeasureKind kind, std::int64_t& result) noexcept {
  if (kind == BackendMeasureKind::Unavailable) return false;
  const bool positive = kind == BackendMeasureKind::LiveBytes
                            ? current >= baseline
                            : baseline >= current;
  const std::uint64_t magnitude = kind == BackendMeasureKind::LiveBytes
                                      ? (positive ? current - baseline
                                                  : baseline - current)
                                      : (positive ? baseline - current
                                                  : current - baseline);
  if (magnitude > static_cast<std::uint64_t>(
                      std::numeric_limits<std::int64_t>::max())) {
    return false;
  }
  const auto signed_magnitude = static_cast<std::int64_t>(magnitude);
  result = positive ? signed_magnitude : -signed_magnitude;
  return true;
}

void* regular_allocate(std::uint64_t bytes, std::uint64_t alignment,
                       void*) noexcept {
  if (bytes > static_cast<std::uint64_t>(
                  std::numeric_limits<std::size_t>::max()) ||
      alignment > static_cast<std::uint64_t>(
                      std::numeric_limits<std::size_t>::max())) {
    return nullptr;
  }
  void* pointer = nullptr;
#if defined(__3DS__)
  pointer = memalign(static_cast<std::size_t>(alignment),
                     static_cast<std::size_t>(bytes));
#else
  if (posix_memalign(&pointer, static_cast<std::size_t>(alignment),
                     static_cast<std::size_t>(bytes)) != 0) {
    return nullptr;
  }
#endif
  return pointer;
}

void regular_release(void* pointer, void*) noexcept { std::free(pointer); }

std::uint64_t regular_usable(void* pointer, void*) noexcept {
  if (pointer == nullptr) return 0U;
#if defined(__APPLE__)
  return static_cast<std::uint64_t>(malloc_size(pointer));
#elif defined(__GLIBC__) || defined(__3DS__)
  return static_cast<std::uint64_t>(malloc_usable_size(pointer));
#else
  return 0U;
#endif
}

std::uint64_t regular_measure(void*) noexcept {
#if defined(__APPLE__)
  malloc_statistics_t statistics{};
  malloc_zone_statistics(malloc_default_zone(), &statistics);
  return static_cast<std::uint64_t>(statistics.size_in_use);
#elif defined(__GLIBC__)
  const auto information = mallinfo2();
  const std::uint64_t allocated = static_cast<std::uint64_t>(information.uordblks);
  const std::uint64_t mapped = static_cast<std::uint64_t>(information.hblkhd);
  std::uint64_t total = 0U;
  return checked_add(allocated, mapped, total)
             ? total
             : std::numeric_limits<std::uint64_t>::max();
#elif defined(__3DS__)
  const auto information = mallinfo();
  return static_cast<std::uint64_t>(information.uordblks);
#else
  return 0U;
#endif
}

#if defined(__3DS__)
void* linear_allocate(std::uint64_t bytes, std::uint64_t alignment,
                      void*) noexcept {
  if (bytes > static_cast<std::uint64_t>(
                  std::numeric_limits<std::size_t>::max()) ||
      alignment > static_cast<std::uint64_t>(
                      std::numeric_limits<std::size_t>::max())) {
    return nullptr;
  }
  return linearMemAlign(static_cast<std::size_t>(bytes),
                        static_cast<std::size_t>(alignment));
}

void linear_release(void* pointer, void*) noexcept { linearFree(pointer); }

std::uint64_t linear_usable(void* pointer, void*) noexcept {
  return pointer == nullptr ? 0U
                            : static_cast<std::uint64_t>(linearGetSize(pointer));
}

std::uint64_t linear_measure(void*) noexcept {
  return static_cast<std::uint64_t>(linearSpaceFree());
}
#endif

}  // namespace

bool checked_align_up(std::uint64_t value, std::uint64_t alignment,
                      std::uint64_t& result) noexcept {
  if (alignment == 0U || (alignment & (alignment - 1U)) != 0U) return false;
  const std::uint64_t mask = alignment - 1U;
  if (value > std::numeric_limits<std::uint64_t>::max() - mask) return false;
  result = (value + mask) & ~mask;
  return true;
}

std::uint64_t runtime_page_size() noexcept {
#if defined(__3DS__)
  return 4096U;
#else
  const long observed = ::sysconf(_SC_PAGESIZE);
  return observed > 0 ? static_cast<std::uint64_t>(observed) : 4096U;
#endif
}

AllocationLedgerConfig default_allocation_ledger_config() noexcept {
  AllocationLedgerConfig config;
  for (std::size_t index = 0U; index < config.pool_caps.size(); ++index) {
    config.pool_caps[index] =
        resource_pool_limit(static_cast<ResourcePool>(index));
  }
  config.runtime_page_size = runtime_page_size();
  config.backends[backend_index(AllocationBackend::Regular)] = {
      regular_allocate,
      regular_usable,
      regular_release,
      regular_measure,
#if defined(__APPLE__) || defined(__GLIBC__) || defined(__3DS__)
      BackendMeasureKind::LiveBytes,
#else
      BackendMeasureKind::Unavailable,
#endif
      nullptr,
  };
#if defined(__3DS__)
  config.backends[backend_index(AllocationBackend::Linear)] = {
      linear_allocate, linear_usable, linear_release, linear_measure,
      BackendMeasureKind::FreeBytes, nullptr};
#endif
  return config;
}

class AllocationLedger::Impl {
 public:
  explicit Impl(AllocationLedgerConfig ledger_config)
      : config(std::move(ledger_config)) {
    if (config.runtime_page_size == 0U ||
        (config.runtime_page_size & (config.runtime_page_size - 1U)) != 0U) {
      config.runtime_page_size = runtime_page_size();
    }
    for (std::size_t index = 0U; index < config.backends.size(); ++index) {
      const auto& api = config.backends[index];
      if (api.measure != nullptr &&
          api.measure_kind != BackendMeasureKind::Unavailable) {
        measurement_baseline[index] = api.measure(api.context);
        measurement_available[index] = true;
      }
    }
  }

  ~Impl() {
    for (auto& item : records) {
      AllocationRecord& record = item.second;
      if (record.state != AllocationState::Live || record.pointer_identity == 0U ||
          !valid_backend(record.backend)) {
        continue;
      }
      const auto& api = config.backends[backend_index(record.backend)];
      if (api.release != nullptr) {
        api.release(reinterpret_cast<void*>(record.pointer_identity), api.context);
      }
      record.state = AllocationState::Freed;
    }
  }

  AllocationLedgerConfig config{};
  mutable std::recursive_mutex mutex{};
  std::map<std::uint64_t, AllocationRecord> records{};
  std::map<std::uint64_t, std::set<std::uintptr_t>> touched_pages{};
  std::array<std::uint64_t, static_cast<std::size_t>(ResourcePool::Count)>
      pool_live{};
  std::array<std::uint64_t,
             static_cast<std::size_t>(AllocationBackend::Count)>
      backend_live{};
  std::array<std::uint64_t,
             static_cast<std::size_t>(AllocationBackend::Count)>
      measurement_baseline{};
  std::array<bool, static_cast<std::size_t>(AllocationBackend::Count)>
      measurement_available{};
  std::uint64_t next_allocation_id{0U};
};

AllocationLedger::AllocationLedger(AllocationLedgerConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

AllocationLedger::~AllocationLedger() = default;
AllocationLedger::AllocationLedger(AllocationLedger&&) noexcept = default;
AllocationLedger& AllocationLedger::operator=(AllocationLedger&&) noexcept = default;

LedgerResult<LedgerAllocation> AllocationLedger::allocate(
    const AllocationRequest& request) noexcept {
  LedgerResult<LedgerAllocation> result;
  if (impl_ == nullptr) {
    result.error = LedgerError::BackendAllocationFailed;
    return result;
  }
  std::lock_guard<std::recursive_mutex> lock(impl_->mutex);
  if (request.requested_bytes == 0U) {
    result.error = LedgerError::ZeroAllocation;
    return result;
  }
  if (!valid_alignment(request.alignment_bytes)) {
    result.error = LedgerError::AlignmentInvalid;
    return result;
  }
  if (!valid_pool(request.pool)) {
    result.error = LedgerError::PoolInvalid;
    return result;
  }
  if (!valid_backend(request.backend)) {
    result.error = LedgerError::BackendInvalid;
    return result;
  }
  const auto& api = impl_->config.backends[backend_index(request.backend)];
  if (api.allocate == nullptr || api.release == nullptr) {
    result.error = LedgerError::BackendAllocationFailed;
    return result;
  }
  std::uint64_t aligned = 0U;
  if (!checked_align_up(request.requested_bytes, request.alignment_bytes,
                        aligned) ||
      aligned > static_cast<std::uint64_t>(
                    std::numeric_limits<std::size_t>::max())) {
    result.error = LedgerError::ArithmeticOverflow;
    return result;
  }
  const std::size_t pool = pool_index(request.pool);
  if (!allocation_fits_pool_budget(impl_->pool_live[pool], aligned,
                                   impl_->config.pool_caps[pool])) {
    result.error = LedgerError::PoolBudgetExceeded;
    return result;
  }
  if (impl_->next_allocation_id == std::numeric_limits<std::uint64_t>::max()) {
    result.error = LedgerError::ArithmeticOverflow;
    return result;
  }
  const std::uint64_t allocation_id = ++impl_->next_allocation_id;
  AllocationRecord record;
  record.allocation_id = allocation_id;
  record.state = AllocationState::Reserved;
  record.pool = request.pool;
  record.backend = request.backend;
  record.requested_bytes = request.requested_bytes;
  record.alignment_bytes = request.alignment_bytes;
  record.aligned_payload_bytes = aligned;
  record.backend_request_bytes = aligned;
  record.budget_charge_bytes = aligned;
  record.transaction_generation = request.transaction_generation;
  try {
    impl_->records.emplace(allocation_id, record);
  } catch (...) {
    result.error = LedgerError::BackendAllocationFailed;
    return result;
  }
  impl_->pool_live[pool] += aligned;
  void* pointer = api.allocate(aligned, request.alignment_bytes, api.context);
  if (pointer == nullptr) {
    impl_->pool_live[pool] -= aligned;
    impl_->records.erase(allocation_id);
    result.error = LedgerError::BackendAllocationFailed;
    return result;
  }
  const std::uint64_t usable = api.usable == nullptr ? 0U
                                                      : api.usable(pointer, api.context);
  const std::uint64_t accounted = usable == 0U ? aligned : usable;
  const std::size_t backend = backend_index(request.backend);
  std::uint64_t backend_after = 0U;
  if (!checked_add(impl_->backend_live[backend], accounted, backend_after)) {
    api.release(pointer, api.context);
    impl_->pool_live[pool] -= aligned;
    impl_->records.erase(allocation_id);
    result.error = LedgerError::ArithmeticOverflow;
    return result;
  }
  AllocationRecord& published = impl_->records.find(allocation_id)->second;
  published.pointer_identity = reinterpret_cast<std::uintptr_t>(pointer);
  published.usable_bytes = usable;
  published.usable_quality = usable == 0U
                                 ? UsableQuality::BackendRequestFallback
                                 : UsableQuality::ExactUsable;
  published.backend_accounted_bytes = accounted;
  published.state = AllocationState::Live;
  impl_->backend_live[backend] = backend_after;
  result.value = {allocation_id, pointer,
                  static_cast<std::size_t>(request.requested_bytes)};
  return result;
}

LedgerError AllocationLedger::release(
    std::uint64_t allocation_id, const void* expected_pointer,
    AllocationBackend expected_backend) noexcept {
  if (impl_ == nullptr) return LedgerError::AllocationUnknown;
  std::lock_guard<std::recursive_mutex> lock(impl_->mutex);
  const auto iterator = impl_->records.find(allocation_id);
  if (iterator == impl_->records.end()) return LedgerError::AllocationUnknown;
  AllocationRecord& record = iterator->second;
  if (record.state != AllocationState::Live) return LedgerError::AllocationNotLive;
  if (record.pointer_identity != reinterpret_cast<std::uintptr_t>(expected_pointer)) {
    return LedgerError::PointerMismatch;
  }
  if (record.backend != expected_backend) return LedgerError::BackendMismatch;
  const auto& api = impl_->config.backends[backend_index(record.backend)];
  if (api.release == nullptr) return LedgerError::BackendAllocationFailed;
  if (impl_->pool_live[pool_index(record.pool)] < record.budget_charge_bytes ||
      impl_->backend_live[backend_index(record.backend)] <
          record.backend_accounted_bytes) {
    return LedgerError::ArithmeticOverflow;
  }
  api.release(reinterpret_cast<void*>(record.pointer_identity), api.context);
  impl_->pool_live[pool_index(record.pool)] -= record.budget_charge_bytes;
  impl_->backend_live[backend_index(record.backend)] -=
      record.backend_accounted_bytes;
  record.state = AllocationState::Freed;
  impl_->touched_pages.erase(record.allocation_id);
  return LedgerError::None;
}

LedgerResult<LedgerAllocation> AllocationLedger::reallocate(
    std::uint64_t allocation_id, const void* expected_pointer,
    std::uint64_t new_requested_bytes) noexcept {
  LedgerResult<LedgerAllocation> result;
  if (impl_ == nullptr) {
    result.error = LedgerError::AllocationUnknown;
    return result;
  }
  std::lock_guard<std::recursive_mutex> lock(impl_->mutex);
  const auto iterator = impl_->records.find(allocation_id);
  if (iterator == impl_->records.end()) {
    result.error = LedgerError::AllocationUnknown;
    return result;
  }
  const AllocationRecord old = iterator->second;
  if (old.state != AllocationState::Live) {
    result.error = LedgerError::AllocationNotLive;
    return result;
  }
  if (old.pointer_identity != reinterpret_cast<std::uintptr_t>(expected_pointer)) {
    result.error = LedgerError::PointerMismatch;
    return result;
  }
  if (new_requested_bytes == 0U) {
    result.error = release(allocation_id, expected_pointer, old.backend);
    return result;
  }
  const AllocationRequest request{new_requested_bytes, old.alignment_bytes,
                                  old.pool, old.backend,
                                  old.transaction_generation};
  auto replacement = allocate(request);
  if (!replacement) return replacement;
  std::memcpy(replacement.value.pointer, expected_pointer,
              std::min<std::size_t>(
                  static_cast<std::size_t>(old.requested_bytes),
                  replacement.value.requested_size));
  const LedgerError released = release(allocation_id, expected_pointer, old.backend);
  if (released != LedgerError::None) {
    (void)release(replacement.value.allocation_id, replacement.value.pointer,
                  old.backend);
    result.error = released;
    return result;
  }
  return replacement;
}

LedgerError AllocationLedger::record_touch(std::uint64_t allocation_id,
                                            std::uint64_t offset,
                                            std::uint64_t bytes) noexcept {
  if (impl_ == nullptr) return LedgerError::AllocationUnknown;
  std::lock_guard<std::recursive_mutex> lock(impl_->mutex);
  const auto iterator = impl_->records.find(allocation_id);
  if (iterator == impl_->records.end()) return LedgerError::AllocationUnknown;
  const AllocationRecord& record = iterator->second;
  if (record.state != AllocationState::Live) return LedgerError::AllocationNotLive;
  if (bytes == 0U) return LedgerError::None;
  if (offset > record.requested_bytes || bytes > record.requested_bytes - offset) {
    return LedgerError::TouchRangeInvalid;
  }
  if (record.pointer_identity > std::numeric_limits<std::uintptr_t>::max() - offset) {
    return LedgerError::TouchRangeInvalid;
  }
  const std::uintptr_t first_address =
      record.pointer_identity + static_cast<std::uintptr_t>(offset);
  if (bytes - 1U > std::numeric_limits<std::uintptr_t>::max() - first_address) {
    return LedgerError::TouchRangeInvalid;
  }
  const std::uintptr_t last_address =
      first_address + static_cast<std::uintptr_t>(bytes - 1U);
  const std::uintptr_t page_size =
      static_cast<std::uintptr_t>(impl_->config.runtime_page_size);
  const std::uintptr_t first_page = first_address / page_size;
  const std::uintptr_t last_page = last_address / page_size;
  try {
    auto& pages = impl_->touched_pages[allocation_id];
    for (std::uintptr_t page = first_page;; ++page) {
      pages.insert(page);
      if (page == last_page) break;
      if (page == std::numeric_limits<std::uintptr_t>::max()) {
        return LedgerError::TouchRangeInvalid;
      }
    }
  } catch (...) {
    return LedgerError::BackendAllocationFailed;
  }
  return LedgerError::None;
}

std::optional<AllocationRecord> AllocationLedger::record(
    std::uint64_t allocation_id) const noexcept {
  if (impl_ == nullptr) return std::nullopt;
  std::lock_guard<std::recursive_mutex> lock(impl_->mutex);
  const auto iterator = impl_->records.find(allocation_id);
  return iterator == impl_->records.end()
             ? std::optional<AllocationRecord>{}
             : std::optional<AllocationRecord>{iterator->second};
}

Reconciliation AllocationLedger::reconcile(
    std::int64_t measured_regular_delta_bytes,
    std::int64_t measured_linear_delta_bytes) const noexcept {
  Reconciliation result;
  result.runtime_page_size = impl_ == nullptr ? 0U : impl_->config.runtime_page_size;
  result.regular_measurement_available = true;
  result.linear_measurement_available = true;
  if (impl_ == nullptr) {
    result.valid = false;
    return result;
  }
  std::lock_guard<std::recursive_mutex> lock(impl_->mutex);
  result.valid = checked_signed_delta(
      measured_regular_delta_bytes,
      impl_->backend_live[backend_index(AllocationBackend::Regular)],
      result.regular_delta_bytes);
  result.valid = checked_signed_delta(
                     measured_linear_delta_bytes,
                     impl_->backend_live[backend_index(AllocationBackend::Linear)],
                     result.linear_delta_bytes) &&
                 result.valid;
  std::set<std::uintptr_t> union_pages;
  try {
    for (const auto& item : impl_->touched_pages) {
      const auto record_iterator = impl_->records.find(item.first);
      if (record_iterator == impl_->records.end() ||
          record_iterator->second.state != AllocationState::Live) {
        continue;
      }
      union_pages.insert(item.second.begin(), item.second.end());
    }
  } catch (...) {
    result.valid = false;
    return result;
  }
  const std::uint64_t page_count = static_cast<std::uint64_t>(union_pages.size());
  if (impl_->config.runtime_page_size != 0U &&
      page_count > std::numeric_limits<std::uint64_t>::max() /
                       impl_->config.runtime_page_size) {
    result.valid = false;
    return result;
  }
  result.touched_page_bytes = page_count * impl_->config.runtime_page_size;
  return result;
}

AllocationLedgerSnapshot AllocationLedger::snapshot() const noexcept {
  AllocationLedgerSnapshot result;
  if (impl_ == nullptr) {
    result.reconciliation.valid = false;
    return result;
  }
  std::lock_guard<std::recursive_mutex> lock(impl_->mutex);
  result.pool_budget_bytes = impl_->pool_live;
  result.backend_accounted_bytes = impl_->backend_live;
  bool totals_valid = true;
  for (const auto& item : impl_->records) {
    const AllocationRecord& record = item.second;
    if (record.state == AllocationState::Reserved) {
      ++result.reserved_records;
      continue;
    }
    if (record.state == AllocationState::Freed) {
      ++result.freed_records;
      continue;
    }
    ++result.live_records;
    totals_valid = checked_add(result.requested_bytes, record.requested_bytes,
                               result.requested_bytes) && totals_valid;
    totals_valid = checked_add(result.aligned_payload_bytes,
                               record.aligned_payload_bytes,
                               result.aligned_payload_bytes) && totals_valid;
    totals_valid = checked_add(result.backend_request_bytes,
                               record.backend_request_bytes,
                               result.backend_request_bytes) && totals_valid;
    totals_valid = checked_add(result.usable_bytes, record.usable_bytes,
                               result.usable_bytes) && totals_valid;
    totals_valid = checked_add(result.budget_charge_bytes,
                               record.budget_charge_bytes,
                               result.budget_charge_bytes) && totals_valid;
    totals_valid = checked_add(result.backend_accounted_total_bytes,
                               record.backend_accounted_bytes,
                               result.backend_accounted_total_bytes) && totals_valid;
  }

  std::array<std::int64_t, static_cast<std::size_t>(AllocationBackend::Count)>
      measured{};
  std::array<bool, static_cast<std::size_t>(AllocationBackend::Count)> available{};
  for (std::size_t index = 0U; index < impl_->config.backends.size(); ++index) {
    const auto& api = impl_->config.backends[index];
    if (!impl_->measurement_available[index] || api.measure == nullptr) continue;
    available[index] = measurement_delta(
        impl_->measurement_baseline[index], api.measure(api.context),
        api.measure_kind, measured[index]);
  }
  result.reconciliation = reconcile(measured[backend_index(AllocationBackend::Regular)],
                                    measured[backend_index(AllocationBackend::Linear)]);
  result.reconciliation.regular_measurement_available =
      available[backend_index(AllocationBackend::Regular)];
  result.reconciliation.linear_measurement_available =
      available[backend_index(AllocationBackend::Linear)];
  if (!available[backend_index(AllocationBackend::Regular)] &&
      impl_->backend_live[backend_index(AllocationBackend::Regular)] != 0U) {
    result.reconciliation.valid = false;
  }
  if (!available[backend_index(AllocationBackend::Linear)] &&
      impl_->backend_live[backend_index(AllocationBackend::Linear)] != 0U) {
    result.reconciliation.valid = false;
  }
  result.reconciliation.valid = result.reconciliation.valid && totals_valid;
  return result;
}

std::uint64_t AllocationLedger::pool_live_bytes(ResourcePool pool) const noexcept {
  if (impl_ == nullptr || !valid_pool(pool)) return 0U;
  std::lock_guard<std::recursive_mutex> lock(impl_->mutex);
  return impl_->pool_live[pool_index(pool)];
}

}  // namespace cth3ds
