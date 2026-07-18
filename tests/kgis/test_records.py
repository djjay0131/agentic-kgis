"""`NormalizedRecord` must be able to *hold* a bad record rather than reject
it — normalization is total, and validation is the single rejection point.
These tests pin that, and the error/warning split it rests on.
"""

import pytest
from pydantic import ValidationError

from kg_contracts.candidates import SourceCoordinates
from kgis.records import NormalizedRecord, RecordIssue, SourceRecord

COORDS = SourceCoordinates(source_type="csv", locator="players.csv#row=1")


def _record(*issues: RecordIssue) -> NormalizedRecord:
    return NormalizedRecord(index=0, coordinates=COORDS, values={"a": 1}, issues=issues)


class TestRecordIssue:
    def test_defaults_to_error_severity(self) -> None:
        assert RecordIssue(code="bad", message="m").severity == "error"

    def test_render_includes_field_when_present(self) -> None:
        issue = RecordIssue(code="coercion_failed", message="not an int", field="age")
        assert issue.render() == "coercion_failed [age]: not an int"

    def test_render_omits_field_when_absent(self) -> None:
        assert RecordIssue(code="empty_row", message="no data").render() == "empty_row: no data"

    def test_is_frozen(self) -> None:
        issue = RecordIssue(code="bad", message="m")
        with pytest.raises(ValidationError):
            issue.code = "other"  # type: ignore[misc]


class TestSourceRecord:
    def test_negative_index_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourceRecord(index=-1, coordinates=COORDS, data={})

    def test_preserves_raw_data_untouched(self) -> None:
        """CSV hands over strings; the reader must not pre-interpret them."""
        record = SourceRecord(index=0, coordinates=COORDS, data={"age": "42"})
        assert record.data == {"age": "42"}


class TestNormalizedRecord:
    def test_a_record_carrying_errors_is_still_constructible(self) -> None:
        """Normalization is total: bad data becomes an issue, never an exception."""
        record = _record(RecordIssue(code="coercion_failed", message="nope", field="age"))
        assert record.has_errors is True

    def test_warnings_alone_do_not_make_a_record_erroneous(self) -> None:
        record = _record(RecordIssue(code="coerced", message="'42' -> 42", severity="warning"))
        assert record.has_errors is False

    def test_errors_and_warnings_partition_issues(self) -> None:
        error = RecordIssue(code="e", message="m", severity="error")
        warning = RecordIssue(code="w", message="m", severity="warning")
        record = _record(error, warning)
        assert record.errors == (error,)
        assert record.warnings == (warning,)

    def test_clean_record_has_no_errors(self) -> None:
        assert _record().has_errors is False

    def test_extras_default_to_empty(self) -> None:
        assert _record().extras == {}
