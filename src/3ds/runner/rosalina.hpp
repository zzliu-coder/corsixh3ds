// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <string>
#include <vector>
namespace runner {
bool loaderAvailable();
void nextLoad(const std::string &path, const std::vector<std::string> &args);
std::string bootId();
} // namespace runner
