#pragma once

#include <cmath>
#include <functional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace testfw {

struct TestCase {
  std::string name;
  std::function<void()> function;
};

inline std::vector<TestCase>& registry() {
  static std::vector<TestCase> tests;
  return tests;
}

class Registrar {
 public:
  Registrar(std::string name, std::function<void()> function) {
    registry().push_back({std::move(name), std::move(function)});
  }
};

inline void fail(const char* expression, const char* file, int line,
                 const std::string& detail = {}) {
  std::ostringstream message;
  message << file << ':' << line << ": assertion failed: " << expression;
  if (!detail.empty()) {
    message << " (" << detail << ')';
  }
  throw std::runtime_error(message.str());
}

template <typename Left, typename Right>
void expect_equal(const Left& left, const Right& right, const char* left_text,
                  const char* right_text, const char* file, int line) {
  if (!(left == right)) {
    std::ostringstream detail;
    detail << left_text << " != " << right_text;
    fail("equality", file, line, detail.str());
  }
}

inline void expect_near(double left, double right, double tolerance,
                        const char* file, int line) {
  if (std::abs(left - right) > tolerance) {
    std::ostringstream detail;
    detail << left << " is not within " << tolerance << " of " << right;
    fail("near", file, line, detail.str());
  }
}

}  // namespace testfw

#define TEST(name) \
  static void name(); \
  static const testfw::Registrar registrar_##name(#name, name); \
  static void name()

#define EXPECT_TRUE(expression) \
  do { if (!(expression)) testfw::fail(#expression, __FILE__, __LINE__); } while (false)
#define EXPECT_FALSE(expression) EXPECT_TRUE(!(expression))
#define EXPECT_EQ(left, right) \
  do { testfw::expect_equal((left), (right), #left, #right, __FILE__, __LINE__); } while (false)
#define EXPECT_NEAR(left, right, tolerance) \
  do { testfw::expect_near(static_cast<double>(left), static_cast<double>(right), \
                           static_cast<double>(tolerance), __FILE__, __LINE__); } while (false)
