"""Property-based and fuzz regression tests for Nigerian digital postcode parsing & normalization."""
import pytest

from backend.app.services.postcodes.normalization import (
    normalize_digital_postcode,
    parse_national_digital_postcode,
)

VALID_11_CHAR_CODES = [
    "LA-01-A04-IK-02",
    "FC-02-A09-DB-09",
    "EK-01-A03-FK-01",
    "  la-01-a04-ik-02  ",
]

MALFORMED_OR_INVALID_CODES = [
    "",
    "   ",
    None,
    "100001",  # 6-digit legacy is not a digital postcode
    "12345",
    "1234567",
    "LA_01_A04_IK_02",  # wrong separator
    "LA/01/A04/IK/02",
    "LA-1-A04-IK-02",  # wrong LGA width
    "LA-001-A04-IK-02",
    "LAG-01-A04-IK-02",  # wrong state width
    "LA-01-A4-IK-02",  # wrong district width
    "LA-01-A04-I-02",  # wrong area width
    "LA-01-A04-IK-2",  # wrong building width
    "LA-01-A04-IK-02-99",  # extra segment
    "12-01-A04-IK-02",  # digits in state prefix
    "LA-01-A04-IK-02; DROP TABLE postcodes;",  # SQL injection attempt
    "LA-01-A04-IK-02\u200b",  # zero-width Unicode
    "LÀ-01-A04-IK-02",  # accented Unicode
    "A" * 500,  # oversized input
]


@pytest.mark.parametrize("code", VALID_11_CHAR_CODES)
def test_valid_national_digital_postcodes_parse_and_normalize(code):
    parsed = parse_national_digital_postcode(code)
    assert parsed is not None
    assert parsed["canonical_code"] == code.strip().upper()
    assert normalize_digital_postcode(code) == code.strip().upper()


@pytest.mark.parametrize("bad_input", MALFORMED_OR_INVALID_CODES)
def test_malformed_and_fuzz_inputs_fail_closed(bad_input):
    assert parse_national_digital_postcode(bad_input) is None
    assert normalize_digital_postcode(bad_input) is None
