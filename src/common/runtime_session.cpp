#include "cth3ds/runtime_session.hpp"

#include <algorithm>
#include <new>
#include <utility>

namespace cth3ds {
namespace {

ResourceError session_error(ResourceErrorCode code, const char* message) {
  return {code, message, {}};
}

}  // namespace

RuntimeSession::RuntimeSession(RuntimeSessionConfig config)
    : config_(std::move(config)) {
  trace_.reserve(64U);
}

RuntimeSession::~RuntimeSession() {
  if (state_ != RuntimeSessionState::Closed) (void)shutdown();
}

ResourceResult<std::unique_ptr<RuntimeSession>> RuntimeSession::start(
    const std::filesystem::path& bundle_manifest, RuntimeSessionConfig config) {
  try {
    auto mounted = BundleMount::open_bundle(bundle_manifest);
    if (!mounted) {
      return ResourceResult<std::unique_ptr<RuntimeSession>>::failure(
          mounted.error());
    }
    return start_mounted_for_test(std::move(mounted.value()), std::move(config));
  } catch (const std::bad_alloc&) {
    return ResourceResult<std::unique_ptr<RuntimeSession>>::failure(session_error(
        ResourceErrorCode::AllocationFailed,
        "RuntimeSession start allocation failed"));
  } catch (...) {
    return ResourceResult<std::unique_ptr<RuntimeSession>>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession start caught an internal exception"));
  }
}

ResourceResult<std::unique_ptr<RuntimeSession>>
RuntimeSession::start_mounted_for_test(std::shared_ptr<MountedBundle> bundle,
                                      RuntimeSessionConfig config) {
  try {
    auto session = std::unique_ptr<RuntimeSession>(
        new RuntimeSession(std::move(config)));
    auto initialized = session->initialize(std::move(bundle));
    if (!initialized) {
      return ResourceResult<std::unique_ptr<RuntimeSession>>::failure(
          initialized.error());
    }
    return ResourceResult<std::unique_ptr<RuntimeSession>>::success(
        std::move(session));
  } catch (const std::bad_alloc&) {
    return ResourceResult<std::unique_ptr<RuntimeSession>>::failure(session_error(
        ResourceErrorCode::AllocationFailed,
        "RuntimeSession owner allocation failed"));
  } catch (...) {
    return ResourceResult<std::unique_ptr<RuntimeSession>>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession owner caught an internal exception"));
  }
}

ResourceResult<void> RuntimeSession::initialize(
    std::shared_ptr<MountedBundle> bundle) {
  state_ = RuntimeSessionState::Starting;
  record(RuntimeSessionEvent::MountBegin);
  if (bundle == nullptr || bundle->packages.empty()) {
    state_ = RuntimeSessionState::Error;
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::PackageMissing,
        "RuntimeSession requires a completely mounted package family"));
  }
  bundle_ = std::move(bundle);
  ++mount_generation_;
  manager_ = std::make_unique<ResourceManager>(
      bundle_, config_.telemetry, config_.budget_gate, config_.fault_injector);
  ++catalog_generation_;
  baseline_ = manager_->snapshot();
  record(RuntimeSessionEvent::MountCommit);
  record(RuntimeSessionEvent::PinBegin);
  for (const MountedPackage& package : bundle_->packages) {
    for (const ResourceDescriptor& descriptor : package.resources) {
      if (!descriptor.pin_on_mount()) continue;
      AcquirePolicy policy;
      policy.expected_kind = descriptor.kind;
      auto lease = manager_->acquire(descriptor.id, policy);
      if (!lease) {
        state_ = RuntimeSessionState::Error;
        return ResourceResult<void>::failure(lease.error());
      }
      mount_pins_.push_back(descriptor.id);
      auto released = lease.value().release();
      if (!released) {
        state_ = RuntimeSessionState::Error;
        return released;
      }
    }
  }
  record(RuntimeSessionEvent::PinCommit);
  manager_->set_stage(ResourceStage::Menu);
  auto initial = manager_->begin_menu_transition(config_.menu_group);
  if (!initial) {
    state_ = RuntimeSessionState::Error;
    return ResourceResult<void>::failure(initial.error());
  }
  auto committed = initial.value().commit();
  if (!committed) {
    state_ = RuntimeSessionState::Error;
    return committed;
  }
  state_ = RuntimeSessionState::Menu;
  return ResourceResult<void>::success();
}

