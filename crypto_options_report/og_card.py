"""Deterministic, metadata-free Open Graph card rendering.

The renderer is intentionally limited to four already-public claims.  It emits
one RGB PNG containing exactly ``IHDR``, ``IDAT``, and ``IEND`` chunks; there is
no textual or ancillary chunk in which operator data could hitch a ride.
"""

from __future__ import annotations

import math
import struct
import zlib
from datetime import date
from typing import Final

from .empirical_rank import vrp_band_for_percentile

WIDTH: Final = 1200
HEIGHT: Final = 630

_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_PUBLIC_BAND_BY_INTERNAL: Final = {
    "extremely_expensive": "P90+",
    "expensive": "P70+",
    "neutral": "P30-P70",
    "thin": "P30-",
    "extremely_thin": "P10-",
}

_BACKGROUND: Final = (9, 18, 31)
_PANEL: Final = (16, 30, 49)
_GRID: Final = (42, 61, 82)
_TEXT: Final = (234, 241, 247)
_MUTED: Final = (145, 163, 181)
_ACCENT: Final = (44, 211, 190)
_WARNING: Final = (255, 184, 77)
_BAND_COLORS: Final = {
    "P10-": (99, 102, 241),
    "P30-": (59, 130, 246),
    "P30-P70": (44, 211, 190),
    "P70+": (255, 184, 77),
    "P90+": (244, 99, 110),
}

# Five-by-seven uppercase bitmap font.  Keeping the glyphs in source makes the
# artifact independent of host fonts, locale, font hinting, and system files.
_FONT: Final = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "+": (0b00000, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0b00000),
    "-": (0b00000, 0b00000, 0b00000, 0b11111, 0b00000, 0b00000, 0b00000),
    ".": (0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00110, 0b00110),
    "/": (0b00001, 0b00010, 0b00100, 0b00100, 0b01000, 0b10000, 0b00000),
    "0": (0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110),
    "1": (0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "2": (0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111),
    "3": (0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110),
    "4": (0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010),
    "5": (0b11111, 0b10000, 0b10000, 0b11110, 0b00001, 0b00001, 0b11110),
    "6": (0b01110, 0b10000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110),
    "7": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000),
    "8": (0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110),
    "9": (0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00001, 0b01110),
    "A": (0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "B": (0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110),
    "C": (0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110),
    "D": (0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110),
    "E": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111),
    "F": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000),
    "G": (0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01110),
    "H": (0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "I": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b11111),
    "J": (0b00111, 0b00010, 0b00010, 0b00010, 0b00010, 0b10010, 0b01100),
    "K": (0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001),
    "L": (0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111),
    "M": (0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001),
    "N": (0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001),
    "O": (0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "P": (0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000),
    "Q": (0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101),
    "R": (0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001),
    "S": (0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110),
    "T": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100),
    "U": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "V": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100),
    "W": (0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b10101, 0b01010),
    "X": (0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001),
    "Y": (0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100),
    "Z": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111),
}


class _Canvas:
    def __init__(self, width: int, height: int, background: tuple[int, int, int]) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(bytes(background) * width * height)

    def rectangle(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        color: tuple[int, int, int],
    ) -> None:
        left = max(x, 0)
        top = max(y, 0)
        right = min(x + width, self.width)
        bottom = min(y + height, self.height)
        if left >= right or top >= bottom:
            return
        row = bytes(color) * (right - left)
        for row_index in range(top, bottom):
            start = (row_index * self.width + left) * 3
            self.pixels[start : start + len(row)] = row

    def text(
        self,
        x: int,
        y: int,
        value: str,
        *,
        scale: int,
        color: tuple[int, int, int],
    ) -> None:
        cursor = x
        for character in value:
            try:
                rows = _FONT[character]
            except KeyError as error:  # pragma: no cover - fixed copy + validated input
                raise ValueError(f"unsupported OG-card glyph: {character!r}") from error
            for row_index, bits in enumerate(rows):
                for column in range(5):
                    if bits & (1 << (4 - column)):
                        self.rectangle(
                            cursor + column * scale,
                            y + row_index * scale,
                            scale,
                            scale,
                            color,
                        )
            cursor += 6 * scale


