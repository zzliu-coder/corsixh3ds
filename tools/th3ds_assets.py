"""Deterministic language, full-screen image, and glyph-atlas conversion."""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path

try:
    from th3ds_resource import ResourceError, canonical_json, read_stable, safe_relative, sha256_bytes
except ModuleNotFoundError:
    from .th3ds_resource import ResourceError, canonical_json, read_stable, safe_relative, sha256_bytes

LANGUAGE_RE = re.compile(r"\bLanguage\s*\(([^\n)]*)\)")
INHERIT_RE = re.compile(r"\bInherit\s*\(\s*(['\"])([^'\"]+)\1\s*(?:,\s*(\d+)\s*)?\)")
STRING_RE = re.compile(r"(['\"])(.*?)\1")


@dataclass(frozen=True)
class LanguageBundle:
    files: tuple[tuple[str, bytes], ...]
    index: bytes
    original_ids: tuple[int, ...]
    selected: str
    tag: str


@dataclass(frozen=True)
class LanguagePackResult:
    data: bytes
    decoded_size: int
    decoded_sha256: str


LANGUAGE_PACK_MAGIC = b"TH3DSLG1"
LANGUAGE_PACK_VERSION = 1
LANGUAGE_PACK_HEADER = struct.Struct("<8sIIIIQQ")
LANGUAGE_PACK_ENTRY = struct.Struct("<HBBQQ32s")
LANGUAGE_PAYLOAD_ALIGNMENT = 64


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & -alignment


def build_language_pack(bundle: LanguageBundle) -> LanguagePackResult:
    """Pack only the statically proven selected-language closure."""

    rows = []
    index_size = 0
    for relative, data in bundle.files:
        encoded = safe_relative(relative).encode("utf-8")
        if len(encoded) > 0xFFFF:
            raise ResourceError(f"language resource path is too long: {relative}")
        kind = 1 if relative.endswith(".lua") else 2
        rows.append((relative, encoded, kind, data))
        index_size += LANGUAGE_PACK_ENTRY.size + len(encoded)
    index_offset = LANGUAGE_PACK_HEADER.size
    data_offset = _align_up(index_offset + index_size, LANGUAGE_PAYLOAD_ALIGNMENT)
    cursor = data_offset
    index = bytearray()
    payload = bytearray(data_offset - (index_offset + index_size))
    decoded = bytearray()
    for relative, encoded, kind, data in rows:
        aligned = _align_up(cursor, LANGUAGE_PAYLOAD_ALIGNMENT)
        payload.extend(bytes(aligned - cursor))
        cursor = aligned
        index.extend(
            LANGUAGE_PACK_ENTRY.pack(
                len(encoded), kind, 0, cursor, len(data), bytes.fromhex(sha256_bytes(data))
            )
        )
        index.extend(encoded)
        payload.extend(data)
        decoded.extend(struct.pack("<H", len(encoded)))
        decoded.extend(encoded)
        decoded.extend(data)
        cursor += len(data)
    header = LANGUAGE_PACK_HEADER.pack(
        LANGUAGE_PACK_MAGIC,
        LANGUAGE_PACK_VERSION,
        len(rows),
        LANGUAGE_PACK_ENTRY.size,
        0,
        index_offset,
        data_offset,
    )
    logical = bytes(decoded)
    return LanguagePackResult(
        bytes(header + index + payload), len(logical), sha256_bytes(logical)
    )


def _language_declaration(data: bytes, path: Path) -> tuple[str, ...]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResourceError(f"language source is not UTF-8: {path}") from exc
    match = LANGUAGE_RE.search(text)
    if match is None:
        raise ResourceError(f"language source has no static Language(...) declaration: {path}")
    names = tuple(item[1] for item in STRING_RE.findall(match.group(1)))
    if not names:
        raise ResourceError(f"language source has an empty Language(...) declaration: {path}")
    return names


