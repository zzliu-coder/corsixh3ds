#include "test_framework.hpp"

#include <string>
#include <vector>

#include "cth3ds/texture_cache.hpp"

TEST(texture_cache_evicts_least_recent_unpinned_entry) {
  cth3ds::TextureCache cache(100);
  EXPECT_TRUE(cache.insert("a", 40));
  EXPECT_TRUE(cache.insert("b", 40));
  EXPECT_TRUE(cache.touch("a"));
  EXPECT_TRUE(cache.insert("c", 40));
  EXPECT_TRUE(cache.contains("a"));
  EXPECT_FALSE(cache.contains("b"));
  EXPECT_TRUE(cache.contains("c"));
  EXPECT_EQ(cache.used_bytes(), std::size_t{80});
}

TEST(texture_cache_never_evicts_pinned_entry) {
  cth3ds::TextureCache cache(80);
  EXPECT_TRUE(cache.insert("ui", 60, true));
  EXPECT_TRUE(cache.insert("sprite", 20));
  EXPECT_FALSE(cache.insert("oversized", 30));
  EXPECT_TRUE(cache.contains("ui"));
  EXPECT_EQ(cache.used_bytes(), std::size_t{60});
}

TEST(texture_cache_budget_reduction_evicts_unpinned_entries) {
  cth3ds::TextureCache cache(200);
  EXPECT_TRUE(cache.insert("a", 50));
  EXPECT_TRUE(cache.insert("b", 50));
  EXPECT_TRUE(cache.insert("pinned", 50, true));
  cache.set_budget(80);
  EXPECT_TRUE(cache.contains("pinned"));
  EXPECT_EQ(cache.used_bytes(), std::size_t{50});
}
