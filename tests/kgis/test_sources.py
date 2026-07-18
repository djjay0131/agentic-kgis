"""Every reader passes the same `RecordReaderContract`, then answers for its
own format's quirks — CSV's missing types, JSON's two framings, and the
failure split between "bad record" and "dead source".
"""

from pathlib import Path

import pytest

from kgis.errors import ConfigurationError, SourceReadError
from kgis.sources import (
    UNNAMED_COLUMNS,
    CsvRecordReader,
    IterableRecordReader,
    JsonRecordReader,
    RecordReader,
)
from kgis.testing import CANONICAL_RECORDS, RecordReaderContract

CSV_TEXT = "id,name\n1,Ada\n2,Grace\n3,Alan\n"
JSON_ARRAY = '[{"id": "1", "name": "Ada"}, {"id": "2", "name": "Grace"}, {"id": "3", "name": "Alan"}]'
JSON_LINES = '{"id": "1", "name": "Ada"}\n{"id": "2", "name": "Grace"}\n{"id": "3", "name": "Alan"}\n'


class TestIterableReaderContract(RecordReaderContract):
    def make_reader(self) -> RecordReader:
        return IterableRecordReader(CANONICAL_RECORDS)


class TestCsvReaderContract(RecordReaderContract):
    def make_reader(self) -> RecordReader:
        return CsvRecordReader(text=CSV_TEXT)


class TestJsonArrayReaderContract(RecordReaderContract):
    def make_reader(self) -> RecordReader:
        return JsonRecordReader(text=JSON_ARRAY)


class TestJsonLinesReaderContract(RecordReaderContract):
    def make_reader(self) -> RecordReader:
        return JsonRecordReader(text=JSON_LINES)


class TestIterableReader:
    def test_input_is_snapshotted_at_construction(self) -> None:
        """A source that mutates under the pipeline would silently break replay."""
        rows = [{"id": "1"}]
        reader = IterableRecordReader(rows)
        rows.append({"id": "2"})
        rows[0]["id"] = "mutated"
        records = list(reader.read())
        assert [record.data for record in records] == [{"id": "1"}]

    def test_generators_are_materialized_and_stay_repeatable(self) -> None:
        reader = IterableRecordReader({"id": str(n)} for n in range(3))
        assert len(list(reader.read())) == 3
        assert len(list(reader.read())) == 3

    def test_empty_source_yields_nothing(self) -> None:
        assert list(IterableRecordReader([]).read()) == []


class TestCsvReader:
    def test_values_stay_strings(self) -> None:
        """CSV has no types. Interpreting "42" is normalization's job, not the reader's."""
        [record] = CsvRecordReader(text="id,age\n1,42\n").read()
        assert record.data == {"id": "1", "age": "42"}

    def test_empty_cell_is_empty_string_not_none(self) -> None:
        [record] = CsvRecordReader(text="id,name\n1,\n").read()
        assert record.data["name"] == ""

    def test_fragment_is_the_editor_visible_line_number(self) -> None:
        records = list(CsvRecordReader(text=CSV_TEXT).read())
        assert [r.coordinates.fragment for r in records] == ["row=2", "row=3", "row=4"]

    def test_short_row_reports_missing_columns_as_a_warning(self) -> None:
        [record] = CsvRecordReader(text="id,name,team\n1,Ada\n").read()
        assert record.data["team"] is None
        assert [issue.code for issue in record.issues] == ["short_row"]
        assert record.issues[0].severity == "warning"

    def test_long_row_preserves_surplus_values_rather_than_dropping_them(self) -> None:
        [record] = CsvRecordReader(text="id,name\n1,Ada,extra\n").read()
        assert record.data[UNNAMED_COLUMNS] == ["extra"]
        assert [issue.code for issue in record.issues] == ["unnamed_columns"]

    def test_blank_lines_are_skipped(self) -> None:
        records = list(CsvRecordReader(text="id\n1\n\n2\n").read())
        assert [record.data["id"] for record in records] == ["1", "2"]

    def test_quoted_field_with_embedded_newline_survives(self) -> None:
        [record] = CsvRecordReader(text='id,note\n1,"line one\nline two"\n').read()
        assert record.data["note"] == "line one\nline two"

    def test_custom_delimiter(self) -> None:
        [record] = CsvRecordReader(text="id;name\n1;Ada\n", delimiter=";").read()
        assert record.data == {"id": "1", "name": "Ada"}

    def test_header_only_file_yields_no_records(self) -> None:
        assert list(CsvRecordReader(text="id,name\n").read()) == []

    def test_reads_from_a_path(self, tmp_path: Path) -> None:
        path = tmp_path / "players.csv"
        path.write_text(CSV_TEXT, encoding="utf-8")
        reader = CsvRecordReader(path=path)
        assert [record.data["name"] for record in reader.read()] == ["Ada", "Grace", "Alan"]

    def test_locator_defaults_to_the_file_name_not_the_absolute_path(self, tmp_path: Path) -> None:
        """An absolute path would make identical candidates differ between laptop and CI."""
        path = tmp_path / "players.csv"
        path.write_text(CSV_TEXT, encoding="utf-8")
        assert CsvRecordReader(path=path).locator == "players.csv"

    def test_explicit_locator_wins(self, tmp_path: Path) -> None:
        path = tmp_path / "players.csv"
        path.write_text(CSV_TEXT, encoding="utf-8")
        reader = CsvRecordReader(path=path, locator="s3://bucket/players.csv")
        assert reader.locator == "s3://bucket/players.csv"

    def test_missing_file_is_a_source_read_error(self, tmp_path: Path) -> None:
        reader = CsvRecordReader(path=tmp_path / "nope.csv")
        with pytest.raises(SourceReadError, match="cannot read CSV"):
            list(reader.read())

    def test_requires_exactly_one_of_path_or_text(self) -> None:
        with pytest.raises(ConfigurationError):
            CsvRecordReader()
        with pytest.raises(ConfigurationError):
            CsvRecordReader(path="a.csv", text="id\n1\n")


