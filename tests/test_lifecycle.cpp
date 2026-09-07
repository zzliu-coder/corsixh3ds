#include "test_framework.hpp"

#include "cth3ds/lifecycle.hpp"

TEST(lifecycle_suspend_requests_pause_and_autosave) {
  cth3ds::LifecycleController controller;
  const auto decision = controller.signal(cth3ds::LifecycleSignal::Suspend, 1000);
  EXPECT_TRUE(decision.pause_simulation);
  EXPECT_TRUE(decision.pause_audio);
  EXPECT_TRUE(decision.request_autosave);
  EXPECT_EQ(controller.state(), cth3ds::LifecycleState::Suspended);
}

TEST(lifecycle_resume_restarts_audio_and_periodic_timer) {
  cth3ds::LifecycleController controller(1000000);
  (void)controller.signal(cth3ds::LifecycleSignal::Sleep, 1000);
  const auto resume = controller.signal(cth3ds::LifecycleSignal::Wake, 2000);
  EXPECT_TRUE(resume.resume_audio);
  EXPECT_EQ(controller.state(), cth3ds::LifecycleState::Running);
  EXPECT_FALSE(controller.tick(900000).request_autosave);
  EXPECT_TRUE(controller.tick(1002000).request_autosave);
}

TEST(lifecycle_defers_save_during_critical_io) {
  cth3ds::LifecycleController controller;
  controller.begin_critical_io();
  const auto suspend = controller.signal(cth3ds::LifecycleSignal::Suspend, 1000);
  EXPECT_FALSE(suspend.request_autosave);
  controller.end_critical_io();
  EXPECT_TRUE(controller.tick(1001).request_autosave);
}

TEST(lifecycle_exit_requests_final_save) {
  cth3ds::LifecycleController controller;
  const auto decision = controller.signal(cth3ds::LifecycleSignal::Exit, 42);
  EXPECT_TRUE(decision.request_exit);
  EXPECT_TRUE(decision.request_autosave);
  EXPECT_EQ(controller.state(), cth3ds::LifecycleState::ExitPending);
}

TEST(lifecycle_exit_waits_for_critical_io) {
  cth3ds::LifecycleController controller;
  controller.begin_critical_io();
  const auto immediate = controller.signal(cth3ds::LifecycleSignal::Exit, 42);
  EXPECT_FALSE(immediate.request_exit);
  EXPECT_FALSE(immediate.request_autosave);
  controller.end_critical_io();
  const auto deferred = controller.tick(43);
  EXPECT_TRUE(deferred.request_autosave);
  EXPECT_TRUE(deferred.request_exit);
}

TEST(lifecycle_duplicate_suspend_and_sleep_are_idempotent) {
  cth3ds::LifecycleController controller;
  const auto first = controller.signal(cth3ds::LifecycleSignal::Suspend, 1000);
  const auto duplicate = controller.signal(cth3ds::LifecycleSignal::Sleep, 1001);
  EXPECT_TRUE(first.request_autosave);
  EXPECT_FALSE(duplicate.request_autosave);
  EXPECT_FALSE(duplicate.pause_audio);
  EXPECT_FALSE(duplicate.pause_simulation);
}

TEST(lifecycle_duplicate_restore_and_wake_are_idempotent) {
  cth3ds::LifecycleController controller;
  (void)controller.signal(cth3ds::LifecycleSignal::Sleep, 1000);
  const auto first = controller.signal(cth3ds::LifecycleSignal::Restore, 2000);
  const auto duplicate = controller.signal(cth3ds::LifecycleSignal::Wake, 2001);
  EXPECT_TRUE(first.resume_audio);
  EXPECT_FALSE(duplicate.resume_audio);
}

TEST(lifecycle_reset_anchors_periodic_autosave_to_current_time) {
  cth3ds::LifecycleController controller(1000000);
  controller.reset(5000000);
  EXPECT_FALSE(controller.tick(5999999).request_autosave);
  EXPECT_TRUE(controller.tick(6000000).request_autosave);
}

TEST(lifecycle_loose_has_bounded_pause_restore_and_no_native_serialization) {
  cth3ds::LifecycleController controller;
  controller.set_autosave_enabled(false);controller.reset(0);
  EXPECT_FALSE(controller.tick(120000000).request_autosave);
  const auto sleep=controller.signal(cth3ds::LifecycleSignal::Sleep,120000001);
  EXPECT_TRUE(sleep.pause_audio);EXPECT_TRUE(sleep.pause_simulation);EXPECT_FALSE(sleep.request_autosave);
  const auto wake=controller.signal(cth3ds::LifecycleSignal::Wake,130000000);
  EXPECT_TRUE(wake.resume_audio);EXPECT_FALSE(wake.request_autosave);
  const auto exit=controller.signal(cth3ds::LifecycleSignal::Exit,130000001);
  EXPECT_TRUE(exit.request_exit);EXPECT_FALSE(exit.request_autosave);
}
