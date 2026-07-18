"""Normalization must be total and deterministic, and it must make CSV and
JSON say the same thing. The coercion tests here mostly pin what
normalization *refuses* to guess."""

from datetime import UTC, datetime

import pytest

from kg_contracts.candidates import SourceCoordinates
from kgis.normalize import FieldSpec, Normalizer, PassthroughNormalizer, SchemaNormalizer
from kgis.records import RecordIssue, SourceRecord

COORDS = SourceCoordinates(source_type="csv", locator="p.csv", fragment="row=2")


def record(data: dict[str, object], *, issues: tuple[RecordIssue, ...] = ()) -> SourceRecord:
    return SourceRecord(index=0, coordinates=COORDS, data=data, issues=issues)


def codes(normalized_issues: tuple[RecordIssue, ...]) -> list[str]:
    return [issue.code for issue in normalized_issues]


class TestSchemaNormalizerBasics:
    def test_maps_declared_fields(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="id"), FieldSpec(name="age", type="int")])
        result = normalizer.normalize(record({"id": "1", "age": "42"}))
        assert result.values == {"id": "1", "age": 42}
        assert result.has_errors is False

    def test_aliases_map_source_columns_onto_canonical_names(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="id", aliases=("player_id",))])
        assert normalizer.normalize(record({"player_id": "7"})).values == {"id": "7"}

    def test_key_matching_is_case_and_whitespace_insensitive(self) -> None:
        """A stray " Name" header from a spreadsheet is not a modeling decision."""
        normalizer = SchemaNormalizer([FieldSpec(name="name")])
        assert normalizer.normalize(record({" Name ": "Ada"})).values == {"name": "Ada"}

    def test_undeclared_keys_are_preserved_as_extras_not_dropped(self) -> None:
        """A dry run must be able to say which columns the mapping ignores."""
        normalizer = SchemaNormalizer([FieldSpec(name="id")])
        result = normalizer.normalize(record({"id": "1", "nickname": "Countess"}))
        assert result.extras == {"nickname": "Countess"}
        assert result.values == {"id": "1"}

    def test_missing_optional_field_takes_its_default(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="team", default="unknown")])
        assert normalizer.normalize(record({})).values == {"team": "unknown"}

    def test_missing_required_field_is_an_error(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="id", required=True)])
        result = normalizer.normalize(record({}))
        assert result.has_errors is True
        assert codes(result.issues) == ["missing_required"]

    def test_empty_string_counts_as_absent_by_default(self) -> None:
        """CSV cannot tell an empty cell from a missing one."""
        normalizer = SchemaNormalizer([FieldSpec(name="id", required=True)])
        assert normalizer.normalize(record({"id": "   "})).has_errors is True

    def test_empty_as_null_can_be_switched_off(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="note", empty_as_null=False)])
        assert normalizer.normalize(record({"note": ""})).values == {"note": ""}

    def test_reader_issues_are_carried_forward(self) -> None:
        """A reader's "malformed json" must survive to reach validation."""
        normalizer = SchemaNormalizer([FieldSpec(name="id")])
        issue = RecordIssue(code="malformed_json", message="bad line")
        result = normalizer.normalize(record({}, issues=(issue,)))
        assert issue in result.issues

    def test_coordinates_and_index_survive(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="id")])
        result = normalizer.normalize(record({"id": "1"}))
        assert result.coordinates == COORDS
        assert result.index == 0

    def test_two_fields_cannot_claim_the_same_column(self) -> None:
        with pytest.raises(ValueError, match="already claims"):
            SchemaNormalizer([FieldSpec(name="id"), FieldSpec(name="key", aliases=("ID",))])

    def test_satisfies_the_normalizer_protocol(self) -> None:
        assert isinstance(SchemaNormalizer([]), Normalizer)
        assert isinstance(PassthroughNormalizer(), Normalizer)


class TestNormalizationIsTotal:
    def test_bad_values_never_raise(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="age", type="int")])
        result = normalizer.normalize(record({"age": "not a number"}))
        assert result.has_errors is True
        assert result.values["age"] is None

    def test_a_record_of_pure_garbage_still_normalizes(self) -> None:
        normalizer = SchemaNormalizer(
            [FieldSpec(name="a", type="int"), FieldSpec(name="b", type="datetime")]
        )
        result = normalizer.normalize(record({"a": {"nested": 1}, "b": "yesterday"}))
        assert codes(result.issues) == ["coercion_failed", "coercion_failed"]


class TestNormalizationIsDeterministic:
    def test_same_input_same_output(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="id"), FieldSpec(name="age", type="int")])
        source = record({"id": "1", "age": "42"})
        assert normalizer.normalize(source) == normalizer.normalize(source)

    def test_issue_order_follows_declared_field_order(self) -> None:
        normalizer = SchemaNormalizer(
            [FieldSpec(name="a", type="int"), FieldSpec(name="b", type="int")]
        )
        result = normalizer.normalize(record({"a": "x", "b": "y"}))
        assert [issue.field for issue in result.issues] == ["a", "b"]


