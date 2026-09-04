#include "cth3ds/resource_manager.hpp"

#include <algorithm>
#include <limits>
#include <map>
#include <mutex>
#include <new>
#include <utility>

namespace cth3ds {
namespace {

ResourceError make_error(ResourceErrorCode code, std::string message,
                         ResourceId id = {}) {
  return {code, std::move(message), id};
}

ResourceErrorCode pool_error(ResourcePool pool) noexcept {
  switch (pool) {
    case ResourcePool::Audio: return ResourceErrorCode::BudgetAudio;
    case ResourcePool::Sprite: return ResourceErrorCode::BudgetSprite;
    case ResourcePool::Texture: return ResourceErrorCode::BudgetTexture;
    case ResourcePool::LanguageFont: return ResourceErrorCode::BudgetLanguageFont;
    case ResourcePool::Metadata: return ResourceErrorCode::BudgetMetadata;
    case ResourcePool::Scratch: return ResourceErrorCode::BudgetScratch;
    case ResourcePool::Unclassified:
    case ResourcePool::Count: return ResourceErrorCode::BudgetContract;
  }
  return ResourceErrorCode::BudgetContract;
}

constexpr std::array<ResourcePool, 4> kEvictionOrder{{
    ResourcePool::Texture,
    ResourcePool::Sprite,
    ResourcePool::Audio,
    ResourcePool::Metadata,
}};

std::uint64_t pin_bit(PinOwner owner) noexcept {
  return std::uint64_t{1U} << static_cast<std::uint8_t>(owner);
}

std::size_t count_bits(std::uint64_t value) noexcept {
  std::size_t count = 0U;
  while (value != 0U) {
    value &= value - 1U;
    ++count;
  }
  return count;
}

ResourceErrorCode ledger_error_code(LedgerError error, ResourcePool pool) noexcept {
  if (error == LedgerError::PoolBudgetExceeded) return pool_error(pool);
  if (error == LedgerError::BackendAllocationFailed) {
    return ResourceErrorCode::AllocationFailed;
  }
  if (error == LedgerError::ArithmeticOverflow) {
    return ResourceErrorCode::AccountingOverrun;
  }
  return ResourceErrorCode::BudgetContract;
}

void publish_record(AllocationPlan& plan, const AllocationRecord& record) noexcept {
  plan.requested_bytes = record.requested_bytes;
  plan.alignment_bytes = record.alignment_bytes;
  plan.aligned_payload_bytes = record.aligned_payload_bytes;
  plan.backend_request_bytes = record.backend_request_bytes;
  plan.usable_bytes = record.usable_bytes;
  plan.usable_quality = record.usable_quality;
  plan.budget_charge_bytes = record.budget_charge_bytes;
  plan.backend_accounted_bytes = record.backend_accounted_bytes;
}

class LedgerAllocationGuard {
 public:
  LedgerAllocationGuard(AllocationLedger& ledger, LedgerAllocation allocation,
                        AllocationBackend backend) noexcept
      : ledger_(&ledger), allocation_(allocation), backend_(backend) {}
  LedgerAllocationGuard(const LedgerAllocationGuard&) = delete;
  LedgerAllocationGuard& operator=(const LedgerAllocationGuard&) = delete;
  ~LedgerAllocationGuard() {
    if (ledger_ != nullptr && allocation_.valid()) {
      (void)ledger_->release(allocation_.allocation_id, allocation_.pointer,
                             backend_);
    }
  }
  void release_ownership() noexcept { ledger_ = nullptr; }

 private:
  AllocationLedger* ledger_;
  LedgerAllocation allocation_;
  AllocationBackend backend_;
};

}  // namespace

class ResourceManagerState {
 public:
  struct Entry {
    const ResourceDescriptor* descriptor{nullptr};
    ResourcePool pool{ResourcePool::Metadata};
    LedgerAllocation allocation{};
    AllocationPlan plan{};
    std::uint64_t bytes{0U};
    std::uint64_t last_release_tick{0U};
    std::uint32_t refcount{0U};
    std::uint32_t dependent_count{0U};
    std::uint32_t group_id{0U};
    std::uint64_t transaction_id{0U};
    std::uint64_t pin_owners{0U};
    bool replacement_texture{false};
    std::optional<ResourceId> dependency{};
  };

  ResourceManagerState(std::shared_ptr<const MountedBundle> mounted,
                       std::shared_ptr<ResourceTelemetrySink> sink,
                       std::shared_ptr<ResourceBudgetGate> gate,
                       std::shared_ptr<ResourceFaultInjector> faults)
      : bundle(std::move(mounted)), telemetry(std::move(sink)),
        budget_gate(std::move(gate)), fault_injector(std::move(faults)) {
    const AllocationRequest scratch_request{
        resource_pool_limit(ResourcePool::Scratch), 64U,
        ResourcePool::Scratch, AllocationBackend::Regular, 0U};
    auto allocated = ledger.allocate(scratch_request);
    if (allocated) scratch_arena = allocated.value;
    if (telemetry != nullptr) {
      telemetry->pool_changed(ResourcePool::Metadata, 0U, {});
      telemetry->pool_changed(
          ResourcePool::Scratch, ledger.pool_live_bytes(ResourcePool::Scratch), {});
    }
  }

  [[nodiscard]] bool inject(AllocationPoint point) const noexcept {
    return fault_injector != nullptr && fault_injector->fail(point);
  }

  ResourceResult<void> release(const ResourceId& id) noexcept {
    std::lock_guard<std::recursive_mutex> lock(mutex);
    const auto iterator = entries.find(id);
    if (iterator == entries.end() || iterator->second.refcount == 0U) {
      return ResourceResult<void>::failure(make_error(
          ResourceErrorCode::RefcountCorrupt,
          "resource lease release would underflow refcount", id));
    }
    Entry& entry = iterator->second;
    --entry.refcount;
    --leases;
    if (entry.refcount == 0U) entry.last_release_tick = ++clock;
    event(CacheEvent::Release, entry, id);
    return ResourceResult<void>::success();
  }

  ByteView bytes(const ResourceId& id) const noexcept {
    std::lock_guard<std::recursive_mutex> lock(mutex);
    const auto iterator = entries.find(id);
    if (iterator == entries.end() || iterator->second.refcount == 0U) return {};
    return {static_cast<const std::uint8_t*>(iterator->second.allocation.pointer),
            iterator->second.allocation.requested_size};
  }