def build_language_bundle(language_dir: Path, selected: str, game_data: Path) -> LanguageBundle:
    if not language_dir.is_dir():
        raise ResourceError(f"language directory does not exist: {language_dir}")
    sources: dict[str, tuple[Path, bytes, tuple[str, ...]]] = {}
    aliases: dict[str, str] = {}
    for path in sorted(language_dir.glob("*.lua"), key=lambda item: item.name.casefold()):
        if path.is_symlink():
            raise ResourceError(f"language source may not be a symlink: {path}")
        data = read_stable(path)
        names = _language_declaration(data, path)
        key = names[0].casefold()
        if key in sources:
            raise ResourceError(f"duplicate canonical language name: {names[0]}")
        sources[key] = (path, data, names)
        for name in names:
            alias = name.casefold()
            if alias in aliases and aliases[alias] != key:
                raise ResourceError(f"language alias collision: {name}")
            aliases[alias] = key

    selected_key = aliases.get(selected.casefold())
    if selected_key is None:
        raise ResourceError(f"selected language is unavailable: {selected}")
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    original_ids: set[int] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ResourceError(f"language inheritance cycle includes {sources[key][2][0]}")
        if key in visited:
            return
        visiting.add(key)
        path, data, _names = sources[key]
        text = data.decode("utf-8")
        for _quote, inherited, language_id in INHERIT_RE.findall(text):
            inherited_key = aliases.get(inherited.casefold())
            if inherited_key is None:
                raise ResourceError(f"{path.name} inherits missing language {inherited!r}")
            if inherited.casefold() == "original_strings":
                if not language_id:
                    raise ResourceError(f"{path.name} must supply a numeric original-string language id")
                original_ids.add(int(language_id))
            visit(inherited_key)
        visiting.remove(key)
        visited.add(key)
        ordered.append(key)

    visit(selected_key)
    files: list[tuple[str, bytes]] = []
    languages: list[dict[str, object]] = []
    for key in ordered:
        path, data, names = sources[key]
        relative = f"languages/lua/{path.name}"
        files.append((relative, data))
        languages.append(
            {
                "aliases": list(names),
                "canonical": names[0],
                "path": relative,
                "sha256": sha256_bytes(data),
            }
        )
    for language_id in sorted(original_ids):
        path = _find_case_insensitive(game_data, f"DATA/LANG-{language_id}.DAT")
        if path is None:
            raise ResourceError(f"selected language requires missing original string file DATA/LANG-{language_id}.DAT")
        data = read_stable(path)
        files.append((f"languages/original/LANG-{language_id}.DAT", data))
    index_obj = {
        "format": "th3ds-language-index",
        "languages": languages,
        "original_string_ids": sorted(original_ids),
        "selected": sources[selected_key][2][0],
        "version": 1,
    }
    aliases_for_selected = sources[selected_key][2]
    tag = next(
        (
            alias.lower()
            for alias in reversed(aliases_for_selected)
            if re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", alias)
        ),
        re.sub(r"[^a-z0-9]+", "-", aliases_for_selected[0].casefold()).strip("-"),
    )
    return LanguageBundle(
        tuple(files),
        canonical_json(index_obj),
        tuple(sorted(original_ids)),
        aliases_for_selected[0],
        tag,
    )


def _find_case_insensitive(root: Path, relative: str) -> Path | None:
    current = root
    for part in safe_relative(relative).split("/"):
        if not current.is_dir():
            return None
        matches = [child for child in current.iterdir() if child.name.casefold() == part.casefold()]
        if len(matches) > 1:
            raise ResourceError(f"case-insensitive collision below {current}: {part}")
        if not matches:
            return None
        current = matches[0]
    return current if current.is_file() else None


def _expand_component(value: int, palette_bits: int) -> int:
    if palette_bits == 8:
        return value
    if value > 63:
        raise ResourceError(f"6-bit palette component is out of range: {value}")
    return (value * 255 + 31) // 63


