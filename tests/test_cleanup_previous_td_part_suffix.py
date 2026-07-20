from scripts.cleanup_previous_td_part_suffix import classify_previous_td


def test_removes_part_from_canonical_previous_td():
    decision = classify_previous_td("06-0012-01742-PART")

    assert decision.action == "normalize"
    assert decision.normalized_value == "06-0012-01742"


def test_removes_trailing_letter_marker_to_reach_canonical_format():
    decision = classify_previous_td("06-0001-00131-A-PART")

    assert decision.action == "normalize_marker"
    assert decision.normalized_value == "06-0001-00131"


def test_skips_legacy_five_digit_middle_group():
    decision = classify_previous_td("02-06012-01742-PART")

    assert decision.action == "skip_legacy_or_malformed"
    assert decision.normalized_value is None


def test_skips_malformed_previous_td():
    decision = classify_previous_td("06-0012-02060/00015-PART")

    assert decision.action == "skip_legacy_or_malformed"
    assert decision.normalized_value is None


def test_ignores_values_without_part_suffix():
    decision = classify_previous_td("06-0012-01742")

    assert decision.action == "not_part_suffix"
    assert decision.normalized_value is None