def render_og_card(
    *,
    vrp_percent_points: float,
    percentile: float,
    band: str,
    publication_date: str,
) -> bytes:
    """Render a 1200x630 public VRP card as deterministic PNG bytes.

    ``band`` uses the public vocabulary (``P10-``, ``P30-``, ``P30-P70``,
    ``P70+``, or ``P90+``) and must agree with ``percentile``.  The date is an
    exact ISO calendar date, not a timestamp or free-form label.
    """
    vrp = _finite_number("vrp_percent_points", vrp_percent_points)
    rank = _finite_number("percentile", percentile)
    if not 0.0 <= rank <= 1.0:
        raise ValueError("percentile must be in 0..1")
    expected_band = _PUBLIC_BAND_BY_INTERNAL[vrp_band_for_percentile(rank)]
    if not isinstance(band, str):
        raise TypeError("band must be a string")
    if band not in _BAND_COLORS:
        raise ValueError("band must use the canonical public vocabulary")
    if band != expected_band:
        raise ValueError("band does not match percentile")
    published = _publication_date(publication_date)

    canvas = _Canvas(WIDTH, HEIGHT, _BACKGROUND)
    _draw_frame(canvas)
    _draw_headline(canvas, vrp)
    _draw_rank_panel(canvas, rank, band)
    _draw_percentile_scale(canvas, rank)
    canvas.text(70, 582, f"PUBLISHED {published}", scale=3, color=_MUTED)
    canvas.text(878, 582, "RESEARCH ONLY", scale=3, color=_WARNING)
    encoded = _encode_png(canvas)
    validate_og_card_png(encoded)
    return encoded