def convert_fullscreen_image(
    pixels_path: Path,
    palette_path: Path,
    *,
    pixel_format: str = "rgb565",
    palette_bits: int = 6,
    transparent_index: int | None = None,
) -> bytes:
    pixels = read_stable(pixels_path)
    palette = read_stable(palette_path)
    if len(pixels) != 640 * 480:
        raise ResourceError(f"full-screen image must contain exactly 640x480 palette indices: {pixels_path}")
    if len(palette) not in (256 * 3, 256 * 4):
        raise ResourceError(f"palette must contain 256 RGB or RGBA entries: {palette_path}")
    if pixel_format not in ("rgb565", "rgba5551") or palette_bits not in (6, 8):
        raise ResourceError("pixel format must be rgb565/rgba5551 and palette bits must be 6/8")
    if transparent_index is not None and not 0 <= transparent_index <= 255:
        raise ResourceError("transparent palette index must be between 0 and 255")
    stride = len(palette) // 256
    colours: list[tuple[int, int, int, int]] = []
    for index in range(256):
        offset = index * stride
        r, g, b = (_expand_component(palette[offset + item], palette_bits) for item in range(3))
        a = palette[offset + 3] if stride == 4 else 255
        if (r, g, b) == (255, 0, 255) or index == transparent_index:
            a = 0
        colours.append((r, g, b, a))
    output = bytearray()
    for y in range(240):
        row = (y * 2) * 640
        for x in range(320):
            r, g, b, a = colours[pixels[row + x * 2]]
            if pixel_format == "rgb565":
                if a < 128:
                    raise ResourceError(f"rgb565 image contains transparent pixels: {pixels_path}")
                value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            else:
                value = ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) | (1 if a >= 128 else 0)
            output.extend(struct.pack("<H", value))
    return bytes(output)


def build_glyph_atlas(metadata_path: Path) -> tuple[str, bytes, bytes]:
    try:
        metadata = json.loads(read_stable(metadata_path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResourceError(f"invalid glyph atlas metadata {metadata_path}: {exc}") from exc
    if not isinstance(metadata, dict) or metadata.get("format") != 1:
        raise ResourceError(f"glyph atlas metadata must use format 1: {metadata_path}")
    name = metadata.get("name")
    image_name = metadata.get("image")
    pixel_format = metadata.get("pixel_format")
    width = metadata.get("width")
    height = metadata.get("height")
    glyphs = metadata.get("glyphs")
    if not isinstance(name, str) or not name or safe_relative(name) != name:
        raise ResourceError("glyph atlas name must be a safe relative name")
    if not isinstance(image_name, str) or Path(image_name).name != image_name:
        raise ResourceError("glyph atlas image must name a sibling file")
    if pixel_format not in ("rgb565", "rgba5551") or not isinstance(width, int) or not isinstance(height, int):
        raise ResourceError("glyph atlas must declare rgb565/rgba5551 integer dimensions")
    if width != 256 or height != 256 or not isinstance(glyphs, list):
        raise ResourceError("glyph atlas dimensions or glyph list are invalid")
    image = read_stable(metadata_path.parent / image_name)
    if len(image) != width * height * 2:
        raise ResourceError("glyph atlas image size does not match its dimensions and 16-bit format")
    normalized: list[dict[str, int]] = []
    seen: set[int] = set()
    required = ("codepoint", "x", "y", "width", "height", "advance", "bearing_x", "bearing_y")
    for index, glyph in enumerate(glyphs):
        if not isinstance(glyph, dict) or any(not isinstance(glyph.get(key), int) for key in required):
            raise ResourceError(f"glyph {index} is missing integer metrics")
        item = {key: glyph[key] for key in required}
        if item["codepoint"] in seen:
            raise ResourceError(f"duplicate glyph codepoint: {item['codepoint']}")
        seen.add(item["codepoint"])
        if item["width"] < 0 or item["height"] < 0 or item["x"] < 0 or item["y"] < 0:
            raise ResourceError(f"glyph {item['codepoint']} has negative geometry")
        if item["x"] + item["width"] > width or item["y"] + item["height"] > height:
            raise ResourceError(f"glyph {item['codepoint']} lies outside the atlas")
        normalized.append(item)
    normalized.sort(key=lambda item: item["codepoint"])
    output_metadata = canonical_json(
        {
            "format": "th3ds-glyph-atlas",
            "glyphs": normalized,
            "height": height,
            "image": f"{name}.bin",
            "image_sha256": sha256_bytes(image),
            "name": name,
            "pixel_format": pixel_format,
            "version": 1,
            "width": width,
        }
    )
    return name, output_metadata, image
