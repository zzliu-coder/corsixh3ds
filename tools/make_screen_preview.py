#!/usr/bin/env python3
"""Convert one simulator PPM frame into a deterministic PNG preview."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from make_preview import PreviewError, read_ppm, write_png


def build_screen_preview(source: Path, output: Path) -> None:
    width, height, pixels = read_ppm(source)
    if (width, height) not in ((400, 240), (320, 240)):
        raise PreviewError(
            f"simulator frame must be 400x240 or 320x240, got {width}x{height}"
        )
    write_png(output, width, height, pixels)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        build_screen_preview(args.source, args.output)
    except (OSError, ValueError, PreviewError) as exc:
        print(f"error: {exc}")
        return 2
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
