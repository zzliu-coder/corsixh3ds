#include <iostream>
#include <optional>
#include <string>

#include "cth3ds/resource_manager.hpp"
#include "cth3ds/runtime_session.hpp"

namespace {

std::optional<cth3ds::ResourceKind> parse_kind(const std::string& value) {
  using cth3ds::ResourceKind;
  if (value == "AUDIO_BANK") return ResourceKind::AudioBank;
  if (value == "LANGUAGE_BUNDLE") return ResourceKind::LanguageBundle;
  if (value == "SPRITE_SHEET") return ResourceKind::SpriteSheet;
  if (value == "UI_BITMAP") return ResourceKind::UiBitmap;
  if (value == "FONT_ATLAS") return ResourceKind::FontAtlas;
  if (value == "FONT_MAP") return ResourceKind::FontMap;
  if (value == "PALETTE") return ResourceKind::Palette;
  if (value == "OPAQUE_BLOB") return ResourceKind::OpaqueBlob;
  return std::nullopt;
}

int fail(const cth3ds::ResourceError& error) {
  std::cerr << cth3ds::resource_error_name(error.code) << ": " << error.message
            << '\n';
  return 2;
}

int run_session_cycle(const std::string& bundle_path,
                      const cth3ds::ResourceId& id,
                      cth3ds::ResourceKind kind, std::size_t cycles) {
  auto started = cth3ds::RuntimeSession::start(bundle_path);
  if (!started) return fail(started.error());
  auto& session = *started.value();
  for (std::size_t cycle = 0U; cycle < cycles; ++cycle) {
    auto lease = session.acquire(id, kind);
    if (!lease) return fail(lease.error());
    if (lease.value().bytes().data == nullptr ||
        lease.value().bytes().size == 0U) {
      std::cerr << "E_INTERNAL: required UI lease has no bytes\n";
      return 2;
    }
    auto result = lease.value().release();
    if (!result) return fail(result.error());
    result = session.enter_level(2U);
    if (!result) return fail(result.error());
    result = session.begin_save_load();
    if (!result) return fail(result.error());
    result = session.finish_save_load(true);
    if (!result) return fail(result.error());
    result = session.enter_menu(1U);
    if (!result) return fail(result.error());
    result = session.suspend();
    if (!result) return fail(result.error());
    result = session.resume();
    if (!result) return fail(result.error());
  }
  auto result = session.shutdown();
  if (!result) return fail(result.error());
  const auto closed = session.snapshot();
  if (!closed.ledger_at_baseline || closed.mounted_packages != 0U ||
      closed.resources.entries != 0U || closed.resources.leases != 0U ||
      closed.resources.pins != 0U) {
    std::cerr << "E_ACCOUNTING_OVERRUN: session did not close at baseline\n";
    return 2;
  }
  std::cout << "session_cycles=" << cycles
            << " production_mounts=1 shutdowns=1"
            << " ledger=baseline packages=0 entries=0 leases=0 pins=0\n";
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "usage: cth3ds-runtime-probe mount BUNDLE [RESOURCE_ID KIND]\n"
                 "       cth3ds-runtime-probe session BUNDLE RESOURCE_ID KIND [CYCLES]\n"
                 "       cth3ds-runtime-probe stream BUNDLE RESOURCE_ID KIND OFFSET BYTES\n";
    return 64;
  }
  const std::string command = argv[1];
  if (command == "session") {
    if (argc != 5 && argc != 6) return 64;
    cth3ds::ResourceId id{};
    const auto kind = parse_kind(argv[4]);
    if (!cth3ds::parse_resource_id_hex(argv[3], id) || !kind) return 64;
    std::size_t cycles = 1U;
    if (argc == 6) {
      try {
        cycles = static_cast<std::size_t>(std::stoull(argv[5]));
      } catch (...) {
        return 64;
      }
      if (cycles == 0U) return 64;
    }
    return run_session_cycle(argv[2], id, *kind, cycles);
  }
  if (command == "stream") {
    if (argc != 7) return 64;
    cth3ds::ResourceId id{};
    const auto kind = parse_kind(argv[4]);
    if (!cth3ds::parse_resource_id_hex(argv[3], id) || !kind) return 64;
    std::uint64_t offset = 0U;
    std::size_t bytes = 0U;
    try {
      offset = std::stoull(argv[5]);
      bytes = static_cast<std::size_t>(std::stoull(argv[6]));
    } catch (...) {
      return 64;
    }
    auto mounted = cth3ds::BundleMount::open_bundle(argv[2]);
    if (!mounted) return fail(mounted.error());
    cth3ds::ResourceManager manager(mounted.value());
    std::size_t observed = 0U;
    const auto read = manager.read_stream_range(
        id, *kind, offset, bytes,
        [&observed](cth3ds::ByteView view) {
          observed = view.size;
          return cth3ds::ResourceResult<void>::success();
        });
    if (!read) return fail(read.error());
    const auto snapshot = manager.snapshot();
    std::cout << "stream_bytes=" << observed
              << " entries=" << snapshot.entries
              << " payload=" << snapshot.payload_bytes
              << " audio=" << snapshot.pool_bytes[static_cast<std::size_t>(
                     cth3ds::ResourcePool::Audio)]
              << " sprite=" << snapshot.pool_bytes[static_cast<std::size_t>(
                     cth3ds::ResourcePool::Sprite)]
              << '\n';
    return 0;
  }
  if (command != "mount") return 64;
  auto mounted = cth3ds::BundleMount::open_bundle(argv[2]);
  if (!mounted) return fail(mounted.error());
  std::cout << "bundle=" << cth3ds::sha256_hex(mounted.value()->bundle_sha256)
            << " packages=" << mounted.value()->packages.size()
            << " resources=" << mounted.value()->catalog.size() << '\n';
  if (argc == 3) return 0;
  if (argc != 5) return 64;
  cth3ds::ResourceId id{};
  const auto kind = parse_kind(argv[4]);
  if (!cth3ds::parse_resource_id_hex(argv[3], id) || !kind) return 64;
  const auto descriptor = mounted.value()->catalog.find(id, *kind);
  if (!descriptor) return fail(descriptor.error());
  std::cout << "resource=" << argv[3]
            << " stored=" << descriptor.value()->stored_size
            << " decoded=" << descriptor.value()->decoded_size
            << " streamable=" << (descriptor.value()->streamable() ? 1 : 0)
            << '\n';
  return 0;
}
