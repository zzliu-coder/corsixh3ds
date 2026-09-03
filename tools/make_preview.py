#!/usr/bin/env python3
"""Create a single PNG preview from simulator top/bottom PPM frames."""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path
from typing import Sequence


class PreviewError(RuntimeError):
    pass


def _tokens(data: bytes):
    index = 0
    length = len(data)
    while index < length:
        while index < length and chr(data[index]).isspace():
            index += 1
        if index < length and data[index] == ord("#"):
            while index < length and data[index] not in (10, 13):
                index += 1
            continue
        if index >= length:
            break
        start = index
        while index < length and not chr(data[index]).isspace() and data[index] != ord("#"):
            index += 1
        yield data[start:index], index


def read_ppm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    iterator = iter(_tokens(data))
    try:
        magic, _ = next(iterator)
        width_token, _ = next(iterator)
        height_token, _ = next(iterator)
        maximum_token, header_end = next(iterator)
    except StopIteration as exc:
        raise PreviewError(f"truncated PPM: {path}") from exc
    if magic not in (b"P6", b"P3"):
        raise PreviewError(f"unsupported PPM type {magic!r}: {path}")
    width, height, maximum = int(width_token), int(height_token), int(maximum_token)
    if width <= 0 or height <= 0 or maximum != 255:
        raise PreviewError(f"invalid PPM header: {path}")
    expected = width * height * 3
    if magic == b"P6":
        cursor = header_end
        if data[cursor : cursor + 2] == b"\r\n":
            cursor += 2
        elif cursor < len(data) and chr(data[cursor]).isspace():
            cursor += 1
        else:
            raise PreviewError(f"missing P6 header separator: {path}")
        pixels = data[cursor : cursor + expected]
        if len(pixels) != expected:
            raise PreviewError(f"truncated P6 pixel data: {path}")
        return width, height, pixels
    values = [int(token) for token, _ in iterator]
    if len(values) != expected or any(value < 0 or value > 255 for value in values):
        raise PreviewError(f"invalid P3 pixel data: {path}")
    return width, height, bytes(values)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    if len(pixels) != width * height * 3:
        raise PreviewError("RGB buffer size mismatch")
    scanlines = b"".join(
        b"\x00" + pixels[y * width * 3 : (y + 1) * width * 3]
        for y in range(height)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(scanlines, 9))
        + _chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def paste(canvas: bytearray, canvas_width: int, x: int, y: int,
          source_width: int, source_height: int, source: bytes) -> None:
    for row in range(source_height):
        source_start = row * source_width * 3
        dest_start = ((y + row) * canvas_width + x) * 3
        canvas[dest_start : dest_start + source_width * 3] = source[
            source_start : source_start + source_width * 3
        ]


def build_preview(top_path: Path, bottom_path: Path, output: Path) -> None:
    top_width, top_height, top = read_ppm(top_path)
    bottom_width, bottom_height, bottom = read_ppm(bottom_path)
    if (top_width, top_height) != (400, 240):
        raise PreviewError(f"top frame must be 400x240, got {top_width}x{top_height}")
    if (bottom_width, bottom_height) != (320, 240):
        raise PreviewError(
            f"bottom frame must be 320x240, got {bottom_width}x{bottom_height}"
        )

    width, height = 440, 560
    canvas = bytearray([24, 27, 31] * (width * height))

    def fill(x: int, y: int, w: int, h: int, rgb: tuple[int, int, int]) -> None:
        row = bytes(rgb) * w
        for line in range(y, y + h):
            start = (line * width + x) * 3
            canvas[start : start + w * 3] = row

    fill(12, 12, 416, 264, (7, 9, 12))
    fill(52, 292, 336, 256, (7, 9, 12))
    paste(canvas, width, 20, 20, top_width, top_height, top)
    paste(canvas, width, 60, 300, bottom_width, bottom_height, bottom)
    write_png(output, width, height, bytes(canvas))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("top", type=Path)
    parser.add_argument("bottom", type=Path)
    parser.add_argument("output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        build_preview(args.top, args.bottom, args.output)
    except (OSError, ValueError, PreviewError) as exc:
        print(f"error: {exc}")
        return 2
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