def validate_og_card_png(payload: bytes) -> None:
    """Fail closed unless *payload* is the exact metadata-free card shape."""
    if not isinstance(payload, bytes) or not payload.startswith(_PNG_SIGNATURE):
        raise ValueError("OG card must be a PNG byte string")
    offset = len(_PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise ValueError("OG card contains a truncated PNG chunk")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(payload):
            raise ValueError("OG card contains a truncated PNG chunk")
        data = payload[data_start:data_end]
        stored_crc = struct.unpack(">I", payload[data_end:crc_end])[0]
        if stored_crc != zlib.crc32(chunk_type + data) & 0xFFFFFFFF:
            raise ValueError("OG card contains an invalid PNG checksum")
        chunks.append((chunk_type, data))
        offset = crc_end
    if [chunk_type for chunk_type, _ in chunks] != [b"IHDR", b"IDAT", b"IEND"]:
        raise ValueError("OG card contains metadata or unsupported PNG chunks")
    if len(chunks[0][1]) != 13:
        raise ValueError("OG card has an invalid IHDR chunk")
    if struct.unpack(">IIBBBBB", chunks[0][1]) != (WIDTH, HEIGHT, 8, 2, 0, 0, 0):
        raise ValueError("OG card must be a 1200x630 RGB image")
    if chunks[-1][1] != b"":
        raise ValueError("OG card has an invalid IEND chunk")


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _publication_date(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("publication_date must be a string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("publication_date must be an ISO calendar date") from error
    if value != parsed.isoformat():
        raise ValueError("publication_date must be an ISO calendar date")
    return value


def _draw_frame(canvas: _Canvas) -> None:
    canvas.rectangle(0, 0, 12, HEIGHT, _ACCENT)
    canvas.rectangle(70, 45, 48, 8, _ACCENT)
    canvas.text(70, 70, "LENSOS / BTC OPTIONS", scale=4, color=_TEXT)
    canvas.rectangle(70, 122, 1060, 2, _GRID)
    canvas.rectangle(887, 54, 243, 49, _PANEL)
    canvas.rectangle(887, 54, 5, 49, _WARNING)
    canvas.text(910, 68, "RESEARCH ONLY", scale=3, color=_WARNING)


def _draw_headline(canvas: _Canvas, vrp: float) -> None:
    canvas.text(70, 164, "BTC VOLATILITY RISK PREMIUM", scale=3, color=_MUTED)
    formatted = _format_vrp(vrp)
    scale = min(12, 680 // _text_width(formatted, scale=1))
    canvas.text(70, 215, formatted, scale=scale, color=_TEXT)
    canvas.text(76, 324, "VOL PTS", scale=4, color=_ACCENT)
    canvas.text(76, 373, "DVOL MINUS 30D REALIZED VOL", scale=3, color=_MUTED)


def _draw_rank_panel(canvas: _Canvas, percentile: float, band: str) -> None:
    color = _BAND_COLORS[band]
    canvas.rectangle(772, 151, 358, 265, _PANEL)
    canvas.rectangle(772, 151, 6, 265, color)
    canvas.text(810, 183, "EMPIRICAL RANK", scale=3, color=_MUTED)
    canvas.text(810, 236, f"{percentile * 100:.1f}", scale=9, color=_TEXT)
    canvas.text(814, 314, "PERCENTILE", scale=3, color=_MUTED)
    badge_width = _text_width(band, scale=4) + 36
    canvas.rectangle(810, 355, badge_width, 44, color)
    canvas.text(828, 363, band, scale=4, color=_BACKGROUND)


def _draw_percentile_scale(canvas: _Canvas, percentile: float) -> None:
    left = 70
    top = 475
    width = 1060
    segments = (
        (0.10, _BAND_COLORS["P10-"]),
        (0.20, _BAND_COLORS["P30-"]),
        (0.40, _BAND_COLORS["P30-P70"]),
        (0.20, _BAND_COLORS["P70+"]),
        (0.10, _BAND_COLORS["P90+"]),
    )
    cursor = left
    for index, (fraction, color) in enumerate(segments):
        segment_width = width - (cursor - left) if index == len(segments) - 1 else round(width * fraction)
        canvas.rectangle(cursor, top, segment_width, 26, color)
        cursor += segment_width

    marker_x = left + round(percentile * width)
    canvas.rectangle(marker_x - 3, top - 13, 6, 52, _TEXT)
    for inset in range(8):
        canvas.rectangle(marker_x - inset, top - 14 - inset, inset * 2 + 1, 1, _TEXT)

    labels = ((70, "P0"), (160, "P10"), (370, "P30"), (787, "P70"), (1003, "P90"))
    for x, label in labels:
        canvas.text(x, 520, label, scale=2, color=_MUTED)
    canvas.text(1090, 520, "P100", scale=2, color=_MUTED)


def _format_vrp(value: float) -> str:
    if value == 0.0:
        return "+0.00"
    if abs(value) < 1000:
        return f"{value:+.2f}"
    return f"{value:+.2E}"


def _text_width(value: str, *, scale: int) -> int:
    return (len(value) * 6 - 1) * scale


def _encode_png(canvas: _Canvas) -> bytes:
    stride = canvas.width * 3
    scanlines = bytearray((stride + 1) * canvas.height)
    for row in range(canvas.height):
        destination = row * (stride + 1)
        source = row * stride
        # Filter byte is already zero (None), which makes decoding and auditing
        # independent from a heuristic PNG filter selection.
        scanlines[destination + 1 : destination + 1 + stride] = canvas.pixels[
            source : source + stride
        ]

    compressor = zlib.compressobj(
        level=9,
        method=zlib.DEFLATED,
        wbits=zlib.MAX_WBITS,
        memLevel=9,
        strategy=zlib.Z_FIXED,
    )
    compressed = compressor.compress(bytes(scanlines)) + compressor.flush()
    header = struct.pack(">IIBBBBB", canvas.width, canvas.height, 8, 2, 0, 0, 0)
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


__all__ = ["HEIGHT", "WIDTH", "render_og_card"]
