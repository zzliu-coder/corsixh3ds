#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "cth3ds/memory_telemetry.hpp"
#include "cth3ds/sha256.hpp"

namespace cth3ds {

inline constexpr std::uint32_t kTh3dsRuntimeAbi = 1U;
inline constexpr std::uint32_t kTh3dsRequiredFlag = 1U;
inline constexpr std::uint32_t kTh3dsPinOnMountFlag = 2U;
inline constexpr std::uint32_t kTh3dsStreamableFlag = 4U;

using ResourceId = std::array<std::uint8_t, 16>;
using PackageId = std::array<std::uint8_t, 16>;

enum class ResourceErrorCode : std::uint16_t {
  None,
  Io,
  LegacyAuditPack,
  FormatMagic,
  HeaderReserved,
  FormatMajor,
  FormatMinor,
  UnsupportedFeature,
  UnsupportedCodec,
  FormatBounds,
  FormatCanonicalJson,
  RuntimeAbi,
  HashBundle,
  HashContainer,
  HashCatalog,
  HashPayload,
  HashResource,
  HashDecoded,
  SourceSetMixed,
  IdDuplicate,
  PackageMissing,
  PackageMismatch,
  ResourceNotFound,
  KindMismatch,
  StreamRequired,
  BudgetContract,
  BudgetAudio,
  BudgetSprite,
  BudgetTexture,
  BudgetLanguageFont,
  BudgetMetadata,
  BudgetScratch,
  AllocationFailed,
  AccountingOverrun,
  RefcountCorrupt,
  ScratchBusy,
  GroupBusy,
  TransitionReserve,
  SaveReserve,
  Internal,
};

struct ResourceError {
  ResourceErrorCode code{ResourceErrorCode::None};
  std::string message{};
  ResourceId resource_id{};

  [[nodiscard]] explicit operator bool() const noexcept {
    return code != ResourceErrorCode::None;
  }
};

template <typename T>
class ResourceResult {
 public:
  static ResourceResult success(T value) {
    ResourceResult result;
    result.value_.emplace(std::move(value));
    return result;
  }
  static ResourceResult failure(ResourceError error) {
    ResourceResult result;
    result.error_ = std::move(error);
    return result;
  }

  [[nodiscard]] bool ok() const noexcept { return value_.has_value(); }
  [[nodiscard]] explicit operator bool() const noexcept { return ok(); }
  [[nodiscard]] const ResourceError& error() const noexcept { return error_; }
  [[nodiscard]] T& value() & { return *value_; }
  [[nodiscard]] const T& value() const& { return *value_; }
  [[nodiscard]] T&& value() && { return std::move(*value_); }

 private:
  std::optional<T> value_{};
  ResourceError error_{};
};

template <>
class ResourceResult<void> {
 public:
  static ResourceResult success() { return ResourceResult(true, {}); }
  static ResourceResult failure(ResourceError error) {
    return ResourceResult(false, std::move(error));
  }
  [[nodiscard]] bool ok() const noexcept { return ok_; }
  [[nodiscard]] explicit operator bool() const noexcept { return ok(); }
  [[nodiscard]] const ResourceError& error() const noexcept { return error_; }

