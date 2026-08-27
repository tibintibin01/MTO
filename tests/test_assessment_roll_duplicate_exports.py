from unittest.mock import MagicMock, patch

from backend.generators import report_gen
from utils.assessment_roll_status import (
    VERIFIED_DUPLICATE_LABEL,
    assessment_roll_duplicate_status,
    assessment_roll_excel_values,
    is_verified_duplicate_assessment_row,
)


def _assessment_row(verified=True):
    row = [None] * 25
    row[0] = 9001
    row[1] = "06-0012-00094"
    row[2] = "SECOND OWNER"
    row[4] = "20-H"
    row[6] = "DINADIAWAN"
    row[7] = "RESIDENTIAL LOT"
    row[9] = 46350
    row[18] = "01-134"
    row[19] = "4085-D-2-F-2"
    row[20] = "02-06012-02007-A-PAR"
    row[21] = "2023-01-01"
    row[22] = "DINADIAWAN"
    row[23] = verified
    return row


def test_verified_duplicate_status_supports_tuple_and_dict_rows():
    assert is_verified_duplicate_assessment_row(_assessment_row()) is True
    assert (
        assessment_roll_duplicate_status({"duplicate_td_verified": True})
        == VERIFIED_DUPLICATE_LABEL
    )
    assert assessment_roll_duplicate_status(_assessment_row(False)) == ""
    assert (
        is_verified_duplicate_assessment_row({"verified_duplicate_td": "false"})
        is False
    )


def test_excel_row_includes_explicit_verified_duplicate_status():
    values, verified = assessment_roll_excel_values(_assessment_row())

    assert verified is True
    assert values[0] == "06-0012-00094"
    assert values[-1] == VERIFIED_DUPLICATE_LABEL


@patch.object(report_gen, "_draw_totals_row")
@patch.object(report_gen, "_draw_data_row", return_value=140)
@patch.object(report_gen, "_draw_table_header_row", return_value=150)
@patch.object(report_gen, "draw_header")
@patch.object(report_gen, "draw_seal")
@patch.object(report_gen.canvas, "Canvas")
def test_pdf_row_includes_status_and_amber_highlight(
    canvas_factory,
    _draw_seal,
    _draw_header,
    _draw_header_row,
    draw_data_row,
    _draw_totals,
    tmp_path,
):
    canvas_factory.return_value = MagicMock()

    report_gen.generate_assessment_roll_pdf(
        [_assessment_row()],
        str(tmp_path),
        as_of_year=2026,
    )

    draw_call = draw_data_row.call_args
    assert draw_call.args[4][-1] == VERIFIED_DUPLICATE_LABEL
    assert draw_call.kwargs["fill_color"] == report_gen._VERIFIED_DUPLICATE_FILL
    assert draw_call.kwargs["text_color"] == report_gen._VERIFIED_DUPLICATE_TEXT
    assert draw_call.kwargs["font_name"] == "Helvetica-Bold"
