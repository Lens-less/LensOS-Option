from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_options_report.storage import (
    atomic_write_text,
    read_json_object_from_regular_file,
    read_json_object_from_stream,
    read_regular_file_bytes,
    read_stream_bytes_bounded,
)


class ReadRegularFileBytesTests(unittest.TestCase):
    def test_directory_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "state-dir"
            directory.mkdir()

            with self.assertRaises((IsADirectoryError, PermissionError)):
                read_regular_file_bytes(
                    directory,
                    max_bytes=8,
                    description="state directory",
                )

    def test_non_regular_file_handle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "state.json"
            candidate.write_bytes(b"{}")

            with patch(
                "crypto_options_report.storage.os.fstat",
                return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO),
            ), self.assertRaisesRegex(ValueError, "must be a regular file"):
                read_regular_file_bytes(
                    candidate,
                    max_bytes=8,
                    description="state file",
                )


class ReadStreamBytesBoundedTests(unittest.TestCase):
    def test_reads_within_limit_and_rejects_oversize_payloads(self):
        self.assertEqual(
            b"abcd",
            read_stream_bytes_bounded(
                io.BytesIO(b"abcd"),
                max_bytes=4,
                description="bounded stream",
            ),
        )

        with self.assertRaisesRegex(ValueError, "exceeds 4 bytes"):
            read_stream_bytes_bounded(
                io.BytesIO(b"abcde"),
                max_bytes=4,
                description="bounded stream",
            )

    def test_rejects_non_bytes_stream_reads(self):
        class TextStream:
            def read(self, _size: int) -> str:
                return "not-bytes"

        with self.assertRaisesRegex(ValueError, "did not return bytes"):
            read_stream_bytes_bounded(
                TextStream(),
                max_bytes=8,
                description="text stream",
            )


class ReadJsonObjectTests(unittest.TestCase):
    def test_regular_file_rejects_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid-utf8.json"
            path.write_bytes(b"\x80")

            with self.assertRaises(UnicodeDecodeError):
                read_json_object_from_regular_file(
                    path,
                    max_bytes=8,
                    description="invalid utf8 payload",
                )

    def test_regular_file_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text("{", encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                read_json_object_from_regular_file(
                    path,
                    max_bytes=8,
                    description="invalid json payload",
                )

    def test_regular_file_rejects_non_object_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, raw in (
                ("array.json", b"[]"),
                ("scalar.json", b"1"),
            ):
                path = Path(tmp) / name
                path.write_bytes(raw)

                with self.subTest(path=path.name):
                    with self.assertRaisesRegex(ValueError, "must be a JSON object"):
                        read_json_object_from_regular_file(
                            path,
                            max_bytes=8,
                            description="json payload",
                        )

    def test_stream_rejects_invalid_utf8(self):
        with self.assertRaises(UnicodeDecodeError):
            read_json_object_from_stream(
                io.BytesIO(b"\x80"),
                max_bytes=8,
                description="invalid utf8 stream",
            )

    def test_stream_rejects_non_object_json(self):
        for raw in (b"[]", b"1"):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, "must be a JSON object"):
                    read_json_object_from_stream(
                        io.BytesIO(raw),
                        max_bytes=8,
                        description="json stream",
                    )

    def test_reads_json_object_from_regular_file_and_stream(self):
        expected = {"status": "ok", "count": 2}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payload.json"
            path.write_text(json.dumps(expected), encoding="utf-8")

            self.assertEqual(
                expected,
                read_json_object_from_regular_file(
                    path,
                    max_bytes=64,
                    description="json payload",
                ),
            )

        self.assertEqual(
            expected,
            read_json_object_from_stream(
                io.BytesIO(json.dumps(expected).encode("utf-8")),
                max_bytes=64,
                description="json stream",
            ),
        )


class AtomicWriteTextTests(unittest.TestCase):
    def test_atomic_write_replaces_existing_file_without_temp_leftovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            target.write_text("old", encoding="utf-8")
            seen: dict[str, object] = {}
            real_replace = os.replace

            def observe_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
                source_path = Path(source)
                destination_path = Path(destination)
                seen["source_exists_before"] = source_path.exists()
                seen["source_contents_before"] = source_path.read_text(encoding="utf-8")
                seen["destination_contents_before"] = destination_path.read_text(
                    encoding="utf-8"
                )
                real_replace(source, destination)
                seen["source_exists_after"] = source_path.exists()

            with patch(
                "crypto_options_report.storage.os.replace",
                side_effect=observe_replace,
            ):
                written = atomic_write_text(target, "new")

            self.assertEqual(target.resolve(), written)
            self.assertEqual("new", target.read_text(encoding="utf-8"))
            self.assertEqual("old", seen["destination_contents_before"])
            self.assertEqual("new", seen["source_contents_before"])
            self.assertTrue(seen["source_exists_before"])
            self.assertFalse(seen["source_exists_after"])
            self.assertEqual([], list(target.parent.glob(f".{target.name}.*.tmp")))


if __name__ == "__main__":
    unittest.main()
