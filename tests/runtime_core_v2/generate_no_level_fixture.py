#!/usr/bin/env python3
"""Generate the deterministic synthetic C3 no-level fixture and open trace."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path


ORIGIN = "generated_synthetic"
BUNDLE_JSON = b'{"bundle_sha256":"438143dbc6ee421172061525d8b9e3582a7e35c22107bd467860dcd2849231cf","fallback_language":null,"format":{"major":1,"minor":0},"packages":[{"container_sha256":"da5cc06932a8b9826523c17bb87276103ae86e1c29c31868e21619e14cb41469","package_id":"f8af6999dbd7fab22ee9d28f443e540a","path":"core.th3ds","role":"core","size":1410},{"container_sha256":"3974a9784238d73022a00fa7e983413a8284067e3d61afcf9b743f3e0445eacc","package_id":"9e89eb5f5ab1963a65ae5c41369a8af7","path":"lang/en.th3ds","role":"language","size":1602}],"runtime_abi":1,"selected_language":"en","source_set_sha256":"2edae379786ba0ab555371612978d84ccd720291cb48a47ebe4c9dc5bb65d329","start_level":null}'
CORE_B64 = (
    "VEgzRFNSMQAAAQEAAAAAAAQDAgFAAAAAAQAAAIAAAAAAAQAAAAAAAJIDAAAAAAAAwAQAAAAAAAAB"
    "AAAAAAAAAEAFAAAAAAAALgAAAAAAAACABQAAAAAAAAIAAAAAAAAAAAAAAAAAAABx7FS9MdfpezxY"
    "RjU2jflK/nV8yydRPvQLyasVJ66yrpailtIk8oXGe+6Tww+KMJFX8NqjXcW4fkELeGMKCc/H2lz"
    "AaTKouYJlI8F7uHJ2EDrobhwpwxho4hYZ4Uy0FGku2uN5eGugq1VTcWEpeNhMzXICkctIpH6+TJ"
    "3Fu2XTKQEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHsiYnVkZ2V0cyI6eyJhdWRpb19ieXRlcyI6ND"
    "A5NiwibGFuZ3VhZ2VfZm9udF9ieXRlcyI6NDA5NiwibWV0YWRhdGFfYnl0ZXMiOjY1NTM2LCJz"
    "Y3JhdGNoX2J5dGVzIjoxMDQ4NTc2LCJzcHJpdGVfYnl0ZXMiOjQwOTYsInRleHR1cmVfYnl0ZX"
    "MiOjQwOTZ9LCJjYXRhbG9nIjp7ImNhdGFsb2dfc2hhMjU2IjoiNzFlYzU0YmQzMWQ3ZTk3YjNj"
    "NTg0NjM1MzY4ZGY5NGFmZTc1N2NjYjI3NTEzZWY0MGJjOWFiMTUyN2FlYjJhZSIsInBheWxvYW"
    "Rfc2hhMjU2IjoiOTZhMjk2ZDIyNGYyODVjNjdiZWU5M2MzMGY4YTMwOTE1N2YwZGFhMzVkYzVi"
    "ODdlNDEwYjc4NjMwYTA5Y2ZjNyIsInJlc291cmNlX2NvdW50IjoxfSwiZGVwZW5kZW5jaWVzIj"
    "pbXSwiZm9ybWF0Ijp7Im1ham9yIjoxLCJtaW5vciI6MH0sImdyb3VwcyI6W3siZGVjb2RlZF9j"
    "ZWlsaW5nX2J5dGVzIjoyLCJpZCI6MSwibmFtZSI6ImJvb3QtbWVudSIsInJlcXVpcmVkIjp0cn"
    "VlLCJyZXNvdXJjZV9pZHMiOlsiZmU4MTdmOTViMjNkMDU0NzRlNzBkMjY2OTZmNDZkNjQiXX1d"
    "LCJsYW5ndWFnZSI6bnVsbCwibGV2ZWwiOm51bGwsInBhY2thZ2UiOnsiaWQiOiJmOGFmNjk5OW"
    "RiZDdmYWIyMmVlOWQyOGY0NDNlNTQwYSIsIm5hbWUiOiJjb3JlIiwicm9sZSI6ImNvcmUifSwic"
    "HJvdmVuYW5jZSI6eyJjb250YWluc191c2VyX2dhbWVfZGF0YSI6dHJ1ZSwicmVkaXN0cmlidXRh"
    "YmxlIjpmYWxzZX0sInJ1bnRpbWVfYWJpIjp7Im1heCI6MSwibWluIjoxfSwic291cmNlIjp7Im"
    "ZpbGVfY291bnQiOjEsInNldF9zaGEyNTYiOiIyZWRhZTM3OTc4NmJhMGFiNTU1MzcxNjEyOTc4"
    "ZDg0Y2NkNzIwMjkxY2I0OGE0N2ViZTRjOWRjNWJiNjVkMzI5IiwidG90YWxfYnl0ZXMiOjIyfS"
    "widG9vbGNoYWluIjp7ImZpeHR1cmUiOiJzeW50aGV0aWMtbm8tZ2FtZS1kYXRhLXYxIn19AAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP6Bf5WyPQVHTnDSZpb0"
    "bWQEAAAAAQAAAAEAAAAGAAAAgAUAAAAAAAACAAAAAgAAAAAAAAAAAAAALgAAAAAAAACWopbSJPKF"
    "xnvuk8MPijCRV/Dao13FuH5BC3hjCgnPx5ailtIk8oXGe+6Tww+KMJFX8NqjXcW4fkELeGMKCc/"
    "HeyJoZWlnaHQiOjEsInBpeGVsX2Zvcm1hdCI6IlJHQjU2NSIsIndpZHRoIjoxfQAAAAAAAAAAAA"
    "AAAAAAAAAAAAAA"
)
LANG_B64 = "VEgzRFNSMQAAAQEAAAAAAAQDAgFAAAAAAgAAAIAAAAAAAQAAAAAAACsEAAAAAAAAQAUAAAAAAAABAAAAAAAAAMAFAAAAAAAAVQAAAAAAAABABgAAAAAAAAIAAAAAAAAAAAAAAAAAAAAl8xvPiLbUgsqqJvVZ3zwEn8L9z657QL2t4EZYxINrckQTb6NVs2eKEUatFvfoZJ6U+0/CH+d+gxDAYPYcqv+KOXSpeEI41zAioA+n6YNBOoKEBn49Ya/Pm3Q/PgRF6swu2uN5eGugq1VTcWEpeNhMzXICkctIpH6+TJ3Fu2XTKQEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHsiYnVkZ2V0cyI6eyJhdWRpb19ieXRlcyI6NDA5NiwibGFuZ3VhZ2VfZm9udF9ieXRlcyI6NDA5NiwibWV0YWRhdGFfYnl0ZXMiOjY1NTM2LCJzY3JhdGNoX2J5dGVzIjoxMDQ4NTc2LCJzcHJpdGVfYnl0ZXMiOjQwOTYsInRleHR1cmVfYnl0ZXMiOjQwOTZ9LCJjYXRhbG9nIjp7ImNhdGFsb2dfc2hhMjU2IjoiMjVmMzFiY2Y4OGI2ZDQ4MmNhYWEyNmY1NTlkZjNjMDQ5ZmMyZmRjZmFlN2I0MGJkYWRlMDQ2NThjNDgzNmI3MiIsInBheWxvYWRfc2hhMjU2IjoiNDQxMzZmYTM1NWIzNjc4YTExNDZhZDE2ZjdlODY0OWU5NGZiNGZjMjFmZTc3ZTgzMTBjMDYwZjYxY2FhZmY4YSIsInJlc291cmNlX2NvdW50IjoxfSwiZGVwZW5kZW5jaWVzIjpbeyJjb250YWluZXJfc2hhMjU2IjoiZGE1Y2MwNjkzMmE4Yjk4MjY1MjNjMTdiYjg3Mjc2MTAzYWU4NmUxYzI5YzMxODY4ZTIxNjE5ZTE0Y2I0MTQ2OSIsInBhY2thZ2VfaWQiOiJmOGFmNjk5OWRiZDdmYWIyMmVlOWQyOGY0NDNlNTQwYSJ9XSwiZm9ybWF0Ijp7Im1ham9yIjoxLCJtaW5vciI6MH0sImdyb3VwcyI6W3siZGVjb2RlZF9jZWlsaW5nX2J5dGVzIjoyLCJpZCI6MSwibmFtZSI6InNlbGVjdGVkLWxhbmd1YWdlIiwicmVxdWlyZWQiOnRydWUsInJlc291cmNlX2lkcyI6WyI1MGM2MTIxMTc0NWQyNjA2MWNmM2YwMDVkMjI5ZThmMiJdfV0sImxhbmd1YWdlIjp7InRhZyI6ImVuIn0sImxldmVsIjpudWxsLCJwYWNrYWdlIjp7ImlkIjoiOWU4OWViNWY1YWIxOTYzYTY1YWU1YzQxMzY5YThhZjciLCJuYW1lIjoiZW4iLCJyb2xlIjoibGFuZ3VhZ2UifSwicHJvdmVuYW5jZSI6eyJjb250YWluc191c2VyX2dhbWVfZGF0YSI6dHJ1ZSwicmVkaXN0cmlidXRhYmxlIjpmYWxzZX0sInJ1bnRpbWVfYWJpIjp7Im1heCI6MSwibWluIjoxfSwic291cmNlIjp7ImZpbGVfY291bnQiOjEsInNldF9zaGEyNTYiOiIyZWRhZTM3OTc4NmJhMGFiNTU1MzcxNjEyOTc4ZDg0Y2NkNzIwMjkxY2I0OGE0N2ViZTRjOWRjNWJiNjVkMzI5IiwidG90YWxfYnl0ZXMiOjIyfSwidG9vbGNoYWluIjp7ImZpeHR1cmUiOiJzeW50aGV0aWMtbm8tZ2FtZS1kYXRhLXYxIn19AAAAAAAAAAAAAAAAAAAAAAAAAAAAUMYSEXRdJgYc8/AF0ino8gIAAAABAAAAAQAAAAYAAABABgAAAAAAAAIAAAACAAAAAAAAAAAAAABVAAAAAAAAAEQTb6NVs2eKEUatFvfoZJ6U+0/CH+d+gxDAYPYcqv+KRBNvo1WzZ4oRRq0W9+hknpT7T8If536DEMBg9hyq/4p7ImNhY2hlX3Bvb2wiOiJsYW5ndWFnZV9mb250IiwiZW50cnlfY291bnQiOjAsInBheWxvYWRfZm9ybWF0IjoiVEgzRFNMRzEiLCJ0YWciOiJlbiJ9AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHt9"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the synthetic C3 no-level fixture"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    args = parser.parse_args()

    output = args.out.resolve()
    trace_path = args.trace.resolve()
    opened: list[dict[str, object]] = []

    def audit(event: str, values: tuple[object, ...]) -> None:
        if event != "open" or not values:
            return
        raw_path = values[0]
        if isinstance(raw_path, (str, bytes, os.PathLike)):
            opened.append({"path": os.fsdecode(raw_path), "mode": str(values[1])})

    sys.addaudithook(audit)
    output.mkdir(parents=True, exist_ok=True)
    (output / "lang").mkdir(parents=True, exist_ok=True)
    files = {
        output / "bundle.json": BUNDLE_JSON,
        output / "core.package.bin": base64.b64decode(CORE_B64, validate=True),
        output / "lang" / "en.package.bin": base64.b64decode(
            LANG_B64, validate=True
        ),
        output / "fixture-manifest.json": (
            json.dumps(
                {
                    "schema": "cth3ds.runtime-core-test-fixture/v2",
                    "payload_origin": ORIGIN,
                    "contains_original_theme_hospital_data": False,
                    "container_schema_claim": {
                        "contains_user_game_data": True,
                        "redistributable": False,
                    },
                    "container_claim_scope":
                        "TH3DSR1_container_safety_classification",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        ),
    }
    for path, payload in files.items():
        path.write_bytes(payload)

    output_prefix = str(output) + os.sep
    inputs = [
        item
        for item in opened
        if not (os.path.realpath(str(item["path"])).startswith(output_prefix))
    ]
    trace_path.write_text(
        json.dumps(
            {
                "schema": "cth3ds.runtime-core-fixture-open-trace/v2",
                "trace_mechanism": "cpython-audit-open",
                "payload_origin": ORIGIN,
                "output_root": str(output),
                "input_opens": inputs,
            }, sort_keys=True, separators=(",", ":")
        ) + "\n", encoding="utf-8"
    )
    print(json.dumps({"generated_files": 4, "payload_origin": ORIGIN},
                     sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