  const ResourceDescriptor* descriptor(const ResourceId& id) const noexcept {
    std::lock_guard<std::recursive_mutex> lock(mutex);
    const auto iterator = entries.find(id);
    return iterator == entries.end() || iterator->second.refcount == 0U
               ? nullptr
               : iterator->second.descriptor;
  }

  void event(CacheEvent cache_event, const Entry& entry,
             const ResourceId& id) noexcept {
    if (telemetry != nullptr) {
      telemetry->cache_event(cache_event, entry.pool, id, entry.bytes,
                             entry.refcount, entry.group_id);
    }
  }

  void reject(const ResourceError& resource_error, ResourcePool pool,
              std::uint64_t bytes) noexcept {
    ++rejects;
    if (telemetry != nullptr) {
      telemetry->allocation_rejected(resource_error, pool, bytes);
    }
  }

  bool evict_one(ResourcePool pool) noexcept {
    auto candidate = entries.end();
    for (auto iterator = entries.begin(); iterator != entries.end(); ++iterator) {
      const Entry& entry = iterator->second;
      if (entry.pool != pool || entry.refcount != 0U || entry.pin_owners != 0U ||
          entry.dependent_count != 0U) {
        continue;
      }
      if (candidate == entries.end() ||
          (pool == ResourcePool::Texture && entry.replacement_texture &&
           !candidate->second.replacement_texture) ||
          (pool == ResourcePool::Texture &&
           entry.replacement_texture == candidate->second.replacement_texture &&
           entry.last_release_tick < candidate->second.last_release_tick) ||
          (pool != ResourcePool::Texture &&
           entry.last_release_tick < candidate->second.last_release_tick) ||
          (entry.last_release_tick == candidate->second.last_release_tick &&
           entry.replacement_texture == candidate->second.replacement_texture &&
           iterator->first < candidate->first)) {
        candidate = iterator;
      }
    }
    if (candidate == entries.end()) return false;
    const ResourceId id = candidate->first;
    const Entry snapshot = candidate->second;
    if (ledger.release(snapshot.allocation.allocation_id,
                       snapshot.allocation.pointer, snapshot.plan.backend) !=
        LedgerError::None) {
      return false;
    }
    if (snapshot.dependency) {
      const auto dependency = entries.find(*snapshot.dependency);
      if (dependency != entries.end() && dependency->second.dependent_count > 0U) {
        --dependency->second.dependent_count;
      }
    }
    ++evictions;
    event(CacheEvent::Evict, snapshot, id);
    entries.erase(candidate);
    if (telemetry != nullptr) {
      telemetry->pool_changed(snapshot.pool, ledger.pool_live_bytes(snapshot.pool), id);
    }
    return true;
  }

  void evict_group(std::uint32_t group) noexcept {
    for (;;) {
      auto candidate = entries.end();
      for (auto iterator = entries.begin(); iterator != entries.end(); ++iterator) {
        const Entry& entry = iterator->second;
        if (entry.group_id != group || entry.refcount != 0U ||
            entry.pin_owners != 0U || entry.dependent_count != 0U) {
          continue;
        }
        if (candidate == entries.end() ||
            entry.last_release_tick < candidate->second.last_release_tick ||
            (entry.last_release_tick == candidate->second.last_release_tick &&
             iterator->first < candidate->first)) {
          candidate = iterator;
        }
      }
      if (candidate == entries.end()) return;
      const ResourceId id = candidate->first;
      const Entry snapshot = candidate->second;
      if (ledger.release(snapshot.allocation.allocation_id,
                         snapshot.allocation.pointer, snapshot.plan.backend) !=
          LedgerError::None) {
        return;
      }
      if (snapshot.dependency) {
        const auto dependency = entries.find(*snapshot.dependency);
        if (dependency != entries.end() && dependency->second.dependent_count > 0U) {
          --dependency->second.dependent_count;
        }
      }
      ++evictions;
      event(CacheEvent::Evict, snapshot, id);
      entries.erase(candidate);
      if (telemetry != nullptr) {
        telemetry->pool_changed(snapshot.pool, ledger.pool_live_bytes(snapshot.pool), id);
      }
    }
  }

  bool has_group_leases(std::uint32_t group) const noexcept {
    return std::any_of(entries.begin(), entries.end(), [group](const auto& item) {
      return item.second.group_id == group && item.second.refcount != 0U;
    });
  }

  ResourceResult<void> commit_transition(std::uint32_t target,
                                         TransitionKind kind) noexcept {
    std::lock_guard<std::recursive_mutex> lock(mutex);
    if (!transition_active || transition_target != target ||
        transition_kind != kind) {
      return ResourceResult<void>::failure(make_error(
          ResourceErrorCode::Internal,
          "transition token does not match active transition"));
    }
    for (auto& item : entries) {
      if (item.second.transaction_id == active_transaction_id) {
        item.second.transaction_id = 0U;
      }
    }
    active_group = target;
    transition_active = false;
    blocked_group = 0U;
    Entry placeholder;
    ResourceDescriptor descriptor;
    descriptor.group_id = target;
    placeholder.descriptor = &descriptor;
    placeholder.group_id = target;
    event(CacheEvent::TransitionCommit, placeholder, {});
    return ResourceResult<void>::success();
  }

  void cancel_transition(std::uint32_t target, TransitionKind kind) noexcept {
    std::lock_guard<std::recursive_mutex> lock(mutex);
    if (!transition_active || transition_target != target ||
        transition_kind != kind) {
      return;
    }
    for (;;) {
      auto candidate = std::find_if(entries.begin(), entries.end(),
                                    [this](const auto& item) {
        return item.second.transaction_id == active_transaction_id &&
               item.second.refcount == 0U &&
               item.second.dependent_count == 0U;
      });
      if (candidate == entries.end()) break;
      const ResourceId id = candidate->first;
      const Entry snapshot = candidate->second;
      if (ledger.release(snapshot.allocation.allocation_id,
                         snapshot.allocation.pointer, snapshot.plan.backend) !=
          LedgerError::None) {
        break;
      }
      if (snapshot.dependency) {
        const auto dependency = entries.find(*snapshot.dependency);
        if (dependency != entries.end() && dependency->second.dependent_count > 0U) {
          --dependency->second.dependent_count;
        }
      }
      event(CacheEvent::Evict, snapshot, id);
      entries.erase(candidate);
      if (telemetry != nullptr) {
        telemetry->pool_changed(snapshot.pool, ledger.pool_live_bytes(snapshot.pool), id);
      }
    }
    transition_active = false;
    blocked_group = 0U;
    Entry placeholder;
    ResourceDescriptor descriptor;
    descriptor.group_id = target;
    placeholder.descriptor = &descriptor;
    placeholder.group_id = target;
    event(CacheEvent::TransitionCancel, placeholder, {});
  }

