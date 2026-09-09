#!/usr/bin/env python3
"""Verify the selected resource boundary against the real final ARM link."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from integration.build_profile import PROFILES, validate_profile

REQUIRED = {
    "runtime_session_start": "RuntimeSession::start(",
    "runtime_session_shutdown": "RuntimeSession::shutdown(",
    "runtime_session_menu": "RuntimeSession::enter_menu(",
    "runtime_session_level": "RuntimeSession::enter_level(",
    "runtime_session_save_begin": "RuntimeSession::begin_save_load(",
    "runtime_session_save_finish": "RuntimeSession::finish_save_load(",
    "runtime_session_suspend": "RuntimeSession::suspend(",
    "runtime_session_resume": "RuntimeSession::resume(",
    "bundle_mount": "BundleMount::open_bundle(",
    "resource_acquire": "ResourceManager::acquire(",
    "transition_rollback": "TransitionToken::~TransitionToken(",
}
EXPERIMENT_FAMILIES = (
    "cth3ds::RuntimeSession::", "cth3ds::ResourceManager::",
    "cth3ds::ResourceManagerState::", "cth3ds::ResourceLease::",
    "cth3ds::TransitionToken::", "cth3ds::BundleMount::",
    "cth3ds::AllocationLedger::", "cth3ds::ResourcePack::",
    "cth3ds::Sha256::", "cth3ds::sha256(", "cth3ds::sha256_hex",
    "RuntimeResourceTelemetry::", "RuntimeResourceBudgetGate::")

def proof(archive_symbols: str, elf_symbols: str, disassembly: str,
          whole_archive: bool, profile: str) -> dict:
    validate_profile(profile)
    archive_present = {key: needle in archive_symbols for key, needle in REQUIRED.items()}
    elf_present = {key: needle in elf_symbols for key, needle in REQUIRED.items()}
    functions = {}
    current = None
    for line in disassembly.splitlines():
        header = re.match(r"^[0-9a-fA-F]+ <(.+)>:$", line)
        if header:
            current = header.group(1)
            functions.setdefault(current, set())
            continue
        if current is not None:
            call = re.search(r"\b(?:b|bl|blx)\b[^<]*<(.+)>", line)
            if call and not re.search(r"\+0x[0-9a-fA-F]+$", call.group(1)):
                functions[current].add(call.group(1))
    roots = [name for name in functions if "cth3ds::runtime_initialize(" in name]
    goals = {name for name in functions if "RuntimeSession::start(" in name}
    queue = [(root, [root]) for root in roots]
    visited, edge_path = set(roots), []
    while queue:
        node, path = queue.pop(0)
        if node in goals:
            edge_path = path
            break
        for target in sorted(functions.get(node, ())):
            if target not in visited:
                visited.add(target)
                queue.append((target, path + [target]))
    ready = any("mainloop(" in name and any("runtime_assert_ready(" in edge for edge in edges)
                for name, edges in functions.items())
    retained = {family: {"archive": family in archive_symbols, "elf": family in elf_symbols}
                for family in EXPERIMENT_FAMILIES}
    if profile == 'resource-experiment':
        boundary = all(archive_present.values()) and all(elf_present.values()) and bool(edge_path)
    else:
        boundary = not any(row["archive"] or row["elf"] for row in retained.values()) and not edge_path
    return {"build_profile": profile, "archive_symbols": archive_present,
            "elf_symbols": elf_present, "experiment_families": retained,
            "production_entry": roots, "runtime_session_call_path": edge_path,
            "entry_scope": "explicit " + profile + " build",
            "player_ready_guard": ready, "whole_archive_used": whole_archive,
            "pass": bool(roots) and ready and boundary and not whole_archive}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--nm', required=True)
    parser.add_argument('--objdump', required=True)
    parser.add_argument('--profile', choices=PROFILES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    def symbols(path):
        return subprocess.check_output([args.nm, '-C', '--defined-only', str(path)],
                                       text=True, errors='replace')
    disassembly = subprocess.check_output([args.objdump, '-d', '-C', str(args.elf)],
                                          text=True, errors='replace')
    links = [*args.build.rglob('link.txt'), *args.build.glob('build.ninja')]
    if not links:
        raise RuntimeError('link command evidence missing')
    whole = any('--whole-archive' in path.read_text(errors='replace') for path in links)
    result = proof(symbols(args.archive), symbols(args.elf), disassembly, whole, args.profile)
    result.update(elf=str(args.elf), archive=str(args.archive))
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    if not result['pass']:
        raise SystemExit('resource build-profile archive/final-ELF boundary failed')

if __name__ == '__main__':
    main()
