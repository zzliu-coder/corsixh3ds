#include <array>
#include <string>

#include "cth3ds/sha256.hpp"
#include "cth3ds/th3ds.hpp"
#include "test_framework.hpp"

TEST(sha256_matches_fips_known_vector) {
  const std::string input = "abc";
  const auto digest = cth3ds::sha256(input.data(), input.size());
  EXPECT_EQ(cth3ds::sha256_hex(digest),
            std::string("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
}

TEST(resource_and_sha_hex_parsers_reject_noncanonical_hex) {
  cth3ds::ResourceId resource{};
  EXPECT_TRUE(cth3ds::parse_resource_id_hex(
      "00112233445566778899aabbccddeeff", resource));
  EXPECT_EQ(cth3ds::resource_id_hex(resource),
            std::string("00112233445566778899aabbccddeeff"));
  EXPECT_FALSE(cth3ds::parse_resource_id_hex(
      "00112233445566778899AABBCCDDEEFF", resource));
  cth3ds::Sha256Digest digest{};
  EXPECT_FALSE(cth3ds::parse_sha256_hex(std::string(64U, 'G'), digest));
}

TEST(runtime_error_names_are_stable_adapter_contract) {
  EXPECT_EQ(std::string(cth3ds::resource_error_name(
                cth3ds::ResourceErrorCode::LegacyAuditPack)),
            std::string("E_LEGACY_AUDIT_PACK"));
  EXPECT_EQ(std::string(cth3ds::resource_error_name(
                cth3ds::ResourceErrorCode::BudgetAudio)),
            std::string("E_BUDGET_AUDIO"));
  EXPECT_EQ(std::string(cth3ds::resource_kind_name(
                cth3ds::ResourceKind::LanguageBundle)),
            std::string("LANGUAGE_BUNDLE"));
}
