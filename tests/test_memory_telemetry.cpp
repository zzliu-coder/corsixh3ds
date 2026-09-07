#include "test_framework.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

#include "cth3ds/memory_telemetry.hpp"

namespace {

struct FakeAllocator {
  std::size_t maximum_success{0U};
  std::size_t live_allocations{0U};
  std::size_t peak_live_allocations{0U};
};

void* fake_allocate(std::size_t bytes, void* context) noexcept {
  auto& allocator = *static_cast<FakeAllocator*>(context);
  if (bytes > allocator.maximum_success) {
    return nullptr;
  }
  ++allocator.live_allocations;
  if (allocator.live_allocations > allocator.peak_live_allocations) {
    allocator.peak_live_allocations = allocator.live_allocations;
  }
  return &allocator;
}

void fake_release(void*, void* context) noexcept {
  auto& allocator = *static_cast<FakeAllocator*>(context);
  --allocator.live_allocations;
}

}  // namespace

TEST(heap_available_includes_unclaimed_environment_heap) {
  EXPECT_EQ(cth3ds::estimate_heap_available(48U, 20U, 7U), std::uint64_t{35U});
}

TEST(heap_available_is_clamped_and_handles_oversized_arena) {
  EXPECT_EQ(cth3ds::estimate_heap_available(48U, 60U, 9U), std::uint64_t{9U});
  EXPECT_EQ(cth3ds::estimate_heap_available(48U, 20U, 99U), std::uint64_t{48U});
}

TEST(memory_gate_contract_matches_frozen_stage_limits) {
  const auto menu = cth3ds::memory_gate_policy(cth3ds::MemoryGate::MenuStable);
  EXPECT_EQ(menu.maximum_heap_used, 36U * cth3ds::kMiB);
  EXPECT_EQ(menu.minimum_heap_available, 16U * cth3ds::kMiB);
  EXPECT_EQ(menu.probe_bytes, std::size_t{8U * cth3ds::kMiB});
  EXPECT_EQ(menu.probe_reserve_bytes, std::size_t{4U * cth3ds::kMiB});
  const auto pass = cth3ds::evaluate_memory_gate(
      52U * cth3ds::kMiB, 16U * cth3ds::kMiB,
      8U * cth3ds::kMiB, menu);
  EXPECT_TRUE(pass.pass());
  const auto fail = cth3ds::evaluate_memory_gate(
      52U * cth3ds::kMiB, 16U * cth3ds::kMiB - 1U,
      8U * cth3ds::kMiB, menu);
  EXPECT_FALSE(fail.pass());
  const auto wrong_linear = cth3ds::evaluate_memory_gate(
      52U * cth3ds::kMiB, 16U * cth3ds::kMiB,
      8U * cth3ds::kMiB - 1U, menu);
  EXPECT_FALSE(wrong_linear.pass());
  const auto short_heap = cth3ds::evaluate_memory_gate(
      52U * cth3ds::kMiB - 1U, 16U * cth3ds::kMiB,
      8U * cth3ds::kMiB, menu);
  EXPECT_FALSE(short_heap.pass());
}

TEST(resource_pool_names_and_limits_are_contract_terms) {
  EXPECT_EQ(cth3ds::resource_pool_limit(cth3ds::ResourcePool::Audio),
            3U * cth3ds::kMiB);
  EXPECT_EQ(cth3ds::resource_pool_limit(cth3ds::ResourcePool::Sprite),
            8U * cth3ds::kMiB);
  EXPECT_EQ(cth3ds::resource_pool_limit(cth3ds::ResourcePool::Texture),
            6U * cth3ds::kMiB);
  EXPECT_EQ(cth3ds::resource_pool_limit(cth3ds::ResourcePool::LanguageFont),
            3U * cth3ds::kMiB);
  EXPECT_EQ(cth3ds::kResourcePoolNames[0], std::string_view{"audio"});
  EXPECT_EQ(cth3ds::kResourcePoolNames[3], std::string_view{"language_font"});
}

