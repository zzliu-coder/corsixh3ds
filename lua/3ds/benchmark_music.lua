-- Observe the asynchronous finished-event handoff without driving the jukebox.
local M={}
local Media=require("3ds.media")

function M.check(native,audio,pending)
  local now=native.clock_ms()
  local playing,paused,token,phase=native.music_state()
  assert(not paused,"benchmark music is paused")
  assert(phase~=3,"benchmark music finished event delivery failed")
  -- A playing observation needs no Lua transport metadata except when settling
  -- a previously observed gap. This also retains the existing legacy host seam.
  if playing and not pending then return nil end
  if not pending then
    assert(type(token)=="number" and token>0 and phase==2,
      "benchmark music stopped without a pending finished event")
  end
  local revision,from,to,failed=Media.musicStatus(audio)
  assert(not failed,"benchmark next music failed to load or play")
  if pending then
    assert(audio==pending.audio,"benchmark music owner changed during handoff")
    assert(now>=pending.at and now-pending.at<=1000,
      "benchmark music handoff exceeded 1000ms")
    if playing then
      assert(from==pending.revision and to==revision,
        "benchmark music resumed without its finished-event handoff")
      assert(type(token)=="number" and token>pending.token and phase==1,
        "benchmark next music has no new native playback owner")
      if native.diagnostic_line then
        native.diagnostic_line("benchmark-music: event=HANDOFF_COMPLETE gap_ms="
          ..(now-pending.at).." from="..from.." to="..to)
      end
      return nil
    end
    assert(revision==pending.revision and token==pending.token and phase==2,
      "benchmark music stopped during handoff")
    return pending
  end
  if native.diagnostic_line then
    native.diagnostic_line("benchmark-music: event=HANDOFF_PENDING at_ms="..now
      .." revision="..revision.." token="..token)
  end
  return {audio=audio,at=now,revision=revision,token=token}
end
return M
