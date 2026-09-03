#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string_view>

#include "cth3ds/allocation_ledger.hpp"
#include "cth3ds/th3ds.hpp"

namespace cth3ds {

enum class ResourceStage : std::uint8_t {
  Boot,
  SelectedLanguage,
  Menu,
  FirstLevel,
  Operation,
};

enum class TransitionKind : std::uint8_t {
  Menu,
  FirstLevel,
  World,
  SaveLoad,
};

enum class CacheEvent : std::uint8_t {
  Allocate,
  Acquire,
  Release,
  Evict,
  Pin,
  Unpin,
  TransitionBegin,
  TransitionCommit,
  TransitionCancel,
};

struct ResourceMemorySnapshot {
  std::array<std::uint64_t, static_cast<std::size_t>(ResourcePool::Count)>
      pool_bytes{};
  std::size_t entries{0U};
  std::size_t leases{0U};
  std::size_t pins{0U};
  std::size_t dependents{0U};
  std::uint64_t payload_bytes{0U};
  // Deprecated compatibility field. Fixed object/index estimates were removed;
  // this field is always zero.
  std::uint64_t allocation_overhead_bytes{0U};
  // Deprecated compatibility field. Unowned STL storage is represented by the
  // signed reconciliation residual; this field is always zero.
  std::uint64_t metadata_baseline_bytes{0U};
  std::int64_t unclassified_bytes{0};
  bool unclassified_known{false};
  std::array<std::uint64_t, static_cast<std::size_t>(AllocationBackend::Count)>
      backend_bytes{};
  std::uint64_t requested_bytes{0U};
  std::uint64_t aligned_payload_bytes{0U};
  std::uint64_t backend_request_bytes{0U};
  std::uint64_t usable_bytes{0U};
  std::uint64_t budget_charge_bytes{0U};
  std::uint64_t backend_accounted_bytes{0U};
  std::size_t allocation_records{0U};
  Reconciliation reconciliation{};
  std::uint64_t evictions{0U};
  std::uint64_t rejects{0U};
  std::uint32_t active_group{0U};
  ResourceStage stage{ResourceStage::Boot};
  bool transition_active{false};
};

enum class PinOwner : std::uint8_t {
  Mount = 0,
  Session = 1,
  Adapter = 2,
  ErrorUi = 3,
  Test = 63,
};

enum class DerivedResourceKind : std::uint8_t {
  SpritePixels,
  Texture,
};

enum class AllocationPoint : std::uint8_t {
  Payload,
  Scratch,
  IndexNode,
  DependencyEdge,
  Publish,
};

struct AllocationPlan {
  ResourcePool pool{ResourcePool::Count};
  AllocationBackend backend{AllocationBackend::Regular};
  std::uint64_t requested_bytes{0U};
  std::uint64_t alignment_bytes{64U};
  std::uint64_t aligned_payload_bytes{0U};
  std::uint64_t backend_request_bytes{0U};
  std::uint64_t usable_bytes{0U};
  UsableQuality usable_quality{UsableQuality::BackendRequestFallback};
  std::uint64_t budget_charge_bytes{0U};
  std::uint64_t backend_accounted_bytes{0U};
  std::uint64_t scratch_bytes{0U};
  std::uint32_t group_id{0U};
  ResourceId cache_id{};
  std::optional<ResourceId> dependency_cache_id{};
  bool replacement_texture{false};
  bool mount_pin{false};

  [[nodiscard]] std::uint64_t ledger_bytes() const noexcept {
    return budget_charge_bytes;
  }
};

class ResourceFaultInjector {
 public:
  virtual ~ResourceFaultInjector() = default;
  [[nodiscard]] virtual bool fail(AllocationPoint point) noexcept = 0;
};

class ResourceTelemetrySink {
 public:
  virtual ~ResourceTelemetrySink() = default;
  virtual void pool_changed(ResourcePool pool, std::uint64_t bytes,
                            const ResourceId& id) noexcept = 0;
  virtual void cache_event(CacheEvent event, ResourcePool pool,
                           const ResourceId& id, std::uint64_t bytes,
                           std::uint32_t refcount,
                           std::uint32_t group_id) noexcept = 0;
  virtual void allocation_rejected(const ResourceError& resource_error,
                                   ResourcePool pool,
                                   std::uint64_t requested_bytes) noexcept = 0;
};

class ResourceBudgetGate {
 public:
  virtual ~ResourceBudgetGate() = default;
  [[nodiscard]] virtual bool allow_allocation(
      ResourceStage stage, ResourcePool pool, std::uint64_t requested_bytes,
      std::uint64_t pool_bytes_after, std::uint64_t scratch_bytes,
      ResourceError& resource_error) noexcept = 0;
  [[nodiscard]] virtual bool allow_operation(
      TransitionKind kind, ResourceError& resource_error) noexcept = 0;
};

struct AcquirePolicy {
  ResourceKind expected_kind{ResourceKind::OpaqueBlob};
};

struct DerivedAcquirePolicy {
  ResourceId source_id{};
  ResourceKind expected_source_kind{ResourceKind::OpaqueBlob};
  DerivedResourceKind kind{DerivedResourceKind::SpritePixels};
  std::uint64_t ordinal{0U};
  bool replacement_texture{false};
};

using DerivedRead = std::function<ResourceResult<void>(
    std::uint64_t relative_offset, MutableByteView destination)>;
using DerivedLoader = std::function<ResourceResult<std::size_t>(
    const ResourceDescriptor& source, MutableByteView destination,
    MutableByteView scratch, const DerivedRead& read_source)>;

class ResourceManagerState;

class ResourceLease {
 public:
  ResourceLease() = default;
  ResourceLease(const ResourceLease&) = delete;
  ResourceLease& operator=(const ResourceLease&) = delete;
  ResourceLease(ResourceLease&& other) noexcept;
  ResourceLease& operator=(ResourceLease&& other) noexcept;
  ~ResourceLease();

