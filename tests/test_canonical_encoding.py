"""Lock the canonical JSON encoding that every digest and signature depends on.

`analysis_run`, `evidence_store`, and `sidecar_auth` each used to carry their
own copy of this encoder. They now share one implementation; these tests exist
so that a future edit to the shared encoder cannot silently invalidate digests
recorded by any of them.
"""

from __future__ import annotations

import hashlib
import json
import unittest

from crypto_options_report._canonical import (
    canonical_json_bytes,
    canonical_json_text,
    canonical_sha256,
    to_jsonable,
)
from crypto_options_report.analysis_run import canonical_sha256 as analysis_sha256
from crypto_options_report.evidence_store import _canonical_json as store_canonical
from crypto_options_report.sidecar_auth import (
    canonical_payload_sha256 as sidecar_sha256,
)

SAMPLES: tuple[dict, ...] = (
    {},
    {"b": 1, "a": 2},
    {"nested": {"z": [1, 2, {"y": None}], "a": True}},
    {"unicode": "期权 · Deribit", "ascii": "plain"},
    {"floats": [0.1, -1.5, 1e-9], "ints": [0, -1, 2**53]},
    {"empty": {"list": [], "dict": {}, "string": ""}},
)


class CanonicalEncodingTests(unittest.TestCase):
    def test_encoding_parameters_are_pinned(self):
        """The exact byte encoding is a compatibility contract, not a preference."""
        payload = {"b": 1, "a": "x", "n": [1, 2]}

        self.assertEqual('{"a":"x","b":1,"n":[1,2]}', canonical_json_text(payload))

    def test_keys_are_sorted_regardless_of_insertion_order(self):
        forward = canonical_json_bytes({"a": 1, "b": 2})
        reverse = canonical_json_bytes({"b": 2, "a": 1})

        self.assertEqual(forward, reverse)

    def test_non_ascii_is_preserved_not_escaped(self):
        self.assertEqual('{"k":"期权"}', canonical_json_text({"k": "期权"}))

    def test_bytes_and_text_encodings_agree(self):
        for sample in SAMPLES:
            with self.subTest(sample=sample):
                self.assertEqual(
                    canonical_json_text(sample).encode("utf-8"),
                    canonical_json_bytes(sample),
                )

    def test_sha256_is_the_digest_of_the_canonical_bytes(self):
        for sample in SAMPLES:
            with self.subTest(sample=sample):
                self.assertEqual(
                    hashlib.sha256(canonical_json_bytes(sample)).hexdigest(),
                    canonical_sha256(sample),
                )

    def test_all_three_consumers_agree_on_every_sample(self):
        """The three modules must stay byte-identical for plain JSON payloads."""
        for sample in SAMPLES:
            with self.subTest(sample=sample):
                expected = canonical_sha256(sample)

                self.assertEqual(expected, analysis_sha256(sample))
                self.assertEqual(expected, sidecar_sha256(sample))
                self.assertEqual(
                    expected,
                    hashlib.sha256(store_canonical(sample)).hexdigest(),
                )

    def test_non_finite_numbers_fail_closed(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_json_bytes({"v": value})

    def test_plain_json_passes_through_to_jsonable_unchanged(self):
        """Pre-processing must not alter payloads that are already JSON-shaped."""
        for sample in SAMPLES:
            with self.subTest(sample=sample):
                self.assertEqual(
                    json.loads(json.dumps(sample)),
                    to_jsonable(sample),
                )

    def test_tuples_encode_as_arrays(self):
        self.assertEqual(
            canonical_json_bytes({"k": [1, 2]}),
            canonical_json_bytes({"k": (1, 2)}),
        )


if __name__ == "__main__":
    unittest.main()