  std::shared_ptr<const MountedBundle> bundle;
  std::shared_ptr<ResourceTelemetrySink> telemetry;
  std::shared_ptr<ResourceBudgetGate> budget_gate;
  std::shared_ptr<ResourceFaultInjector> fault_injector;
  mutable std::recursive_mutex mutex{};
  std::map<ResourceId, Entry> entries{};
  AllocationLedger ledger{};
  std::uint64_t clock{0U};
  std::size_t leases{0U};
  std::uint64_t evictions{0U};
  std::uint64_t rejects{0U};
  std::uint32_t active_group{0U};
  std::uint32_t blocked_group{0U};
  ResourceStage stage{ResourceStage::Boot};
  bool transition_active{false};
  std::uint32_t transition_target{0U};
  TransitionKind transition_kind{TransitionKind::World};
  bool scratch_busy{false};
  std::uint64_t next_transaction_id{0U};
  std::uint64_t active_transaction_id{0U};
  LedgerAllocation scratch_arena{};
  std::uint64_t metadata_baseline{0U};
};

std::uint64_t resource_allocation_reservation(
    std::uint64_t requested_bytes, std::uint32_t alignment) noexcept {
  std::uint64_t aligned = 0U;
  return checked_align_up(requested_bytes, alignment, aligned) ? aligned : 0U;
}

ResourceResult<AllocationPlan> raw_plan(const ResourceDescriptor& descriptor) {
  AllocationPlan plan;
  plan.pool = default_pool(descriptor.kind);
  plan.requested_bytes = descriptor.stored_size;
  plan.alignment_bytes = descriptor.alignment;
  (void)checked_align_up(plan.requested_bytes, plan.alignment_bytes,
                         plan.aligned_payload_bytes);
  plan.backend_request_bytes = plan.aligned_payload_bytes;
  plan.budget_charge_bytes = plan.aligned_payload_bytes;
  plan.group_id = descriptor.group_id;
  plan.cache_id = descriptor.id;
  plan.mount_pin = descriptor.pin_on_mount();
  if (plan.pool == ResourcePool::Count || plan.pool == ResourcePool::Scratch ||
      plan.pool == ResourcePool::Unclassified || plan.requested_bytes == 0U ||
      plan.aligned_payload_bytes == 0U) {
    return ResourceResult<AllocationPlan>::failure(make_error(
        ResourceErrorCode::BudgetContract,
        "descriptor cannot produce an authoritative raw allocation plan",
        descriptor.id));
  }
  return ResourceResult<AllocationPlan>::success(plan);
}

ResourceResult<AllocationPlan> derived_plan(
    const ResourceDescriptor& source, const DerivedAcquirePolicy& request) {
  AllocationPlan plan;
  plan.group_id = source.group_id;
  plan.replacement_texture = request.replacement_texture;
  const std::uint64_t sprite_bytes = std::min<std::uint64_t>(
      source.decoded_size, 64U * 1024U);
  if (source.kind != ResourceKind::SpriteSheet || !source.streamable() ||
      sprite_bytes == 0U) {
    return ResourceResult<AllocationPlan>::failure(make_error(
        ResourceErrorCode::BudgetContract,
        "derived type has no trusted plan for the source descriptor",
        source.id));
  }
  if (request.kind == DerivedResourceKind::SpritePixels) {
    plan.pool = ResourcePool::Sprite;
    plan.requested_bytes = sprite_bytes;
    plan.scratch_bytes = std::min<std::uint64_t>(
        source.stored_size, resource_pool_limit(ResourcePool::Scratch));
    plan.cache_id = derived_resource_id(source.id, "sprite", request.ordinal);
  } else {
    if (sprite_bytes > resource_pool_limit(ResourcePool::Texture) / 2U) {
      return ResourceResult<AllocationPlan>::failure(make_error(
          ResourceErrorCode::BudgetTexture,
          "derived texture exceeds the frozen texture pool", source.id));
    }
    plan.pool = ResourcePool::Texture;
    plan.requested_bytes = sprite_bytes * 2U;
    plan.cache_id = derived_resource_id(source.id, "texture", request.ordinal);
    plan.dependency_cache_id =
        derived_resource_id(source.id, "sprite", request.ordinal);
  }
  plan.alignment_bytes = 64U;
  (void)checked_align_up(plan.requested_bytes, plan.alignment_bytes,
                         plan.aligned_payload_bytes);
  plan.backend_request_bytes = plan.aligned_payload_bytes;
  plan.budget_charge_bytes = plan.aligned_payload_bytes;
  if (plan.aligned_payload_bytes == 0U) {
    return ResourceResult<AllocationPlan>::failure(make_error(
        ResourceErrorCode::BudgetContract,
        "derived allocation plan overflowed", source.id));
  }
  return ResourceResult<AllocationPlan>::success(plan);
}

ResourceLease::ResourceLease(std::shared_ptr<ResourceManagerState> state,
                             ResourceId id) noexcept
    : state_(std::move(state)), id_(id), active_(true) {}

ResourceLease::ResourceLease(ResourceLease&& other) noexcept
    : state_(std::move(other.state_)), id_(other.id_), active_(other.active_) {
  other.active_ = false;
}

ResourceLease& ResourceLease::operator=(ResourceLease&& other) noexcept {
  if (this != &other) {
    if (active_ && state_ != nullptr) (void)state_->release(id_);
    state_ = std::move(other.state_);
    id_ = other.id_;
    active_ = other.active_;
    other.active_ = false;
  }
  return *this;
}

ResourceLease::~ResourceLease() {
  if (active_ && state_ != nullptr) (void)state_->release(id_);
}

ByteView ResourceLease::bytes() const noexcept {
  return active_ && state_ != nullptr ? state_->bytes(id_) : ByteView{};
}

const ResourceDescriptor* ResourceLease::descriptor() const noexcept {
  return active_ && state_ != nullptr ? state_->descriptor(id_) : nullptr;
}

ResourceResult<void> ResourceLease::release() noexcept {
  if (!active_ || state_ == nullptr) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::RefcountCorrupt,
        "resource lease was released more than once", id_));
  }
  active_ = false;
  return state_->release(id_);
}