class TestJsonReader:
    def test_array_and_lines_produce_the_same_data(self) -> None:
        from_array = [r.data for r in JsonRecordReader(text=JSON_ARRAY).read()]
        from_lines = [r.data for r in JsonRecordReader(text=JSON_LINES).read()]
        assert from_array == from_lines

    def test_json_keeps_real_types_unlike_csv(self) -> None:
        [record] = JsonRecordReader(text='[{"id": 1, "active": true, "score": 1.5}]').read()
        assert record.data == {"id": 1, "active": True, "score": 1.5}

    def test_mode_auto_detects_array(self) -> None:
        records = list(JsonRecordReader(text="  " + JSON_ARRAY).read())
        assert [r.coordinates.fragment for r in records] == ["index=0", "index=1", "index=2"]

    def test_mode_auto_detects_lines(self) -> None:
        records = list(JsonRecordReader(text=JSON_LINES).read())
        assert [r.coordinates.fragment for r in records] == ["line=1", "line=2", "line=3"]

    def test_nested_values_survive(self) -> None:
        [record] = JsonRecordReader(text='[{"id": "1", "tags": ["a", "b"]}]').read()
        assert record.data["tags"] == ["a", "b"]

    def test_blank_lines_are_skipped_in_lines_mode(self) -> None:
        records = list(JsonRecordReader(text='{"id": "1"}\n\n{"id": "2"}\n').read())
        assert [r.data["id"] for r in records] == ["1", "2"]

    def test_one_malformed_line_is_one_bad_record_not_a_dead_run(self) -> None:
        """Rejections are data (spec §9): the good records must still ingest."""
        text = '{"id": "1"}\nNOT JSON\n{"id": "2"}\n'
        records = list(JsonRecordReader(text=text).read())
        assert len(records) == 3
        assert [issue.code for issue in records[1].issues] == ["malformed_json"]
        assert records[1].issues[0].severity == "error"
        assert [r.data.get("id") for r in records] == ["1", None, "2"]

    def test_bare_scalar_in_an_array_is_a_bad_record_not_a_crash(self) -> None:
        records = list(JsonRecordReader(text='[{"id": "1"}, 42]').read())
        assert [issue.code for issue in records[1].issues] == ["not_an_object"]
        assert "int" in records[1].issues[0].message

    def test_indices_stay_sequential_across_a_malformed_line(self) -> None:
        text = '{"id": "1"}\nNOT JSON\n{"id": "2"}\n'
        assert [r.index for r in JsonRecordReader(text=text).read()] == [0, 1, 2]

    def test_unparseable_document_is_a_source_read_error(self) -> None:
        """A truncated file has no records — reporting "0 records" would be a lie."""
        with pytest.raises(SourceReadError, match="cannot parse JSON array"):
            list(JsonRecordReader(text='[{"id": "1"},').read())

    def test_top_level_object_in_array_mode_is_a_source_read_error(self) -> None:
        with pytest.raises(SourceReadError, match="expected an array"):
            list(JsonRecordReader(text='{"id": "1"}', mode="array").read())

    def test_empty_document_yields_no_records(self) -> None:
        assert list(JsonRecordReader(text="").read()) == []
        assert list(JsonRecordReader(text="[]").read()) == []

    def test_reads_from_a_path(self, tmp_path: Path) -> None:
        path = tmp_path / "players.json"
        path.write_text(JSON_ARRAY, encoding="utf-8")
        assert [r.data["name"] for r in JsonRecordReader(path=path).read()] == [
            "Ada",
            "Grace",
            "Alan",
        ]

    def test_missing_file_is_a_source_read_error(self, tmp_path: Path) -> None:
        with pytest.raises(SourceReadError, match="cannot read JSON"):
            list(JsonRecordReader(path=tmp_path / "nope.json").read())

    def test_requires_exactly_one_of_path_or_text(self) -> None:
        with pytest.raises(ConfigurationError):
            JsonRecordReader()


class TestReadersAreUniform:
    def test_all_three_formats_yield_identical_data(self) -> None:
        """The pipeline must not be able to tell a CSV from a list of dicts."""
        readers: list[RecordReader] = [
            IterableRecordReader(CANONICAL_RECORDS),
            CsvRecordReader(text=CSV_TEXT),
            JsonRecordReader(text=JSON_ARRAY),
            JsonRecordReader(text=JSON_LINES),
        ]
        payloads = [[record.data for record in reader.read()] for reader in readers]
        assert all(payload == payloads[0] for payload in payloads)

    def test_all_three_satisfy_the_reader_protocol(self) -> None:
        assert isinstance(IterableRecordReader([]), RecordReader)
        assert isinstance(CsvRecordReader(text=""), RecordReader)
        assert isinstance(JsonRecordReader(text=""), RecordReader)
