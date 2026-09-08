#include "observation.hpp"
#include <cstdio>
#include <cstring>
#include "cth3ds/cpu_work.hpp"
#include "cth3ds/text_cache.hpp"

namespace cth3ds {
void RuntimeObservations::reset(std::uint64_t now) noexcept {
  timing.clear();
  timing.reset_window(now);
  memory.clear();
  slow.clear();
  scene.fill(0);
  window_has_operation = window_scene_changed = false;
  terminal = terminal_saved = flush_requested = false;
  compact_us = full_us = now;
  timer_events = logic_callbacks = logic_failures = 0;
  // Rows beyond count are unreachable; no large aggregate temporary or
  // duplicated buffer is needed to retire the previous session's records.
  operation_count = 0;
  operation_overflow = 0;
  sample_intervals.clear();
  sample_active=sample_valid=sample_anchor=false;
  sample_begin=sample_first=sample_last=0;
  cpu_work.sample_active=false;
  cpu_work.sample_rows={};
}
void RuntimeObservations::sample_present(std::uint64_t now, PresentResult result) noexcept {
  if(!sample_active)return;
  if(now<sample_begin || (sample_anchor && now<sample_last)){sample_valid=false;return;}
  if(result==PresentResult::Failed){sample_valid=false;return;}
  if(result!=PresentResult::Success)return;
  if(sample_anchor)sample_intervals.add(now-sample_last);
  else {sample_first=now;sample_anchor=true;}
  sample_last=now;
}
void RuntimeObservations::sample_mark(const char* event,std::uint64_t now,const ObservationOutput& output) noexcept {
  const bool begin=!std::strcmp(event,"SAMPLE-BEGIN");
  if(sample_active){
    const auto d=sample_intervals.snapshot();
    const auto elapsed=now>=sample_begin?now-sample_begin:0;
    const auto initial=sample_anchor?sample_first-sample_begin:elapsed;
    const auto tail=sample_anchor&&now>=sample_last?now-sample_last:elapsed;
    const bool eligible=!std::strcmp(event,"SAMPLE-END") && sample_valid && !d.total_overflowed &&
      d.count>0 && elapsed>=60000000U && initial<=1000000U && tail<=1000000U;
    output.line("benchmark-frames: end_event=%s eligible=%d begin=%llu end=%llu elapsed=%llu coverage_begin=%llu coverage_end=%llu first_delay_us=%llu open_gap_us=%llu intervals=%llu sum_us=%llu p95_hi_us=%llu max_us=%llu workload_guard=lua_each_tick presentation_api_timing=1",
      event,eligible,(unsigned long long)sample_begin,(unsigned long long)now,(unsigned long long)elapsed,
      (unsigned long long)sample_first,(unsigned long long)sample_last,
      (unsigned long long)initial,(unsigned long long)tail,(unsigned long long)d.count,
      (unsigned long long)d.total_us,(unsigned long long)d.p95_upper_us,(unsigned long long)d.maximum_us);
    cpu_work.sample_active=false;
    for(std::size_t i=0;i<cpu_work.sample_rows.size();++i){
      const auto& row=cpu_work.sample_rows[i];
      if(!row.calls)continue;
      output.line("benchmark-cpu: eligible=%d name=%s calls=%llu total_us=%llu max_us=%llu units=%llu contained_scopes=1 inclusive=1",
        eligible,kCpuWorkNames[i],(unsigned long long)row.calls,(unsigned long long)row.total_us,
        (unsigned long long)row.max_us,(unsigned long long)row.units);
    }
    sample_active=false;
  }
  if(begin){
    sample_intervals.clear();sample_begin=now;sample_first=sample_last=0;
    sample_anchor=false;sample_active=sample_valid=true;
    cpu_work.sample_rows={};cpu_work.sample_begin=now;cpu_work.sample_active=true;
  }
}
bool RuntimeObservations::due(std::uint64_t now, bool force) const noexcept {
  return !terminal_saved && (force || flush_requested || now-full_us>=60000000U || now-compact_us>=10000000U);
}
void RuntimeObservations::observe(const char* checkpoint, const MemoryObservation& o) noexcept {
  memory.observe(checkpoint ? checkpoint : "unknown", o);
  if(!checkpoint)return;
  const auto* phase=o.phase.data();
  const auto* resource=o.resource.data();
  const bool operation=!std::strcmp(checkpoint,"save")||!std::strcmp(checkpoint,"reload")||
    !std::strcmp(checkpoint,"world")||!std::strcmp(checkpoint,"release")||!std::strcmp(checkpoint,"restore");
  const bool boundary=!std::strcmp(phase,"before")||!std::strcmp(phase,"after")||
    !std::strcmp(phase,"committed")||!std::strcmp(phase,"failed")||
    !std::strcmp(phase,"gc-before")||!std::strcmp(phase,"gc-after");
  if(operation&&(boundary || !std::strcmp(checkpoint,"save") || !std::strcmp(checkpoint,"reload"))) {
    if(operation_count<operations.size()) {
      auto& row=operations[operation_count++];row.observation=o;
      std::snprintf(row.site.data(),row.site.size(),"%s",checkpoint);
    }else ++operation_overflow;
  }
  if(!std::strcmp(phase,"after") && (!std::strncmp(resource,"level:",6)||!std::strcmp(resource,"menu"))) {
    if(std::strcmp(scene.data(),resource))window_scene_changed=true;
    std::snprintf(scene.data(),scene.size(),"%s",resource);
  }
}
void RuntimeObservations::flush(const ObservationInputs& inputs, const ObservationOutput& output, bool force) noexcept {
  if (terminal_saved) return;
  const auto now = inputs.now;
  if(terminal && sample_active)sample_mark("TERMINAL",now,output);
  flush_requested = flush_requested || force;
  const bool full = flush_requested || now - full_us >= 60000000U;
  if (!full && now - compact_us < 10000000U) return;
  const auto p = timing.snapshot(now);
  const bool compact = force || terminal || now - compact_us >= 10000000U;
  if (compact) {
    slow.drain(output.line);
    const auto& m = inputs;
    output.line("perf: at_us=%llu scene=%s elapsed_us=%llu successful=%llu failed=%llu intervals=%llu mean_us=%.0f p95_us=%llu max_us=%llu gap_us=%llu heap_free=%llu heap_low=%llu lua=%llu linear_free=%llu log_us=%llu workload_us=%llu terminal=%d truncated=%d",
      static_cast<unsigned long long>(now),scene.data(),static_cast<unsigned long long>(p.elapsed_us),
      static_cast<unsigned long long>(p.successful_presents),static_cast<unsigned long long>(p.failed_presents),
      static_cast<unsigned long long>(p.intervals.count),p.intervals.count ? static_cast<double>(p.intervals.total_us)/static_cast<double>(p.intervals.count) : 0.0,
      static_cast<unsigned long long>(p.intervals.p95_upper_us),static_cast<unsigned long long>(p.intervals.maximum_us),
      static_cast<unsigned long long>(p.open_present_gap_us),static_cast<unsigned long long>(m.heap_available_estimate),
      static_cast<unsigned long long>(m.heap_available_low_water),static_cast<unsigned long long>(m.lua_bytes),
      static_cast<unsigned long long>(m.linear_free),static_cast<unsigned long long>(inputs.log_time_us),
      static_cast<unsigned long long>(inputs.workload_time_us),terminal,inputs.log_truncated);
    // Delivered SDL events remain an observation; SimulationClock now decides
    // callback dispatch. Read debt/dropped time below to judge lost progress.
    output.line("simulation-clock: at_us=%llu elapsed_us=%llu timer_events=%llu callbacks=%llu failures=%llu nominal_timer_us=18000",
      (unsigned long long)now,(unsigned long long)(now-compact_us),
      (unsigned long long)timer_events,(unsigned long long)logic_callbacks,(unsigned long long)logic_failures);
    timer_events=logic_callbacks=logic_failures=0;
    const auto& clock = inputs.clock;
    for(std::size_t i=0;i<cpu_work.rows.size();++i) {
      const auto& row=cpu_work.rows[i];
      // A missing row means zero calls in this compact interval. Error and
      // boundary reports keep every row for standalone diagnostics.
      if (!row.calls && !terminal && !full) continue;
      output.line("cpu-work: at_us=%llu name=%s calls=%llu total_us=%llu max_us=%llu units=%llu enabled=%d inclusive=1",
        (unsigned long long)now,kCpuWorkNames[i],(unsigned long long)row.calls,
        (unsigned long long)row.total_us,(unsigned long long)row.max_us,(unsigned long long)row.units,cpu_work.enabled);
    }
    cpu_work.rows = {};
    output.line("entity-profile: sample_period=16 sampled_passes_only=1 preserve_order=1");
    output.line("text-cache: charged_bytes=%llu peak_charged_bytes=%llu retained_limit=%llu evictions=%llu oversized_transients=%llu gpu_source_included=1",
      (unsigned long long)text_cache.bytes,(unsigned long long)text_cache.peak,
      (unsigned long long)TextCacheBudget::limit,(unsigned long long)text_cache.evictions,
      (unsigned long long)text_cache.oversize);
    output.line("text-cache-lookup: lookups=%llu hits=%llu secondary_hits=%llu misses=%llu conflicts=%llu entries_per_face=128 ways=2 cumulative=1",
      (unsigned long long)text_cache.lookups,(unsigned long long)text_cache.hits,
      (unsigned long long)text_cache.secondary_hits,(unsigned long long)text_cache.misses,
      (unsigned long long)text_cache.conflict_replacements);
    output.line("thermal-cache: updates=%llu scans=%llu rebuilt_cells=%llu scratch_bytes=%llu structure_fast=%u",
      (unsigned long long)cpu_work.thermal_updates,(unsigned long long)cpu_work.thermal_scans,
      (unsigned long long)cpu_work.thermal_rebuilds,(unsigned long long)cpu_work.thermal_bytes,
      cpu_work.thermal_structure_fast?1U:0U);
    output.line("simulation-budget: steps=%llu debt_us=%llu dropped_us=%llu rebases=%llu budget_exits=%llu step_us=18000 max_steps=4 budget_us=24000",
      (unsigned long long)clock.steps,(unsigned long long)clock.debt_us,
      (unsigned long long)clock.dropped_us,(unsigned long long)clock.rebases,
      (unsigned long long)clock.budget_exits);
    compact_us = now;
    output.line("log-buffer: capacity=4096 flushes=%llu failed=%d bytes_accepted=%llu flush_time_in_log_us=1",
      (unsigned long long)inputs.log_flushes,inputs.log_failed,(unsigned long long)inputs.log_bytes);
  }
  if (!full) { output.flush(); return; }
  // A save/load may span the scheduled flush time; retain it until quiescent.
  bool open = false;
  for (const auto& stage : p.stages) if (stage.open != 0) open = true;
  if (open && !terminal) {
    if (compact) output.flush();
    return;
  }
  output.line("observation: terminal=%d active_spans=%d reset_allowed=%d",terminal,open,!open);
  output.display();
  const auto& d = p.intervals;
  output.line("frame-interval-sum: overflowed=%d",d.total_overflowed);
  const bool crossed=p.intervals.count>0 && p.interval_coverage_begin_us<p.window_begin_us;
  output.line("segment: scene=%s stable_eligible=0 presentation_api_timing=1 operation_rows=%lu overflow=%llu crossing_interval=%d operation_mixed=%d scene_changed=%d workload_unfixed=1 strict_samples=benchmark-frames",
    scene.data(),(unsigned long)operation_count,(unsigned long long)operation_overflow,
    crossed,window_has_operation,window_scene_changed);
  for(std::size_t i=0;i<operation_count;++i){
    const auto& row=operations[i];const auto& o=row.observation;const auto& m=o.sample;
    output.line("operation-memory: site=%s phase=%s identity=%s timestamp=%llu heap_available=%llu arena=%llu lua=%llu lua_known=%d linear_free=%llu",
      row.site.data(),o.phase.data(),o.resource.data(),(unsigned long long)m.timestamp_us,(unsigned long long)m.heap_available_estimate(),(unsigned long long)m.arena,(unsigned long long)m.lua_bytes,m.lua_known,(unsigned long long)m.linear_free);
  }
  operation_count=0;operation_overflow=0;window_has_operation=false;
  window_scene_changed=false;
  output.line("frames: begin=%llu end=%llu elapsed=%llu success=%llu failed=%llu skipped=%llu count=%llu sum=%llu p50_lo=%llu p50_hi=%llu p95_lo=%llu p95_hi=%llu p99_lo=%llu p99_hi=%llu max=%llu coverage_begin=%llu coverage_end=%llu open_gap=%llu invalid=%llu",
      (unsigned long long)p.window_begin_us, (unsigned long long)p.observed_until_us,
      (unsigned long long)p.elapsed_us, (unsigned long long)p.successful_presents,
      (unsigned long long)p.failed_presents, (unsigned long long)p.skipped_presents,
      (unsigned long long)d.count, (unsigned long long)d.total_us,
      (unsigned long long)d.p50_lower_us, (unsigned long long)d.p50_upper_us,
      (unsigned long long)d.p95_lower_us, (unsigned long long)d.p95_upper_us,
      (unsigned long long)d.p99_lower_us, (unsigned long long)d.p99_upper_us,
      (unsigned long long)d.maximum_us, (unsigned long long)p.interval_coverage_begin_us,
      (unsigned long long)p.interval_coverage_end_us, (unsigned long long)p.open_present_gap_us,
      (unsigned long long)p.invalid_events);
  for (std::size_t i = 0; i < p.stages.size(); ++i) {
    const auto& s = p.stages[i];
    output.line("span: stage=%s count=%llu failed=%llu inclusive_us=%llu exclusive_us=%llu max=%llu open=%llu",
      kTimingStageNames[i], (unsigned long long)s.completed, (unsigned long long)s.failed,
      (unsigned long long)s.inclusive_us, (unsigned long long)s.exclusive_us, (unsigned long long)s.maximum_us,(unsigned long long)s.open);
  }
  for (std::size_t i = 0; i < memory.checkpoints().size(); ++i) {
    const auto& s = memory.checkpoints()[i];
    if (!s.samples) continue;
    const auto& o = s.latest; const auto& m = o.sample;
    output.line("observed-memory: site=%.*s samples=%llu first=%llu last=%llu stage=%s phase=%s resource=%s gate=%.*s env_heap_total=%llu arena=%llu uordblks=%llu fordblks=%llu heap_available_estimate=%llu linear_total=%llu linear_free=%llu lua=%llu lua_known=%d requested=%llu request_known=%d held=%llu held_known=%d min_heap_available=%llu max_heap_used=%llu min_linear_free=%llu max_lua=%llu max_request=%llu max_held=%llu failures=%llu opaque_unknown=%llu truncated=%d sampled_lower_bound=1",
      (int)kMemoryCheckpointNames[i].size(), kMemoryCheckpointNames[i].data(),
      (unsigned long long)s.samples, (unsigned long long)s.first_us, (unsigned long long)s.last_us,
      o.stage.data(), o.phase.data(), o.resource.data(), (int)memory_gate_name(o.gate).size(), memory_gate_name(o.gate).data(),
      (unsigned long long)m.env_heap_total, (unsigned long long)m.arena, (unsigned long long)m.uordblks,
      (unsigned long long)m.fordblks, (unsigned long long)m.heap_available_estimate(),
      (unsigned long long)m.linear_total, (unsigned long long)m.linear_free, (unsigned long long)m.lua_bytes, m.lua_known,
      (unsigned long long)o.requested_bytes, o.requested_known, (unsigned long long)o.held_bytes, o.held_known,
      (unsigned long long)s.minimum_heap_available, (unsigned long long)s.maximum_heap_used,
      (unsigned long long)s.minimum_linear_free, (unsigned long long)s.maximum_lua_bytes,
      (unsigned long long)s.maximum_requested_bytes, (unsigned long long)s.maximum_known_held_bytes,
      (unsigned long long)s.allocation_failures, (unsigned long long)s.unknown_temporary_samples, o.identity_truncated);
  }
  output.flush();
  if (terminal) { terminal_saved = true; return; }
  timing.reset_window(now); memory.clear(); full_us = now;
  flush_requested = false;
}
} // namespace cth3ds