TransitionToken::TransitionToken(std::shared_ptr<ResourceManagerState> state,
                                 std::uint32_t target_group,
                                 TransitionKind kind) noexcept
    : state_(std::move(state)), target_group_(target_group), kind_(kind),
      active_(true) {}

TransitionToken::TransitionToken(TransitionToken&& other) noexcept
    : state_(std::move(other.state_)), target_group_(other.target_group_),
      kind_(other.kind_), active_(other.active_) {
  other.active_ = false;
}

TransitionToken& TransitionToken::operator=(TransitionToken&& other) noexcept {
  if (this != &other) {
    if (active_ && state_ != nullptr) state_->cancel_transition(target_group_, kind_);
    state_ = std::move(other.state_);
    target_group_ = other.target_group_;
    kind_ = other.kind_;
    active_ = other.active_;
    other.active_ = false;
  }
  return *this;
}

TransitionToken::~TransitionToken() {
  if (active_ && state_ != nullptr) state_->cancel_transition(target_group_, kind_);
}

ResourceResult<void> TransitionToken::commit() noexcept {
  if (!active_ || state_ == nullptr) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::Internal, "transition token is inactive"));
  }
  auto result = state_->commit_transition(target_group_, kind_);
  if (result) active_ = false;
  return result;
}

void TransitionToken::cancel() noexcept {
  if (active_ && state_ != nullptr) state_->cancel_transition(target_group_, kind_);
  active_ = false;
}

DecodedHashVerifier::DecodedHashVerifier(
    const ResourceDescriptor& descriptor) noexcept
    : id_(descriptor.id), expected_(descriptor.decoded_sha256),
      expected_size_(descriptor.decoded_size) {}

void DecodedHashVerifier::update(ByteView bytes) noexcept {
  if (finished_ || bytes.data == nullptr || bytes.size == 0U) return;
  if (bytes.size > std::numeric_limits<std::uint64_t>::max() - seen_) {
    seen_ = std::numeric_limits<std::uint64_t>::max();
    return;
  }
  seen_ += bytes.size;
  hash_.update(bytes.data, bytes.size);
}

ResourceResult<void> DecodedHashVerifier::finish() {
  if (finished_) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::Internal, "decoded hash verifier was finished twice", id_));
  }
  finished_ = true;
  if (seen_ != expected_size_ || hash_.finish() != expected_) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::HashDecoded,
        "decoded resource size or SHA-256 mismatch", id_));
  }
  return ResourceResult<void>::success();
}

ResourcePool default_pool(ResourceKind kind) noexcept {
  switch (kind) {
    case ResourceKind::AudioBank: return ResourcePool::Audio;
    case ResourceKind::SpriteSheet: return ResourcePool::Sprite;
    case ResourceKind::UiBitmap: return ResourcePool::Texture;
    case ResourceKind::LanguageBundle:
    case ResourceKind::FontAtlas:
    case ResourceKind::FontMap: return ResourcePool::LanguageFont;
    case ResourceKind::Palette:
    case ResourceKind::OpaqueBlob: return ResourcePool::Metadata;
  }
  return ResourcePool::Unclassified;
}

ResourceResult<std::uint64_t> resource_package_budget_cap(
    const PackageBudgets& budgets, ResourcePool pool) noexcept {
  const std::size_t pool_index = static_cast<std::size_t>(pool);
  if (pool_index >= budgets.bytes.size()) {
    return ResourceResult<std::uint64_t>::failure(make_error(
        ResourceErrorCode::BudgetContract,
        "allocation plan pool is outside the package budget contract"));
  }
  return ResourceResult<std::uint64_t>::success(budgets.bytes[pool_index]);
}

ResourceManager::ResourceManager(
    std::shared_ptr<const MountedBundle> bundle,
    std::shared_ptr<ResourceTelemetrySink> telemetry,
    std::shared_ptr<ResourceBudgetGate> budget_gate,
    std::shared_ptr<ResourceFaultInjector> fault_injector)
    : state_(std::make_shared<ResourceManagerState>(
          std::move(bundle), std::move(telemetry), std::move(budget_gate),
          std::move(fault_injector))) {}

