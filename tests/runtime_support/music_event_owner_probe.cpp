#include "cth3ds/music_event_owner.hpp"

#include <cassert>
#include <cstdio>
#include <thread>

using Owner = cth3ds::MusicEventOwner;
extern Owner* other_translation_unit_owner();

int main() {
  Owner owner;
  assert(owner.completed() == 0 && !owner.consume(0) && !owner.consume(-1));
  const auto first = owner.begin();
  assert(first > 0 && !owner.consume(first));
  assert(owner.completed() == first && owner.completed() == 0);
  assert(owner.snapshot().phase == Owner::Phase::completed);
  assert(owner.consume(first) && !owner.consume(first));
  assert(owner.completed() == 0);
  std::puts("PASS natural completion once and positive SDL code");

  const auto old = owner.begin();
  const auto already_waited_event = owner.completed();
  owner.invalidate(old);
  const auto current = owner.begin(); // Old callback joined before real begin.
  assert(!owner.consume(already_waited_event));
  owner.invalidate(old); // Collection of the previous decoder cannot stop this.
  assert(owner.snapshot().token == current);
  assert(owner.snapshot().phase == Owner::Phase::playing);
  assert(owner.completed() == current && owner.consume(current));
  std::puts("PASS event already dequeued then stop replacement and old free");

  const auto failed_play = owner.begin();
  owner.invalidate(failed_play);
  assert(owner.completed() == 0 && !owner.consume(failed_play));
  const auto retry = owner.begin();
  assert(retry != failed_play && owner.completed() == retry);
  owner.delivery_failed(retry);
  assert(owner.snapshot().phase == Owner::Phase::delivery_failed);
  assert(!owner.consume(retry) && owner.completed() == 0);
  owner.invalidate_all();
  assert(!owner.consume(retry));
  std::puts("PASS failed play retry and filtered or full event queue observable");

  const auto dropped = owner.begin();
  assert(owner.completed() == dropped);
  assert(owner.snapshot().phase == Owner::Phase::completed); // Queue was cleared.
  owner.invalidate_all();
  assert(owner.snapshot().phase == Owner::Phase::inactive);
  assert(!owner.consume(dropped));
  std::puts("PASS pending completion survives queue loss until explicit stop");

  // The main thread can stop while the audio thread is completing. No event
  // created on either side of invalidate may dispatch after the stop returns.
  for (unsigned n = 0; n != 500; ++n) {
    const auto token = owner.begin();
    Owner::Token event = 0;
    std::thread callback([&] { event = owner.completed(); });
    owner.invalidate(token);
    callback.join();
    assert(event == 0 || event == token);
    assert(!owner.consume(event));
    assert(owner.snapshot().phase == Owner::Phase::inactive);
  }
  std::puts("PASS callback main-stop race");

  Owner boundary(Owner::max_token - 1);
  const auto last = boundary.begin();
  assert(last == Owner::max_token && boundary.completed() == last);
  assert(boundary.consume(last));
  assert(boundary.begin() == 0 && boundary.begin() == 0);
  assert(boundary.completed() == 0 && !boundary.consume(last));
  assert(other_translation_unit_owner() == &cth3ds::music_event_owner);
  std::puts("PASS exhaustion no token reuse and shared translation-unit owner");
}