ResourceResult<ResourceLease> RuntimeSession::acquire(
    const ResourceId& id, ResourceKind kind) {
  try {
    if (manager_ == nullptr || (state_ != RuntimeSessionState::Menu &&
                                state_ != RuntimeSessionState::Level &&
                                state_ != RuntimeSessionState::Transitioning)) {
      return ResourceResult<ResourceLease>::failure(session_error(
          ResourceErrorCode::GroupBusy,
          "RuntimeSession is not accepting resource acquires"));
    }
    AcquirePolicy policy;
    policy.expected_kind = kind;
    return manager_->acquire(id, policy);
  } catch (const std::bad_alloc&) {
    return ResourceResult<ResourceLease>::failure(session_error(
        ResourceErrorCode::AllocationFailed,
        "RuntimeSession acquire allocation failed"));
  } catch (...) {
    return ResourceResult<ResourceLease>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession acquire caught an internal exception"));
  }
}

ResourceResult<void> RuntimeSession::transition(
    std::uint32_t target_group, TransitionKind kind,
    RuntimeSessionState target_state, const RuntimePrepare& prepare) {
  try {
    if (manager_ == nullptr || (state_ != RuntimeSessionState::Menu &&
                                state_ != RuntimeSessionState::Level)) {
      return ResourceResult<void>::failure(session_error(
          ResourceErrorCode::GroupBusy,
          "RuntimeSession cannot begin a transition in its current state"));
    }
    const RuntimeSessionState old_state = state_;
    state_ = RuntimeSessionState::Transitioning;
    record(RuntimeSessionEvent::TransitionBegin);
    auto token = manager_->begin_transition(target_group, kind);
    if (!token) {
      state_ = old_state;
      record(RuntimeSessionEvent::TransitionRollback);
      return ResourceResult<void>::failure(token.error());
    }
    if (prepare) {
      ResourceResult<void> prepared = ResourceResult<void>::failure(session_error(
          ResourceErrorCode::Internal,
          "RuntimeSession transition prepare did not run"));
      try {
        prepared = prepare(*manager_);
      } catch (...) {
        prepared = ResourceResult<void>::failure(session_error(
            ResourceErrorCode::Internal,
            "RuntimeSession transition prepare callback threw"));
      }
      if (!prepared) {
        token.value().cancel();
        state_ = old_state;
        record(RuntimeSessionEvent::TransitionRollback);
        return prepared;
      }
    }
    auto committed = token.value().commit();
    if (!committed) {
      token.value().cancel();
      state_ = old_state;
      record(RuntimeSessionEvent::TransitionRollback);
      return committed;
    }
    state_ = target_state;
    manager_->set_stage(target_state == RuntimeSessionState::Level
                            ? ResourceStage::FirstLevel
                            : ResourceStage::Menu);
    record(RuntimeSessionEvent::TransitionCommit);
    return ResourceResult<void>::success();
  } catch (const std::bad_alloc&) {
    state_ = RuntimeSessionState::Error;
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::AllocationFailed,
        "RuntimeSession transition allocation failed"));
  } catch (...) {
    state_ = RuntimeSessionState::Error;
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession transition caught an internal exception"));
  }
}

ResourceResult<void> RuntimeSession::enter_menu(
    std::uint32_t menu_group, const RuntimePrepare& prepare) {
  return transition(menu_group, TransitionKind::Menu,
                    RuntimeSessionState::Menu, prepare);
}