ResourceResult<ResourceLease> ResourceManager::acquire(
    const ResourceId& id, const AcquirePolicy& policy) {
  try {
    if (state_ == nullptr || state_->bundle == nullptr) {
      return ResourceResult<ResourceLease>::failure(make_error(
          ResourceErrorCode::Internal, "resource manager has no mounted bundle", id));
    }
    const auto typed = state_->bundle->catalog.find(id, policy.expected_kind);
    if (!typed) return ResourceResult<ResourceLease>::failure(typed.error());
    const ResourceDescriptor* descriptor = typed.value();
    if (descriptor->streamable()) {
      return ResourceResult<ResourceLease>::failure(make_error(
          ResourceErrorCode::StreamRequired,
          "streamable resources require bounded range reads", id));
    }
    auto planned = raw_plan(*descriptor);
    if (!planned) return ResourceResult<ResourceLease>::failure(planned.error());
    AllocationPlan plan = planned.value();
    const std::uint64_t reservation = plan.ledger_bytes();
    std::lock_guard<std::recursive_mutex> lock(state_->mutex);
    if (state_->transition_active && plan.group_id == state_->blocked_group) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::GroupBusy,
          "old resource group is closed to new acquires", id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    auto existing = state_->entries.find(id);
    if (existing != state_->entries.end()) {
      ResourceManagerState::Entry& entry = existing->second;
      if (entry.pool != plan.pool ||
          entry.refcount == std::numeric_limits<std::uint32_t>::max()) {
        const ResourceError rejected = make_error(
            ResourceErrorCode::RefcountCorrupt,
            "cached resource plan mismatch or refcount overflow", id);
        state_->reject(rejected, plan.pool, reservation);
        return ResourceResult<ResourceLease>::failure(rejected);
      }
      ++entry.refcount;
      ++state_->leases;
      state_->event(CacheEvent::Acquire, entry, id);
      return ResourceResult<ResourceLease>::success(ResourceLease(state_, id));
    }
    const MountedPackage& package =
        state_->bundle->packages[descriptor->package_index];
    auto package_cap = resource_package_budget_cap(package.budgets, plan.pool);
    if (!package_cap) {
      ResourceError rejected = package_cap.error();
      rejected.resource_id = id;
      state_->reject(rejected, ResourcePool::Unclassified, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    const std::uint64_t cap =
        std::min(resource_pool_limit(plan.pool), package_cap.value());
    while (!allocation_fits_pool_budget(
        state_->ledger.pool_live_bytes(plan.pool), reservation, cap)) {
      if (!state_->evict_one(plan.pool)) {
        const ResourceError rejected = make_error(
            pool_error(plan.pool), "resource pool budget is exhausted", id);
        state_->reject(rejected, plan.pool, reservation);
        return ResourceResult<ResourceLease>::failure(rejected);
      }
    }
    if (state_->budget_gate != nullptr) {
      ResourceError gate_error;
      const std::uint64_t pool_after =
          state_->ledger.pool_live_bytes(plan.pool) + reservation;
      if (!state_->budget_gate->allow_allocation(
              state_->stage, plan.pool, reservation, pool_after, 0U,
              gate_error)) {
        if (!gate_error) {
          gate_error = make_error(ResourceErrorCode::BudgetContract,
                                  "runtime heap gate rejected raw allocation", id);
        }
        gate_error.resource_id = id;
        state_->reject(gate_error, plan.pool, reservation);
        return ResourceResult<ResourceLease>::failure(gate_error);
      }
    }
    if (state_->inject(AllocationPoint::Payload)) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::AllocationFailed,
          "fault injection rejected payload allocation", id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    const AllocationRequest allocation_request{
        plan.requested_bytes, plan.alignment_bytes, plan.pool, plan.backend,
        state_->transition_active && plan.group_id == state_->transition_target
            ? state_->active_transaction_id
            : 0U};
    auto allocated = state_->ledger.allocate(allocation_request);
    if (!allocated) {
      const ResourceError rejected = make_error(
          ledger_error_code(allocated.error, plan.pool),
          "allocation ledger rejected raw payload", id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    LedgerAllocationGuard allocation_guard(state_->ledger, allocated.value,
                                            plan.backend);
    const auto record = state_->ledger.record(allocated.value.allocation_id);
    if (!record) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::Internal,
          "allocation ledger did not publish a raw allocation record", id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    publish_record(plan, *record);
    auto* data = static_cast<std::uint8_t*>(allocated.value.pointer);
    auto read = read_resource_range(*state_->bundle, *descriptor, 0U,
                                    {data, allocated.value.requested_size});
    if (!read) {
      state_->reject(read.error(), plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(read.error());
    }
    if (state_->ledger.record_touch(allocated.value.allocation_id, 0U,
                                    plan.requested_bytes) != LedgerError::None) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::AccountingOverrun,
          "allocation ledger could not record raw touched pages", id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    if (sha256(data, allocated.value.requested_size) != descriptor->stored_sha256) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::HashResource,
          "resource SHA-256 changed after mount", id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    ResourceManagerState::Entry entry;
    entry.descriptor = descriptor;
    entry.pool = plan.pool;
    entry.plan = plan;
    entry.bytes = plan.ledger_bytes();
    entry.allocation = allocated.value;
    entry.refcount = 1U;
    entry.group_id = plan.group_id;
    entry.transaction_id =
        state_->transition_active && plan.group_id == state_->transition_target
            ? state_->active_transaction_id
            : 0U;
    if (plan.mount_pin) entry.pin_owners |= pin_bit(PinOwner::Mount);
    if (state_->inject(AllocationPoint::IndexNode)) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::AllocationFailed,
          "fault injection rejected index-node allocation", id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    const auto inserted = state_->entries.emplace(id, std::move(entry));
    if (!inserted.second || state_->inject(AllocationPoint::Publish)) {
      if (inserted.second) state_->entries.erase(inserted.first);
      const ResourceError rejected = make_error(
          ResourceErrorCode::AllocationFailed,
          "resource entry publication failed atomically", id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    allocation_guard.release_ownership();
    ++state_->leases;
    state_->event(CacheEvent::Allocate, inserted.first->second, id);
    if (state_->telemetry != nullptr) {
      state_->telemetry->pool_changed(
          plan.pool, state_->ledger.pool_live_bytes(plan.pool), id);
    }
    return ResourceResult<ResourceLease>::success(ResourceLease(state_, id));
  } catch (const std::bad_alloc&) {
    return ResourceResult<ResourceLease>::failure(make_error(
        ResourceErrorCode::AllocationFailed,
        "raw acquire caught allocator failure", id));
  } catch (...) {
    return ResourceResult<ResourceLease>::failure(make_error(
        ResourceErrorCode::Internal,
        "raw acquire caught an internal exception", id));
  }
}

ResourceResult<ResourceLease> ResourceManager::acquire_derived(
    const DerivedAcquirePolicy& policy, const DerivedLoader& loader) {
  ResourceId cache_id{};
  try {
    if (state_ == nullptr || state_->bundle == nullptr || !loader) {
      return ResourceResult<ResourceLease>::failure(make_error(
          ResourceErrorCode::Internal,
          "derived acquire has no mounted bundle or loader", policy.source_id));
    }
    const auto typed = state_->bundle->catalog.find(
        policy.source_id, policy.expected_source_kind);
    if (!typed) return ResourceResult<ResourceLease>::failure(typed.error());
    const ResourceDescriptor* source = typed.value();
    auto planned = derived_plan(*source, policy);
    if (!planned) return ResourceResult<ResourceLease>::failure(planned.error());
    AllocationPlan plan = planned.value();
    cache_id = plan.cache_id;
    const std::uint64_t reservation = plan.ledger_bytes();
    if (cache_id == source->id || state_->bundle->catalog.find(cache_id) != nullptr) {
      return ResourceResult<ResourceLease>::failure(make_error(
          ResourceErrorCode::IdDuplicate,
          "derived cache ID collides with a catalog resource ID", cache_id));
    }
    std::lock_guard<std::recursive_mutex> lock(state_->mutex);
    if (state_->transition_active && plan.group_id == state_->blocked_group) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::GroupBusy,
          "old resource group is closed to derived acquires", cache_id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    auto existing = state_->entries.find(cache_id);
    if (existing != state_->entries.end()) {
      ResourceManagerState::Entry& entry = existing->second;
      if (entry.descriptor != source || entry.pool != plan.pool ||
          entry.group_id != plan.group_id ||
          entry.refcount == std::numeric_limits<std::uint32_t>::max()) {
        const ResourceError rejected = make_error(
            ResourceErrorCode::RefcountCorrupt,
            "derived cache identity maps to incompatible state", cache_id);
        state_->reject(rejected, plan.pool, reservation);
        return ResourceResult<ResourceLease>::failure(rejected);
      }
      ++entry.refcount;
      ++state_->leases;
      state_->event(CacheEvent::Acquire, entry, cache_id);
      return ResourceResult<ResourceLease>::success(ResourceLease(state_, cache_id));
    }
    if (plan.scratch_bytes != 0U && state_->scratch_busy) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::ScratchBusy,
          "derived decoder cannot recursively acquire scratch", cache_id);
      state_->reject(rejected, ResourcePool::Scratch, plan.scratch_bytes);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    auto dependency = state_->entries.end();
    if (plan.dependency_cache_id) {
      dependency = state_->entries.find(*plan.dependency_cache_id);
      if (dependency == state_->entries.end() ||
          dependency->second.dependent_count ==
              std::numeric_limits<std::uint32_t>::max()) {
        const ResourceError rejected = make_error(
            ResourceErrorCode::ResourceNotFound,
            "authoritative derived dependency is not resident", cache_id);
        state_->reject(rejected, plan.pool, reservation);
        return ResourceResult<ResourceLease>::failure(rejected);
      }
    }
    const MountedPackage& package = state_->bundle->packages[source->package_index];
    auto package_cap = resource_package_budget_cap(package.budgets, plan.pool);
    if (!package_cap) {
      ResourceError rejected = package_cap.error();
      rejected.resource_id = cache_id;
      state_->reject(rejected, ResourcePool::Unclassified, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    const std::uint64_t cap =
        std::min(resource_pool_limit(plan.pool), package_cap.value());
    while (!allocation_fits_pool_budget(
        state_->ledger.pool_live_bytes(plan.pool), reservation, cap)) {
      if (!state_->evict_one(plan.pool)) {
        const ResourceError rejected = make_error(
            pool_error(plan.pool), "derived resource pool budget is exhausted",
            cache_id);
        state_->reject(rejected, plan.pool, reservation);
        return ResourceResult<ResourceLease>::failure(rejected);
      }
    }
    if (state_->budget_gate != nullptr) {
      ResourceError gate_error;
      const std::uint64_t pool_after =
          state_->ledger.pool_live_bytes(plan.pool) + reservation;
      if (!state_->budget_gate->allow_allocation(
              state_->stage, plan.pool, reservation, pool_after,
              plan.scratch_bytes, gate_error)) {
        if (!gate_error) {
          gate_error = make_error(ResourceErrorCode::BudgetContract,
                                  "runtime heap gate rejected derived allocation",
                                  cache_id);
        }
        gate_error.resource_id = cache_id;
        state_->reject(gate_error, plan.pool, reservation);
        return ResourceResult<ResourceLease>::failure(gate_error);
      }
    }
    if (plan.scratch_bytes > state_->scratch_arena.requested_size ||
        state_->inject(AllocationPoint::Scratch)) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::AllocationFailed,
          "shared scratch arena is unavailable", cache_id);
      state_->reject(rejected, ResourcePool::Scratch, plan.scratch_bytes);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    if (state_->inject(AllocationPoint::Payload)) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::AllocationFailed,
          "fault injection rejected derived payload", cache_id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    state_->scratch_busy = plan.scratch_bytes != 0U;
    const AllocationRequest allocation_request{
        plan.requested_bytes, plan.alignment_bytes, plan.pool, plan.backend,
        state_->transition_active && plan.group_id == state_->transition_target
            ? state_->active_transaction_id
            : 0U};
    auto allocated = state_->ledger.allocate(allocation_request);
    if (!allocated) {
      state_->scratch_busy = false;
      const ResourceError rejected = make_error(
          ledger_error_code(allocated.error, plan.pool),
          "allocation ledger rejected derived payload", cache_id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    LedgerAllocationGuard allocation_guard(state_->ledger, allocated.value,
                                            plan.backend);
    const auto record = state_->ledger.record(allocated.value.allocation_id);
    if (!record) {
      state_->scratch_busy = false;
      const ResourceError rejected = make_error(
          ResourceErrorCode::Internal,
          "allocation ledger did not publish a derived allocation record",
          cache_id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    publish_record(plan, *record);
    auto* destination = static_cast<std::uint8_t*>(allocated.value.pointer);
    auto* scratch = static_cast<std::uint8_t*>(state_->scratch_arena.pointer);
    const DerivedRead reader = [this, source](
                                   std::uint64_t offset,
                                   MutableByteView bytes) -> ResourceResult<void> {
      return read_resource_range(*state_->bundle, *source, offset, bytes);
    };
    ResourceResult<std::size_t> decoded = loader(
        *source, {destination, allocated.value.requested_size},
        {scratch, static_cast<std::size_t>(plan.scratch_bytes)}, reader);
    state_->scratch_busy = false;
    if (!decoded) {
      state_->reject(decoded.error(), plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(decoded.error());
    }
    if (decoded.value() != plan.requested_bytes) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::AccountingOverrun,
          "derived loader wrote a different size than its trusted plan", cache_id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    if (state_->ledger.record_touch(allocated.value.allocation_id, 0U,
                                    plan.requested_bytes) != LedgerError::None ||
        (plan.scratch_bytes != 0U &&
         state_->ledger.record_touch(state_->scratch_arena.allocation_id, 0U,
                                     plan.scratch_bytes) != LedgerError::None)) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::AccountingOverrun,
          "allocation ledger could not record derived touched pages", cache_id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    ResourceManagerState::Entry entry;
    entry.descriptor = source;
    entry.pool = plan.pool;
    entry.plan = plan;
    entry.allocation = allocated.value;
    entry.bytes = plan.ledger_bytes();
    entry.refcount = 1U;
    entry.group_id = plan.group_id;
    entry.transaction_id =
        state_->transition_active && plan.group_id == state_->transition_target
            ? state_->active_transaction_id
            : 0U;
    entry.replacement_texture = plan.replacement_texture;
    entry.dependency = plan.dependency_cache_id;
    if (state_->inject(AllocationPoint::IndexNode) ||
        (plan.dependency_cache_id && state_->inject(AllocationPoint::DependencyEdge))) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::AllocationFailed,
          "fault injection rejected derived index or dependency edge", cache_id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    const auto inserted = state_->entries.emplace(cache_id, std::move(entry));
    if (!inserted.second || state_->inject(AllocationPoint::Publish)) {
      if (inserted.second) state_->entries.erase(inserted.first);
      const ResourceError rejected = make_error(
          ResourceErrorCode::AllocationFailed,
          "derived entry publication failed atomically", cache_id);
      state_->reject(rejected, plan.pool, reservation);
      return ResourceResult<ResourceLease>::failure(rejected);
    }
    allocation_guard.release_ownership();
    if (plan.dependency_cache_id) ++dependency->second.dependent_count;
    ++state_->leases;
    state_->event(CacheEvent::Allocate, inserted.first->second, cache_id);
    if (state_->telemetry != nullptr) {
      state_->telemetry->pool_changed(
          plan.pool, state_->ledger.pool_live_bytes(plan.pool), cache_id);
    }
    return ResourceResult<ResourceLease>::success(ResourceLease(state_, cache_id));
  } catch (const std::bad_alloc&) {
    if (state_ != nullptr) state_->scratch_busy = false;
    return ResourceResult<ResourceLease>::failure(make_error(
        ResourceErrorCode::AllocationFailed,
        "derived acquire caught allocator failure", cache_id));
  } catch (...) {
    if (state_ != nullptr) state_->scratch_busy = false;
    return ResourceResult<ResourceLease>::failure(make_error(
        ResourceErrorCode::Internal,
        "derived acquire caught a loader or container exception", cache_id));
  }
}

ResourceResult<void> ResourceManager::read_stream_range(
    const ResourceId& id, ResourceKind expected_kind,
    std::uint64_t relative_offset, std::size_t bytes,
    const std::function<ResourceResult<void>(ByteView)>& consumer) {
  if (state_ == nullptr || state_->bundle == nullptr || !consumer) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::Internal, "stream read has no bundle or consumer", id));
  }
  const auto typed = state_->bundle->catalog.find(id, expected_kind);
  if (!typed) return ResourceResult<void>::failure(typed.error());
  const ResourceDescriptor* descriptor = typed.value();
  if (!descriptor->streamable()) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::StreamRequired,
        "bounded range API only accepts streamable resources", id));
  }
  if (bytes > resource_pool_limit(ResourcePool::Scratch) ||
      bytes > state_->scratch_arena.requested_size ||
      relative_offset > descriptor->stored_size ||
      bytes > descriptor->stored_size - relative_offset) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::BudgetScratch,
        "stream range exceeds resource or 1 MiB scratch bounds", id));
  }
  {
    std::lock_guard<std::recursive_mutex> lock(state_->mutex);
    if (state_->scratch_busy) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::ScratchBusy,
          "shared scratch workspace is already in use", id);
      state_->reject(rejected, ResourcePool::Scratch, bytes);
      return ResourceResult<void>::failure(rejected);
    }
    if (state_->inject(AllocationPoint::Scratch)) {
      const ResourceError rejected = make_error(
          ResourceErrorCode::AllocationFailed,
          "fault injection rejected shared scratch use", id);
      state_->reject(rejected, ResourcePool::Scratch, bytes);
      return ResourceResult<void>::failure(rejected);
    }
    if (state_->budget_gate != nullptr) {
      ResourceError gate_error;
      if (!state_->budget_gate->allow_allocation(
              state_->stage, ResourcePool::Scratch, bytes, bytes, bytes,
              gate_error)) {
        if (!gate_error) {
          gate_error = make_error(ResourceErrorCode::BudgetScratch,
                                  "runtime scratch gate rejected stream range", id);
        }
        gate_error.resource_id = id;
        state_->reject(gate_error, ResourcePool::Scratch, bytes);
        return ResourceResult<void>::failure(gate_error);
      }
    }
    state_->scratch_busy = true;
  }
  ResourceResult<void> result = ResourceResult<void>::success();
  if (result) {
    auto* scratch = static_cast<std::uint8_t*>(state_->scratch_arena.pointer);
    result = read_resource_range(*state_->bundle, *descriptor, relative_offset,
                                 {scratch, bytes});
    if (result) {
      try {
        result = consumer({scratch, bytes});
      } catch (...) {
        result = ResourceResult<void>::failure(make_error(
            ResourceErrorCode::Internal, "stream consumer threw an exception", id));
      }
    }
  }
  {
    std::lock_guard<std::recursive_mutex> lock(state_->mutex);
    state_->scratch_busy = false;
    if (result && state_->ledger.record_touch(
                      state_->scratch_arena.allocation_id, 0U,
                      static_cast<std::uint64_t>(bytes)) != LedgerError::None) {
      result = ResourceResult<void>::failure(make_error(
          ResourceErrorCode::AccountingOverrun,
          "allocation ledger could not record scratch touched pages", id));
    }
    if (!result) state_->reject(result.error(), ResourcePool::Scratch, bytes);
  }
  return result;
}

ResourceResult<void> ResourceManager::pin(const ResourceId& id, PinOwner owner) {
  std::lock_guard<std::recursive_mutex> lock(state_->mutex);
  const auto iterator = state_->entries.find(id);
  if (iterator == state_->entries.end()) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::ResourceNotFound,
        "only a resident resource can be pinned", id));
  }
  iterator->second.pin_owners |= pin_bit(owner);
  state_->event(CacheEvent::Pin, iterator->second, id);
  return ResourceResult<void>::success();
}