TEST(every_resource_pool_has_exact_cap_minus_one_cap_and_cap_plus_one_rules) {
  for (std::size_t index = 0U;
       index < static_cast<std::size_t>(cth3ds::ResourcePool::Count); ++index) {
    const auto pool = static_cast<cth3ds::ResourcePool>(index);
    const std::uint64_t cap = cth3ds::resource_pool_limit(pool);
    EXPECT_TRUE(cap > 0U);
    EXPECT_TRUE(cth3ds::allocation_fits_pool_budget(0U, cap - 1U, cap));
    EXPECT_TRUE(cth3ds::allocation_fits_pool_budget(0U, cap, cap));
    EXPECT_FALSE(cth3ds::allocation_fits_pool_budget(0U, cap + 1U, cap));
    EXPECT_FALSE(cth3ds::allocation_fits_pool_budget(cap + 1U, 0U, cap));
  }
}

TEST(contiguous_probe_keeps_reserve_and_returns_verified_lower_bound) {
  FakeAllocator allocator{5U * 1024U * 1024U};
  cth3ds::ContiguousProbePolicy policy;
  policy.granularity_bytes = 1024U * 1024U;
  policy.minimum_success_bytes = 2U * 1024U * 1024U;
  policy.reserve_bytes = 2U * 1024U * 1024U;
  policy.maximum_probe_bytes = 8U * 1024U * 1024U;

  const auto result = cth3ds::probe_largest_contiguous(
      12U * 1024U * 1024U, policy, fake_allocate, fake_release, &allocator);
  EXPECT_EQ(result.verified_bytes, std::size_t{5U * 1024U * 1024U});
  EXPECT_EQ(result.attempted_limit_bytes, std::size_t{8U * 1024U * 1024U});
  EXPECT_TRUE(result.met_minimum);
  EXPECT_TRUE(result.capped);
  EXPECT_EQ(allocator.live_allocations, std::size_t{0U});
  EXPECT_EQ(allocator.peak_live_allocations, std::size_t{1U});
}

TEST(contiguous_probe_refuses_to_spend_the_safety_reserve) {
  FakeAllocator allocator{64U * 1024U * 1024U};
  cth3ds::ContiguousProbePolicy policy;
  policy.reserve_bytes = 2U * 1024U * 1024U;
  const auto result = cth3ds::probe_largest_contiguous(
      policy.reserve_bytes, policy, fake_allocate, fake_release, &allocator);
  EXPECT_EQ(result.attempts, std::size_t{0U});
  EXPECT_EQ(result.verified_bytes, std::size_t{0U});
  EXPECT_FALSE(result.met_minimum);
}

TEST(contiguous_probe_touches_every_4096_byte_page_and_last_byte) {
  std::vector<std::uint8_t> bytes(3U * 4096U + 17U, 0U);
  EXPECT_TRUE(cth3ds::touch_probe_pages(bytes.data(), bytes.size(), 4096U));
  EXPECT_EQ(bytes[0], std::uint8_t{0xA5U});
  EXPECT_EQ(bytes[4096U], std::uint8_t{0xA4U});
  EXPECT_EQ(bytes[8192U], std::uint8_t{0xA7U});
  EXPECT_EQ(bytes[12288U], std::uint8_t{0xA6U});
  EXPECT_TRUE(bytes.back() != std::uint8_t{0U});
}

TEST(memory_checkpoint_and_resource_names_are_bounded) {
  EXPECT_TRUE(cth3ds::is_memory_checkpoint("language_discovery"));
  EXPECT_TRUE(cth3ds::is_memory_checkpoint("sound_archive_copy"));
  EXPECT_TRUE(cth3ds::is_memory_checkpoint("vspr_decode"));
  EXPECT_TRUE(cth3ds::is_memory_checkpoint("first_level"));
  EXPECT_FALSE(cth3ds::is_memory_checkpoint("arbitrary_dynamic_name"));
  EXPECT_EQ(cth3ds::resource_memory_category("vspr_data"),
            cth3ds::ResourceMemoryCategory::VsprData);
  EXPECT_EQ(cth3ds::resource_memory_category("unknown"),
            cth3ds::ResourceMemoryCategory::Other);
  EXPECT_EQ(cth3ds::checkpoint_resource_category("sound_archive_copy"),
            cth3ds::ResourceMemoryCategory::SoundArchive);
  EXPECT_EQ(cth3ds::checkpoint_resource_category("vspr_decode"),
            cth3ds::ResourceMemoryCategory::VsprDecoded);
}