ResourceResult<void> RuntimeSession::enter_level(
    std::uint32_t level_group, const RuntimePrepare& prepare) {
  return transition(level_group, TransitionKind::World,
                    RuntimeSessionState::Level, prepare);
}

ResourceResult<void> RuntimeSession::save_or_load(
    const RuntimePrepare& operation) {
  try {
    if (!operation) {
      return ResourceResult<void>::failure(session_error(
          ResourceErrorCode::GroupBusy,
          "RuntimeSession cannot begin save/load in its current state"));
    }
    auto begun = begin_save_load();
    if (!begun) return begun;
    ResourceResult<void> result = ResourceResult<void>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession save/load callback did not run"));
    try {
      result = operation(*manager_);
    } catch (...) {
      result = ResourceResult<void>::failure(session_error(
          ResourceErrorCode::Internal,
          "RuntimeSession save/load callback threw"));
    }
    if (!result) {
      (void)finish_save_load(false);
      return result;
    }
    return finish_save_load(true);
  } catch (const std::bad_alloc&) {
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::AllocationFailed,
        "RuntimeSession save/load allocation failed"));
  } catch (...) {
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession save/load caught an internal exception"));
  }
}

ResourceResult<void> RuntimeSession::begin_save_load() {
  try {
    if (manager_ == nullptr || save_load_token_.has_value() ||
        (state_ != RuntimeSessionState::Menu &&
         state_ != RuntimeSessionState::Level)) {
      return ResourceResult<void>::failure(session_error(
          ResourceErrorCode::GroupBusy,
          "RuntimeSession cannot begin save/load in its current state"));
    }
    record(RuntimeSessionEvent::SaveBegin);
    auto token = manager_->begin_save_load();
    if (!token) {
      record(RuntimeSessionEvent::SaveRollback);
      return ResourceResult<void>::failure(token.error());
    }
    save_load_token_.emplace(std::move(token.value()));
    return ResourceResult<void>::success();
  } catch (const std::bad_alloc&) {
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::AllocationFailed,
        "RuntimeSession save/load begin allocation failed"));
  } catch (...) {
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession save/load begin caught an internal exception"));
  }
}

ResourceResult<void> RuntimeSession::finish_save_load(bool commit) {
  try {
    if (!save_load_token_.has_value()) {
      return ResourceResult<void>::failure(session_error(
          ResourceErrorCode::GroupBusy,
          "RuntimeSession has no active save/load transaction"));
    }
    if (!commit) {
      save_load_token_->cancel();
      save_load_token_.reset();
      record(RuntimeSessionEvent::SaveRollback);
      return ResourceResult<void>::success();
    }
    auto result = save_load_token_->commit();
    if (!result) save_load_token_->cancel();
    save_load_token_.reset();
    record(result ? RuntimeSessionEvent::SaveCommit
                  : RuntimeSessionEvent::SaveRollback);
    return result;
  } catch (const std::bad_alloc&) {
    if (save_load_token_.has_value()) save_load_token_->cancel();
    save_load_token_.reset();
    record(RuntimeSessionEvent::SaveRollback);
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::AllocationFailed,
        "RuntimeSession save/load finish allocation failed"));
  } catch (...) {
    if (save_load_token_.has_value()) save_load_token_->cancel();
    save_load_token_.reset();
    record(RuntimeSessionEvent::SaveRollback);
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession save/load finish caught an internal exception"));
  }
}

ResourceResult<void> RuntimeSession::quiesce() {
  record(RuntimeSessionEvent::Quiesce);
  if (!config_.quiesce_clients) return ResourceResult<void>::success();
  try {
    return config_.quiesce_clients();
  } catch (...) {
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession client quiesce callback threw"));
  }
}