ResourceResult<void> ResourceManager::unpin(const ResourceId& id, PinOwner owner) {
  std::lock_guard<std::recursive_mutex> lock(state_->mutex);
  const auto iterator = state_->entries.find(id);
  if (iterator == state_->entries.end()) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::ResourceNotFound,
        "only a resident resource can be unpinned", id));
  }
  const std::uint64_t bit = pin_bit(owner);
  if ((iterator->second.pin_owners & bit) == 0U) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::RefcountCorrupt,
        "pin owner does not hold this resource", id));
  }
  iterator->second.pin_owners &= ~bit;
  state_->event(CacheEvent::Unpin, iterator->second, id);
  return ResourceResult<void>::success();
}

ResourceResult<void> ResourceManager::release_group(std::uint32_t group_id) {
  std::lock_guard<std::recursive_mutex> lock(state_->mutex);
  if (state_->has_group_leases(group_id)) {
    return ResourceResult<void>::failure(make_error(
        ResourceErrorCode::GroupBusy,
        "resource group still has active leases"));
  }
  state_->evict_group(group_id);
  return ResourceResult<void>::success();
}

void ResourceManager::purge_zero_reference() noexcept {
  std::lock_guard<std::recursive_mutex> lock(state_->mutex);
  for (const ResourcePool pool : kEvictionOrder) {
    while (state_->evict_one(pool)) {
    }
  }
  while (state_->evict_one(ResourcePool::LanguageFont)) {
  }
}