class TestCoercion:
    """The interesting cases are the ones normalization refuses to guess."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("42", 42), (42, 42), (42.0, 42), ("  42  ", 42), (-7, -7)],
    )
    def test_int_accepts(self, raw: object, expected: int) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="int")])
        assert normalizer.normalize(record({"v": raw})).values["v"] == expected

    @pytest.mark.parametrize("raw", ["42.5", 42.5, True, "abc", [1]])
    def test_int_rejects(self, raw: object) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="int")])
        result = normalizer.normalize(record({"v": raw}))
        assert codes(result.issues) == ["coercion_failed"]

    def test_int_rejects_true_rather_than_reading_it_as_one(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="int")])
        result = normalizer.normalize(record({"v": True}))
        assert "boolean is not an integer" in result.issues[0].message

    @pytest.mark.parametrize(("raw", "expected"), [("1", "1"), (1, "1"), (1.5, "1.5")])
    def test_str_stringifies_numbers_so_csv_and_json_agree(
        self, raw: object, expected: str
    ) -> None:
        """JSON's 1 and CSV's "1" must become the same entity key."""
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="str")])
        assert normalizer.normalize(record({"v": raw})).values["v"] == expected

    @pytest.mark.parametrize("raw", [True, {"a": 1}, [1, 2]])
    def test_str_rejects_values_with_no_unambiguous_string_form(self, raw: object) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="str")])
        assert normalizer.normalize(record({"v": raw})).has_errors is True

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("true", True), ("TRUE", True), ("yes", True), ("1", True), (1, True),
         ("false", False), ("no", False), ("0", False), (0, False), (True, True)],
    )
    def test_bool_accepts(self, raw: object, expected: bool) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="bool")])
        assert normalizer.normalize(record({"v": raw})).values["v"] is expected

    @pytest.mark.parametrize("raw", ["maybe", 2, 1.5])
    def test_bool_rejects(self, raw: object) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="bool")])
        assert normalizer.normalize(record({"v": raw})).has_errors is True

    @pytest.mark.parametrize(("raw", "expected"), [("1.5", 1.5), (1.5, 1.5), (2, 2.0)])
    def test_float_accepts(self, raw: object, expected: float) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="float")])
        assert normalizer.normalize(record({"v": raw})).values["v"] == expected

    def test_datetime_parses_iso8601(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="datetime")])
        result = normalizer.normalize(record({"v": "2026-07-14T12:00:00+00:00"}))
        assert result.values["v"] == datetime(2026, 7, 14, 12, tzinfo=UTC)
        assert result.issues == ()

    def test_datetime_repairs_a_naive_value_but_says_so(self) -> None:
        """An assumed timezone is a real assumption; a bitemporal graph is
        exactly where a silent one does damage (spec §5.4)."""
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="datetime")])
        result = normalizer.normalize(record({"v": "2026-07-14T12:00:00"}))
        assert result.values["v"] == datetime(2026, 7, 14, 12, tzinfo=UTC)
        assert codes(result.issues) == ["assumed_utc"]
        assert result.issues[0].severity == "warning"
        assert result.has_errors is False

    def test_datetime_rejects_prose(self) -> None:
        normalizer = SchemaNormalizer([FieldSpec(name="v", type="datetime")])
        assert normalizer.normalize(record({"v": "last tuesday"})).has_errors is True

    def test_failure_message_names_the_offending_value(self) -> None:
        """ADR-0008 discipline: reject naming the value, never coerce silently."""
        normalizer = SchemaNormalizer([FieldSpec(name="age", type="int")])
        result = normalizer.normalize(record({"age": "abc"}))
        assert "'abc'" in result.issues[0].message
        assert result.issues[0].field == "age"


class TestPassthroughNormalizer:
    def test_carries_data_through_untouched(self) -> None:
        result = PassthroughNormalizer().normalize(record({"id": 1, "raw": {"a": 2}}))
        assert result.values == {"id": 1, "raw": {"a": 2}}

    def test_carries_issues_through(self) -> None:
        issue = RecordIssue(code="not_an_object", message="nope")
        result = PassthroughNormalizer().normalize(record({}, issues=(issue,)))
        assert result.issues == (issue,)


class TestCrossFormatEquivalence:
    def test_csv_strings_and_json_natives_normalize_identically(self) -> None:
        """The whole point of the stage: after this, nothing knows the format."""
        normalizer = SchemaNormalizer(
            [
                FieldSpec(name="id", type="str"),
                FieldSpec(name="age", type="int"),
                FieldSpec(name="rating", type="float"),
                FieldSpec(name="active", type="bool"),
            ]
        )
        from_csv = normalizer.normalize(
            record({"id": "1", "age": "42", "rating": "1.5", "active": "true"})
        )
        from_json = normalizer.normalize(
            record({"id": 1, "age": 42, "rating": 1.5, "active": True})
        )
        assert from_csv.values == from_json.values