TEST(memory_actual_samples_never_add_lua_or_resource_subsets_to_heap) {
  cth3ds::MemoryTelemetry t;
  cth3ds::MemorySample s{100, 52U*cth3ds::kMiB, 30U*cth3ds::kMiB,
    25U*cth3ds::kMiB, 5U*cth3ds::kMiB, 8U*cth3ds::kMiB, 6U*cth3ds::kMiB,
    10U*cth3ds::kMiB, true};
  auto observation = cth3ds::memory_observation(s, cth3ds::MemoryGate::Operation,
    "audio", "decode-after", "clip:17", 1024, true, 2048, true);
  EXPECT_TRUE(t.observe("sound_decode", observation));
  const auto& a = t.checkpoints()[4];
  EXPECT_EQ(a.maximum_heap_used, 25U*cth3ds::kMiB);
  EXPECT_EQ(a.minimum_heap_available, 27U*cth3ds::kMiB);
  EXPECT_EQ(a.maximum_lua_bytes, 10U*cth3ds::kMiB);
  EXPECT_EQ(a.maximum_known_held_bytes, 2048U);
  EXPECT_EQ(a.unknown_temporary_samples, 1U);
  observation.sample.timestamp_us = 200; observation.held_bytes = 0;
  observation.sample.fordblks = 6U*cth3ds::kMiB;
  EXPECT_TRUE(t.observe("sound_decode", observation));
  EXPECT_EQ(a.latest.held_bytes, 0U); EXPECT_TRUE(a.latest.held_known);
  EXPECT_EQ(a.maximum_heap_used, 25U*cth3ds::kMiB);
  EXPECT_EQ(a.first_us, 100U); EXPECT_EQ(a.last_us, 200U); EXPECT_EQ(a.samples, 2U);
}
TEST(memory_failed_request_identity_survives_release_and_unknown_is_explicit) {
  cth3ds::MemoryTelemetry t; cth3ds::MemorySample sample;
  sample.timestamp_us = 4;
  auto o = cth3ds::memory_observation(sample, cth3ds::MemoryGate::Operation,
      "save", "allocation-failed", "serialized-state", 4000001, true, 0, false, true);
  EXPECT_TRUE(t.observe("save", o));
  o.allocation_failed = false; o.requested_known = false; o.sample.timestamp_us = 5;
  EXPECT_TRUE(t.observe("release", o));
  EXPECT_TRUE(t.has_failure());
  EXPECT_EQ(t.last_failure().requested_bytes, 4000001U);
  EXPECT_EQ(std::string_view(t.last_failure().resource.data()), std::string_view("serialized-state"));
  EXPECT_FALSE(t.last_failure().held_known); EXPECT_FALSE(t.last_failure().sample.lua_known);
  EXPECT_FALSE(t.observe("not-a-site", o));
  o.sample.timestamp_us = 3; EXPECT_FALSE(t.observe("release", o));
  EXPECT_EQ(t.invalid_events(), 2U);
  t.clear(); EXPECT_FALSE(t.has_failure()); EXPECT_EQ(t.invalid_events(), 0U);
  EXPECT_TRUE(sizeof(t) <= 16U * 1024U);
}
TEST(memory_resource_identity_copy_is_bounded_and_reports_truncation) {
  auto o = cth3ds::memory_observation({}, cth3ds::MemoryGate::MenuStable,
      "menu", "stable", std::string(200, 'x'));
  EXPECT_TRUE(o.identity_truncated); EXPECT_EQ(o.resource.back(), '\0');
}
TEST(memory_gate_probe_uses_explicit_stage_in_probe_and_error_text) {
  for (const auto gate : {cth3ds::MemoryGate::MenuStable, cth3ds::MemoryGate::LevelStable,
                         cth3ds::MemoryGate::Operation}) {
    const auto p = cth3ds::memory_gate_probe_policy(gate);
    FakeAllocator allocator{p.minimum_success_bytes - p.granularity_bytes};
    const auto result = cth3ds::probe_largest_contiguous(20U * cth3ds::kMiB, p,
        fake_allocate, fake_release, &allocator);
    EXPECT_FALSE(result.met_minimum); EXPECT_EQ(allocator.live_allocations, 0U);
    EXPECT_EQ(result.attempted_limit_bytes, p.maximum_probe_bytes);
    char message[256]; cth3ds::format_memory_gate_probe(message, sizeof(message), gate, result);
    const std::string text(message);
    EXPECT_TRUE(text.find(std::string(cth3ds::memory_gate_name(gate))) != std::string::npos);
    EXPECT_TRUE(text.find("required_probe=" + std::to_string(p.minimum_success_bytes)) != std::string::npos);
    EXPECT_TRUE(text.find("result=FAIL") != std::string::npos);
  }
}