void ResourceManager::purge_group(std::uint32_t group_id) noexcept {
  std::lock_guard<std::recursive_mutex> lock(state_->mutex);
  state_->evict_group(group_id);
}

ResourceResult<TransitionToken> ResourceManager::begin_transition(
    std::uint32_t target_group, TransitionKind kind) {
  std::lock_guard<std::recursive_mutex> lock(state_->mutex);
  if (state_->transition_active) {
    return ResourceResult<TransitionToken>::failure(make_error(
        ResourceErrorCode::GroupBusy, "another resource transition is active"));
  }
  state_->blocked_group =
      kind == TransitionKind::SaveLoad ? 0U : state_->active_group;
  if (kind != TransitionKind::SaveLoad && state_->active_group != 0U &&
      state_->has_group_leases(state_->active_group)) {
    state_->blocked_group = 0U;
    return ResourceResult<TransitionToken>::failure(make_error(
        ResourceErrorCode::GroupBusy,
        "old resource group still has active leases"));
  }
  if (kind != TransitionKind::SaveLoad && state_->active_group != 0U) {
    state_->evict_group(state_->active_group);
  }
  if (state_->budget_gate != nullptr) {
    ResourceError gate_error;
    if (!state_->budget_gate->allow_operation(kind, gate_error)) {
      if (!gate_error) {
        gate_error = make_error(
            kind == TransitionKind::SaveLoad ? ResourceErrorCode::SaveReserve
                                             : ResourceErrorCode::TransitionReserve,
            "operation reserve gate failed");
      }
      state_->blocked_group = 0U;
      state_->reject(gate_error, ResourcePool::Unclassified, 4U * kMiB);
      return ResourceResult<TransitionToken>::failure(gate_error);
    }
  }
  state_->transition_active = true;
  state_->active_transaction_id = ++state_->next_transaction_id;
  state_->transition_target = target_group;
  state_->transition_kind = kind;
  ResourceManagerState::Entry placeholder;
  ResourceDescriptor descriptor;
  descriptor.group_id = target_group;
  placeholder.descriptor = &descriptor;
  placeholder.group_id = target_group;
  state_->event(CacheEvent::TransitionBegin, placeholder, {});
  return ResourceResult<TransitionToken>::success(
      TransitionToken(state_, target_group, kind));
}

