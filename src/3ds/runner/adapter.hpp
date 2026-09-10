#pragma once
#include "core.hpp"
namespace cth3ds {
int runner_start(int argc, char** argv) noexcept;
bool runner_active() noexcept;
bool runner_interactive() noexcept;
void runner_process_exit() noexcept;
const runner::Fields& runner_config();
std::string runner_directory();
void runner_checkpoint(const runner::Fields& metrics);
void runner_finish(const std::string& outcome, const std::string& reason,
                   const runner::Fields& metrics = {});
void runner_present(bool success) noexcept;
unsigned long long runner_frames() noexcept;
}
