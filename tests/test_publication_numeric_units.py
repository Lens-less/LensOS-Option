"""Published numeric evidence preserves fraction and percentage units."""

from crypto_options_report.public_api_contract import validate_public_projection
from crypto_options_report.publication import (
    _annotate_numeric_field_evidence,
    _project_signal_artifact,
)
from tests.test_publication_contract_boundary import (
    _measured_signal_at_publication_clock,
)


def test_measured_signal_bucket_rates_keep_fraction_units() -> None:
    source = _measured_signal_at_publication_clock()
    projected = _project_signal_artifact(source)
    assert projected["status"] == "measured"
    bucket_count = 0
    for name, measurement in projected["signals"].items():
        for index, bucket in enumerate(measurement.get("buckets", [])):
            bucket_count += 1
            for field in ("win_rate", "expired_itm_rate"):
                assert bucket[field] == source["signals"][name]["buckets"][index][field]
                assert 0 <= bucket[field] <= 1
                assert bucket["field_evidence"][field] == {
                    "evidence_class": "research_signal_artifact",
                    "unit": "fraction_0_1",
                }
    assert bucket_count > 0
    validate_public_projection("ResearchSignal", projected)


def test_percentage_fields_keep_percent_units() -> None:
    source = {"dvol_percent": 42.5, "rv30_percent": 38.0}
    projected = _annotate_numeric_field_evidence(
        source, evidence_class="validated_underlying_price_history"
    )
    for field, value in source.items():
        assert projected[field] == value
        assert projected["field_evidence"][field]["unit"] == "percent"
