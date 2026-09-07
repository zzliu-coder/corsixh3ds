"""Bound ARM stack frames in the actual linked, unstripped device ELF.

DWARF CFA offsets describe compiler-emitted frames, including hidden aggregate
temporaries. This bounds individual port frames, not transitive call chains or
upstream/library recursion; real-device stack headroom still needs measurement.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

REQUIRED = {
    'cth3ds::register_lua_module(lua_State*)': 1024,
    'cth3ds::RuntimeObservations::reset(unsigned long long)': 1024,
    'cth3ds::RuntimeObservations::flush(': 4096,
}
FRAME_LIMIT = 8192  # one quarter of the unchanged 32768-byte main stack


def inspect_frames(symbols: str, frames: str) -> dict:
    names = {}
    for line in symbols.splitlines():
        match = re.match(r'([0-9a-fA-F]+) [TtWw] (.+)', line)
        if match and 'cth3ds::' in match[2]:
            names.setdefault(int(match[1], 16), []).append(match[2])
    rows = []
    seen = set()
    for block in frames.split('\n\n'):
        match = re.search(r'\bFDE .*\bpc=([0-9a-fA-F]+)\.\.([0-9a-fA-F]+)', block)
        if not match or int(match[1], 16) not in names:
            continue
        address = int(match[1], 16)
        seen.add(address)
        offsets = [int(x) for x in re.findall(r'DW_CFA_def_cfa_offset(?:_sf)?: (\d+)', block)]
        offsets += [int(x) for x in re.findall(r'DW_CFA_def_cfa(?:_sf)?: .* ofs (\d+)', block)]
        # Expressions do not provide a constant bound in this simple checker.
        unknown = 'DW_CFA_def_cfa_expression' in block
        for name in names[address]:
            limit = min([FRAME_LIMIT] + [n for prefix, n in REQUIRED.items() if name.startswith(prefix)])
            size = max(offsets, default=0)
            rows.append(dict(symbol=name, address=f'0x{address:08x}', frame_bytes=size,
                             limit_bytes=limit, result='FAIL' if unknown or size > limit else 'PASS',
                             constant_cfa=not unknown))
    missing = [prefix for prefix in REQUIRED if not any(r['symbol'].startswith(prefix) for r in rows)]
    uncovered = [name for address, group in names.items() if address not in seen for name in group]
    failures = [r for r in rows if r['result'] != 'PASS']
    return dict(result='PASS' if rows and not missing and not failures and not uncovered else 'FAIL',
                missing_required=missing, uncovered_symbols=uncovered, failures=failures,
                checked_symbols=len(rows), rows=sorted(rows, key=lambda r: (-r['frame_bytes'], r['symbol'])),
                boundary='Individual port frames only; no claim about aggregate call depth, library recursion or physical headroom.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--tool-prefix', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = args.elf.read_bytes()
    if data[:6] != b'\x7fELF\x01\x01' or struct.unpack_from('<H', data, 18)[0] != 40:
        raise SystemExit('Expected a little-endian ELF32 ARM executable')
    def call(tool, *flags):
        return subprocess.check_output([args.tool_prefix + tool, *flags, str(args.elf)], text=True)
    report = inspect_frames(call('nm', '-n', '-C', '--defined-only'), call('objdump', '--dwarf=frames'))
    report.update(elf_sha256=hashlib.sha256(data).hexdigest(), elf=str(args.elf))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, indent=2))
    print('Largest port frames: ' + ', '.join(f"{r['frame_bytes']}B {r['symbol']}" for r in report['rows'][:5]))
    return 0 if report['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
