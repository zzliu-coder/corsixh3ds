#include <exception>
#include <iostream>

#include "test_framework.hpp"

int main() {
  int failed = 0;
  for (const auto& test : testfw::registry()) {
    try {
      test.function();
      std::cout << "[PASS] " << test.name << '\n';
    } catch (const std::exception& error) {
      ++failed;
      std::cerr << "[FAIL] " << test.name << ": " << error.what() << '\n';
    } catch (...) {
      ++failed;
      std::cerr << "[FAIL] " << test.name << ": unknown exception\n";
    }
  }
  std::cout << "Ran " << testfw::registry().size() << " tests; " << failed
            << " failed.\n";
  return failed == 0 ? 0 : 1;
}