  [[nodiscard]] bool valid() const noexcept { return active_; }
  [[nodiscard]] ByteView bytes() const noexcept;
  [[nodiscard]] const ResourceDescriptor* descriptor() const noexcept;
  [[nodiscard]] ResourceResult<void> release() noexcept;

 private:
  friend class ResourceManager;
  ResourceLease(std::shared_ptr<ResourceManagerState> state, ResourceId id) noexcept;
  std::shared_ptr<ResourceManagerState> state_{};
  ResourceId id_{};
  bool active_{false};
};

class TransitionToken {
 public:
  TransitionToken() = default;
  TransitionToken(const TransitionToken&) = delete;
  TransitionToken& operator=(const TransitionToken&) = delete;
  TransitionToken(TransitionToken&& other) noexcept;
  TransitionToken& operator=(TransitionToken&& other) noexcept;
  ~TransitionToken();

  [[nodiscard]] bool valid() const noexcept { return active_; }
  [[nodiscard]] ResourceResult<void> commit() noexcept;
  void cancel() noexcept;

 private:
  friend class ResourceManager;
  TransitionToken(std::shared_ptr<ResourceManagerState> state,
                  std::uint32_t target_group, TransitionKind kind) noexcept;
  std::shared_ptr<ResourceManagerState> state_{};
  std::uint32_t target_group_{0U};
  TransitionKind kind_{TransitionKind::World};
  bool active_{false};
};

class DecodedHashVerifier {
 public:
  explicit DecodedHashVerifier(const ResourceDescriptor& descriptor) noexcept;
  void update(ByteView bytes) noexcept;
  [[nodiscard]] ResourceResult<void> finish();

 private:
  ResourceId id_{};
  Sha256Digest expected_{};
  std::uint64_t expected_size_{0U};
  std::uint64_t seen_{0U};
  Sha256 hash_{};
  bool finished_{false};
};

class ResourceManager {
 public:
  explicit ResourceManager(
      std::shared_ptr<const MountedBundle> bundle,
      std::shared_ptr<ResourceTelemetrySink> telemetry = {},
      std::shared_ptr<ResourceBudgetGate> budget_gate = {},
      std::shared_ptr<ResourceFaultInjector> fault_injector = {});
  ResourceManager(const ResourceManager&) = delete;
  ResourceManager& operator=(const ResourceManager&) = delete;
  ResourceManager(ResourceManager&&) noexcept = default;
  ResourceManager& operator=(ResourceManager&&) noexcept = default;

  [[nodiscard]] ResourceResult<ResourceLease> acquire(
      const ResourceId& id, const AcquirePolicy& policy);
  [[nodiscard]] ResourceResult<ResourceLease> acquire_derived(
      const DerivedAcquirePolicy& policy, const DerivedLoader& loader);
  [[nodiscard]] ResourceResult<void> read_stream_range(
      const ResourceId& id, ResourceKind expected_kind,
      std::uint64_t relative_offset, std::size_t bytes,
      const std::function<ResourceResult<void>(ByteView)>& consumer);

  [[nodiscard]] ResourceResult<void> pin(
      const ResourceId& id, PinOwner owner = PinOwner::Session);
  [[nodiscard]] ResourceResult<void> unpin(
      const ResourceId& id, PinOwner owner = PinOwner::Session);
  [[nodiscard]] ResourceResult<void> release_group(std::uint32_t group_id);
  void purge_zero_reference() noexcept;
  void purge_group(std::uint32_t group_id) noexcept;

  [[nodiscard]] ResourceResult<TransitionToken> begin_transition(
      std::uint32_t target_group, TransitionKind kind);
  [[nodiscard]] ResourceResult<TransitionToken> begin_menu_transition(
      std::uint32_t menu_group);
  [[nodiscard]] ResourceResult<TransitionToken> begin_first_level_transition(
      std::uint32_t first_level_group);
  [[nodiscard]] ResourceResult<TransitionToken> begin_world_transition(
      std::uint32_t target_group);
  [[nodiscard]] ResourceResult<TransitionToken> begin_save_load();

  void set_stage(ResourceStage stage) noexcept;
  [[nodiscard]] ResourceMemorySnapshot snapshot() const noexcept;
  [[nodiscard]] std::shared_ptr<const MountedBundle> bundle() const noexcept;

 private:
  std::shared_ptr<ResourceManagerState> state_{};
};

[[nodiscard]] ResourcePool default_pool(ResourceKind kind) noexcept;
[[nodiscard]] std::uint64_t resource_allocation_reservation(
    std::uint64_t requested_bytes, std::uint32_t alignment) noexcept;
[[nodiscard]] ResourceId derived_resource_id(
    const ResourceId& source_id, std::string_view domain,
    std::uint64_t ordinal) noexcept;

}  // namespace cth3ds