ResourceResult<TransitionToken> ResourceManager::begin_menu_transition(
    std::uint32_t menu_group) {
  return begin_transition(menu_group, TransitionKind::Menu);
}

ResourceResult<TransitionToken> ResourceManager::begin_first_level_transition(
    std::uint32_t first_level_group) {
  return begin_transition(first_level_group, TransitionKind::FirstLevel);
}

ResourceResult<TransitionToken> ResourceManager::begin_world_transition(
    std::uint32_t target_group) {
  return begin_transition(target_group, TransitionKind::World);
}

ResourceResult<TransitionToken> ResourceManager::begin_save_load() {
  return begin_transition(state_->active_group, TransitionKind::SaveLoad);
}

void ResourceManager::set_stage(ResourceStage stage) noexcept {
  std::lock_guard<std::recursive_mutex> lock(state_->mutex);
  state_->stage = stage;
}

ResourceMemorySnapshot ResourceManager::snapshot() const noexcept {
  std::lock_guard<std::recursive_mutex> lock(state_->mutex);
  ResourceMemorySnapshot result;
  const AllocationLedgerSnapshot ledger = state_->ledger.snapshot();
  result.pool_bytes = ledger.pool_budget_bytes;
  result.entries = state_->entries.size();
  result.leases = state_->leases;
  for (const auto& item : state_->entries) {
    result.pins += count_bits(item.second.pin_owners);
    result.dependents += item.second.dependent_count;
  }
  bool payload_valid = true;
  for (std::size_t index = 0U; index < ledger.pool_budget_bytes.size(); ++index) {
    if (index == static_cast<std::size_t>(ResourcePool::Scratch)) continue;
    const std::uint64_t bytes = ledger.pool_budget_bytes[index];
    if (bytes > std::numeric_limits<std::uint64_t>::max() - result.payload_bytes) {
      payload_valid = false;
      break;
    }
    result.payload_bytes += bytes;
  }
  result.allocation_overhead_bytes = 0U;
  result.metadata_baseline_bytes = state_->metadata_baseline;
  result.unclassified_bytes = ledger.reconciliation.regular_delta_bytes;
  result.unclassified_known =
      ledger.reconciliation.regular_measurement_available &&
      ledger.reconciliation.valid;
  result.backend_bytes = ledger.backend_accounted_bytes;
  result.requested_bytes = ledger.requested_bytes;
  result.aligned_payload_bytes = ledger.aligned_payload_bytes;
  result.backend_request_bytes = ledger.backend_request_bytes;
  result.usable_bytes = ledger.usable_bytes;
  result.budget_charge_bytes = ledger.budget_charge_bytes;
  result.backend_accounted_bytes = ledger.backend_accounted_total_bytes;
  result.allocation_records = ledger.live_records;
  result.reconciliation = ledger.reconciliation;
  result.reconciliation.valid = result.reconciliation.valid && payload_valid;
  result.evictions = state_->evictions;
  result.rejects = state_->rejects;
  result.active_group = state_->active_group;
  result.stage = state_->stage;
  result.transition_active = state_->transition_active;
  return result;
}

std::shared_ptr<const MountedBundle> ResourceManager::bundle() const noexcept {
  return state_ == nullptr ? nullptr : state_->bundle;
}

ResourceId derived_resource_id(const ResourceId& source_id,
                               std::string_view domain,
                               std::uint64_t ordinal) noexcept {
  Sha256 hash;
  constexpr char prefix[] = "th3ds-derived-id-v1";
  hash.update(prefix, sizeof(prefix));
  hash.update(source_id.data(), source_id.size());
  hash.update(domain.data(), domain.size());
  const std::uint8_t zero = 0U;
  hash.update(&zero, 1U);
  std::array<std::uint8_t, 8> encoded{};
  for (std::size_t index = 0U; index < encoded.size(); ++index) {
    encoded[index] =
        static_cast<std::uint8_t>((ordinal >> (index * 8U)) & 0xFFU);
  }
  hash.update(encoded.data(), encoded.size());
  const Sha256Digest digest = hash.finish();
  ResourceId result{};
  std::copy_n(digest.begin(), result.size(), result.begin());
  return result;
}

}  // namespace cth3ds
