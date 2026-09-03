#pragma once

#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <vector>

#include "cth3ds/resource_manager.hpp"

namespace cth3ds {

enum class RuntimeSessionState : std::uint8_t {
  Closed,
  Starting,
  Menu,
  Transitioning,
  Level,
  Suspended,
  ShuttingDown,
  Error,
};

enum class RuntimeSessionEvent : std::uint8_t {
  MountBegin,
  MountCommit,
  PinBegin,
  PinCommit,
  TransitionBegin,
  TransitionCommit,
  TransitionRollback,
  SaveBegin,
  SaveCommit,
  SaveRollback,
  Suspend,
  Resume,
  Quiesce,
  ShutdownBegin,
  ShutdownCommit,
};

struct RuntimeSessionConfig {
  std::shared_ptr<ResourceTelemetrySink> telemetry{};
  std::shared_ptr<ResourceBudgetGate> budget_gate{};
  std::shared_ptr<ResourceFaultInjector> fault_injector{};
  std::function<ResourceResult<void>()> quiesce_clients{};
  std::uint32_t menu_group{1U};
};

struct RuntimeSessionSnapshot {
  RuntimeSessionState state{RuntimeSessionState::Closed};
  ResourceMemorySnapshot resources{};
  std::size_t mounted_packages{0U};
  std::size_t trace_events{0U};
  std::uint64_t mount_generation{0U};
  std::uint64_t catalog_generation{0U};
  bool ledger_at_baseline{false};
};

using RuntimePrepare =
    std::function<ResourceResult<void>(ResourceManager& manager)>;

class RuntimeSession {
 public:
  [[nodiscard]] static ResourceResult<std::unique_ptr<RuntimeSession>> start(
      const std::filesystem::path& bundle_manifest,
      RuntimeSessionConfig config = {});

  // Unit-test seam. Production composition must call start(path, config).
  [[nodiscard]] static ResourceResult<std::unique_ptr<RuntimeSession>>
  start_mounted_for_test(std::shared_ptr<MountedBundle> bundle,
                         RuntimeSessionConfig config = {});

  RuntimeSession(const RuntimeSession&) = delete;
  RuntimeSession& operator=(const RuntimeSession&) = delete;
  RuntimeSession(RuntimeSession&&) = delete;
  RuntimeSession& operator=(RuntimeSession&&) = delete;
  ~RuntimeSession();

  [[nodiscard]] ResourceResult<ResourceLease> acquire(
      const ResourceId& id, ResourceKind kind);
  [[nodiscard]] ResourceResult<void> enter_menu(
      std::uint32_t menu_group, const RuntimePrepare& prepare = {});
  [[nodiscard]] ResourceResult<void> enter_level(
      std::uint32_t level_group, const RuntimePrepare& prepare = {});
  [[nodiscard]] ResourceResult<void> save_or_load(
      const RuntimePrepare& operation);
  [[nodiscard]] ResourceResult<void> begin_save_load();
  [[nodiscard]] ResourceResult<void> finish_save_load(bool commit);
  [[nodiscard]] ResourceResult<void> suspend();
  [[nodiscard]] ResourceResult<void> resume();
  [[nodiscard]] ResourceResult<void> shutdown();

  [[nodiscard]] RuntimeSessionSnapshot snapshot() const noexcept;
  [[nodiscard]] const std::vector<RuntimeSessionEvent>& trace() const noexcept {
    return trace_;
  }
  [[nodiscard]] const MountedBundle* bundle() const noexcept {
    return bundle_.get();
  }

 private:
  explicit RuntimeSession(RuntimeSessionConfig config);
  [[nodiscard]] ResourceResult<void> initialize(
      std::shared_ptr<MountedBundle> bundle);
  [[nodiscard]] ResourceResult<void> transition(
      std::uint32_t target_group, TransitionKind kind,
      RuntimeSessionState target_state, const RuntimePrepare& prepare);
  [[nodiscard]] ResourceResult<void> quiesce();
  [[nodiscard]] bool ledger_at_baseline() const noexcept;
  void record(RuntimeSessionEvent event);

  RuntimeSessionConfig config_{};
  RuntimeSessionState state_{RuntimeSessionState::Closed};
  RuntimeSessionState resume_state_{RuntimeSessionState::Menu};
  std::shared_ptr<MountedBundle> bundle_{};
  std::unique_ptr<ResourceManager> manager_{};
  ResourceMemorySnapshot baseline_{};
  ResourceMemorySnapshot closed_{};
  std::vector<ResourceId> mount_pins_{};
  std::vector<RuntimeSessionEvent> trace_{};
  std::optional<TransitionToken> save_load_token_{};
  std::uint64_t mount_generation_{0U};
  std::uint64_t catalog_generation_{0U};
};

}  // namespace cth3ds