ResourceResult<void> RuntimeSession::suspend() {
  if (state_ != RuntimeSessionState::Menu &&
      state_ != RuntimeSessionState::Level) {
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::GroupBusy,
        "RuntimeSession can suspend only from a stable state"));
  }
  auto stopped = quiesce();
  if (!stopped) return stopped;
  resume_state_ = state_;
  state_ = RuntimeSessionState::Suspended;
  record(RuntimeSessionEvent::Suspend);
  return ResourceResult<void>::success();
}

ResourceResult<void> RuntimeSession::resume() {
  if (state_ != RuntimeSessionState::Suspended) {
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::GroupBusy,
        "RuntimeSession is not suspended"));
  }
  state_ = resume_state_;
  record(RuntimeSessionEvent::Resume);
  return ResourceResult<void>::success();
}

ResourceResult<void> RuntimeSession::shutdown() {
  try {
    if (state_ == RuntimeSessionState::Closed) {
      return ResourceResult<void>::success();
    }
    const RuntimeSessionState old_state = state_;
    state_ = RuntimeSessionState::ShuttingDown;
    record(RuntimeSessionEvent::ShutdownBegin);
    if (save_load_token_.has_value()) {
      save_load_token_->cancel();
      save_load_token_.reset();
      record(RuntimeSessionEvent::SaveRollback);
    }
    auto stopped = quiesce();
    if (!stopped) {
      state_ = old_state;
      return stopped;
    }
    if (manager_ != nullptr && manager_->snapshot().leases != 0U) {
      state_ = old_state;
      return ResourceResult<void>::failure(session_error(
          ResourceErrorCode::GroupBusy,
          "RuntimeSession shutdown has outstanding leases"));
    }
    if (manager_ != nullptr) {
      for (auto iterator = mount_pins_.rbegin(); iterator != mount_pins_.rend();
           ++iterator) {
        auto released = manager_->unpin(*iterator, PinOwner::Mount);
        if (!released) {
          state_ = old_state;
          return released;
        }
      }
      mount_pins_.clear();
      manager_->purge_zero_reference();
      closed_ = manager_->snapshot();
      if (!ledger_at_baseline()) {
        state_ = old_state;
        return ResourceResult<void>::failure(session_error(
            ResourceErrorCode::AccountingOverrun,
            "RuntimeSession shutdown ledger did not return to baseline"));
      }
    }
    manager_.reset();
    bundle_.reset();
    state_ = RuntimeSessionState::Closed;
    record(RuntimeSessionEvent::ShutdownCommit);
    return ResourceResult<void>::success();
  } catch (const std::bad_alloc&) {
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::AllocationFailed,
        "RuntimeSession shutdown allocation failed"));
  } catch (...) {
    return ResourceResult<void>::failure(session_error(
        ResourceErrorCode::Internal,
        "RuntimeSession shutdown caught an internal exception"));
  }
}

bool RuntimeSession::ledger_at_baseline() const noexcept {
  const ResourceMemorySnapshot current = manager_ != nullptr
                                             ? manager_->snapshot()
                                             : closed_;
  return current.entries == 0U && current.leases == 0U && current.pins == 0U &&
         current.dependents == 0U && current.payload_bytes == 0U &&
         current.allocation_overhead_bytes == 0U &&
         current.pool_bytes == baseline_.pool_bytes &&
         current.backend_bytes == baseline_.backend_bytes;
}

RuntimeSessionSnapshot RuntimeSession::snapshot() const noexcept {
  RuntimeSessionSnapshot result;
  result.state = state_;
  result.resources = manager_ != nullptr ? manager_->snapshot() : closed_;
  result.mounted_packages = bundle_ == nullptr ? 0U : bundle_->packages.size();
  result.trace_events = trace_.size();
  result.mount_generation = mount_generation_;
  result.catalog_generation = catalog_generation_;
  result.ledger_at_baseline = ledger_at_baseline();
  return result;
}

void RuntimeSession::record(RuntimeSessionEvent event) {
  trace_.push_back(event);
}

}  // namespace cth3ds
