from __future__ import annotations

import hashlib
import struct
import zlib

import pytest

from crypto_options_report.og_card import render_og_card

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _render(**overrides: object) -> bytes:
    inputs: dict[str, object] = {
        "vrp_percent_points": 8.198375,
        "percentile": 0.522852,
        "band": "P30-P70",
        "publication_date": "2026-08-03",
    }
    inputs.update(overrides)
    return render_og_card(**inputs)  # type: ignore[arg-type]


def _parse_chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    assert png.startswith(PNG_SIGNATURE)
    offset = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(png):
        assert offset + 12 <= len(png)
        length = struct.unpack(">I", png[offset : offset + 4])[0]
        chunk_type = png[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        assert crc_end <= len(png)
        data = png[data_start:data_end]
        stored_crc = struct.unpack(">I", png[data_end:crc_end])[0]
        assert stored_crc == zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        chunks.append((chunk_type, data))
        offset = crc_end
    assert offset == len(png)
    return chunks


def test_rendered_card_is_a_metadata_free_1200_by_630_rgb_png() -> None:
    png = _render()
    chunks = _parse_chunks(png)

    assert [chunk_type for chunk_type, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    assert struct.unpack(">IIBBBBB", chunks[0][1]) == (1200, 630, 8, 2, 0, 0, 0)
    assert chunks[-1][1] == b""

    scanlines = zlib.decompress(chunks[1][1])
    row_size = 1 + 1200 * 3
    assert len(scanlines) == 630 * row_size
    assert all(scanlines[row * row_size] == 0 for row in range(630))
    pixels: set[bytes] = set()
    for row in range(630):
        start = row * row_size + 1
        row_pixels = scanlines[start : start + 1200 * 3]
        pixels.update(row_pixels[index : index + 3] for index in range(0, len(row_pixels), 3))
    assert len(pixels) >= 8


def test_same_inputs_are_byte_for_byte_deterministic() -> None:
    assert _render() == _render()


def test_each_public_claim_changes_the_png_hash() -> None:
    baseline = hashlib.sha256(_render()).digest()
    variants = [
        _render(vrp_percent_points=8.208375),
        _render(percentile=0.612852),
        _render(percentile=0.75, band="P70+"),
        _render(publication_date="2026-08-04"),
    ]

    assert len({baseline, *(hashlib.sha256(item).digest() for item in variants)}) == 5


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("vrp_percent_points", float("nan")),
        ("vrp_percent_points", float("inf")),
        ("vrp_percent_points", True),
        ("percentile", float("nan")),
        ("percentile", -0.000001),
        ("percentile", 1.000001),
        ("percentile", False),
        ("band", "neutral"),
        ("band", "P30-P70\noperator_notes"),
        ("publication_date", "2026-8-3"),
        ("publication_date", "2026-02-30"),
        ("publication_date", "2026-08-03T12:00:00Z"),
    ],
)
def test_invalid_or_uncontrolled_inputs_fail_closed(field: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _render(**{field: value})


@pytest.mark.parametrize(
    ("percentile", "band"),
    [
        (0.0, "P10-"),
        (0.1, "P10-"),
        (0.100001, "P30-"),
        (0.3, "P30-"),
        (0.300001, "P30-P70"),
        (0.699999, "P30-P70"),
        (0.7, "P70+"),
        (0.899999, "P70+"),
        (0.9, "P90+"),
        (1.0, "P90+"),
    ],
)
def test_all_canonical_band_boundaries_render(percentile: float, band: str) -> None:
    assert _render(percentile=percentile, band=band).startswith(PNG_SIGNATURE)


@pytest.mark.parametrize(
    ("percentile", "band"),
    [
        (0.1, "P30-"),
        (0.3, "P30-P70"),
        (0.7, "P30-P70"),
        (0.9, "P70+"),
    ],
)
def test_band_must_agree_with_percentile(percentile: float, band: str) -> None:
    with pytest.raises(ValueError, match="band does not match percentile"):
        _render(percentile=percentile, band=band)