 private:
  ResourceResult(bool ok, ResourceError error)
      : ok_(ok), error_(std::move(error)) {}
  bool ok_{false};
  ResourceError error_{};
};

enum class PackageRole : std::uint8_t { Core = 1, Language = 2, Level = 3 };

enum class ResourceKind : std::uint16_t {
  AudioBank = 1,
  LanguageBundle = 2,
  SpriteSheet = 3,
  UiBitmap = 4,
  FontAtlas = 5,
  FontMap = 6,
  Palette = 7,
  OpaqueBlob = 255,
};

enum class ResourceCodec : std::uint16_t { None = 0, Zlib = 1, DspAdpcm = 2 };

struct ByteView {
  const std::uint8_t* data{nullptr};
  std::size_t size{0U};
};

struct MutableByteView {
  std::uint8_t* data{nullptr};
  std::size_t size{0U};
};

struct ResourceDescriptor {
  ResourceId id{};
  ResourceKind kind{ResourceKind::OpaqueBlob};
  ResourceCodec codec{ResourceCodec::None};
  std::uint32_t flags{0U};
  std::uint32_t group_id{0U};
  std::uint32_t alignment{0U};
  std::uint64_t data_offset{0U};
  std::uint32_t stored_size{0U};
  std::uint32_t decoded_size{0U};
  std::uint64_t metadata_offset{0U};
  std::uint32_t metadata_size{0U};
  std::uint16_t dependency_count{0U};
  std::vector<ResourceId> dependencies{};
  Sha256Digest stored_sha256{};
  Sha256Digest decoded_sha256{};
  std::size_t package_index{0U};

  [[nodiscard]] bool required() const noexcept {
    return (flags & kTh3dsRequiredFlag) != 0U;
  }
  [[nodiscard]] bool pin_on_mount() const noexcept {
    return (flags & kTh3dsPinOnMountFlag) != 0U;
  }
  [[nodiscard]] bool streamable() const noexcept {
    return (flags & kTh3dsStreamableFlag) != 0U;
  }
};

struct PackageDependency {
  PackageId package_id{};
  Sha256Digest container_sha256{};
};

struct ResourceGroup {
  std::uint32_t id{0U};
  std::string name{};
  bool required{false};
  std::uint64_t decoded_ceiling_bytes{0U};
  std::vector<ResourceId> resource_ids{};
};

struct PackageBudgets {
  std::array<std::uint64_t, static_cast<std::size_t>(ResourcePool::Count)>
      bytes{};
};

struct MountedPackage {
  std::filesystem::path path{};
  PackageRole role{PackageRole::Core};
  std::string name{};
  std::uint16_t format_minor{0U};
  PackageId id{};
  Sha256Digest source_set_sha256{};
  Sha256Digest container_sha256{};
  PackageBudgets budgets{};
  std::vector<PackageDependency> dependencies{};
  std::vector<ResourceGroup> groups{};
  std::vector<ResourceDescriptor> resources{};
  std::vector<std::uint8_t> metadata{};
};

class ResourceCatalog {
 public:
  [[nodiscard]] static ResourceResult<ResourceCatalog> build(
      std::vector<MountedPackage>& packages);
  [[nodiscard]] const ResourceDescriptor* find(const ResourceId& id) const noexcept;
  [[nodiscard]] ResourceResult<const ResourceDescriptor*> find(
      const ResourceId& id, ResourceKind expected_kind) const;
  [[nodiscard]] std::size_t size() const noexcept { return sorted_.size(); }

 private:
  std::vector<const ResourceDescriptor*> sorted_{};
};

struct MountedBundle {
  std::filesystem::path root{};
  std::string selected_language{};
  std::optional<std::string> fallback_language{};
  std::optional<std::string> start_level{};
  Sha256Digest bundle_sha256{};
  Sha256Digest source_set_sha256{};
  std::vector<MountedPackage> packages{};
  ResourceCatalog catalog{};
};

class BundleMount {
 public:
  [[nodiscard]] static ResourceResult<std::shared_ptr<MountedBundle>> open_bundle(
      const std::filesystem::path& bundle_manifest);
};

[[nodiscard]] ResourceResult<void> read_resource_range(
    const MountedBundle& bundle, const ResourceDescriptor& descriptor,
    std::uint64_t relative_offset, MutableByteView destination);

[[nodiscard]] std::string resource_id_hex(const ResourceId& id);
[[nodiscard]] bool parse_resource_id_hex(std::string_view value,
                                         ResourceId& id) noexcept;
[[nodiscard]] const char* resource_error_name(ResourceErrorCode code) noexcept;
[[nodiscard]] const char* resource_kind_name(ResourceKind kind) noexcept;

}  // namespace cth3ds
